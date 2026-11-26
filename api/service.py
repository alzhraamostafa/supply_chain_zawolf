"""The rules behind the API, independent of the web framework (so they are easy to test)."""
import sqlite3
import threading
from dataclasses import asdict
from uuid import uuid4

from common.access import BUYER_ROLES, Principal, Quote, QuoteStore
from common.approval import ApprovalWorkflow
from common.audit import AuditLog
from risk.adapter import load_histories
from risk.api_payload import build_risk_payload, overall_confidence
from risk.engine import assess
from risk.envelope import portfolio_envelope

AUDIT_READERS = frozenset({"procurement_manager", "finance_manager"})
RISK_SOURCES = ["fact_procurement_rfq", "product_bom_items", "product_packaging_items"]


class Forbidden(Exception):
    """The caller's role does not allow this action."""


class NotFound(Exception):
    pass


class Unavailable(Exception):
    """A needed resource is not configured."""


class ApiService:
    def __init__(self, audit_path: str = ":memory:", plant_db_path: str | None = None):
        self.audit = AuditLog(audit_path)
        self.approvals = ApprovalWorkflow(self.audit, db_path=audit_path)
        self.quotes = QuoteStore(self.audit, db_path=audit_path)
        self.plant_db_path = plant_db_path
        self._lock = threading.RLock()


    def close(self) -> None:
        self.quotes.close()
        self.approvals.close()
        self.audit.close()

    def _require(self, principal: Principal, roles, action: str) -> None:
        if principal.role not in roles:
            self.audit.record(principal.user_id, f"forbidden:{action}")
            raise Forbidden(f"role '{principal.role}' cannot {action}")

    def submit_approval(self, principal: Principal, action: str, amount_egp: float) -> dict:
        with self._lock:
            self._require(principal, BUYER_ROLES, "submit_approval")
            return asdict(self.approvals.submit(principal.user_id, action, amount_egp))

    def decide_approval(self, principal: Principal, request_id: str, approve: bool,
                        reason: str | None = None) -> dict:
        with self._lock:
            self._require(principal, BUYER_ROLES, "decide_approval")
            if self.approvals.get(request_id) is None:
                raise NotFound("approval request not found")
            return asdict(self.approvals.decide(request_id, principal.user_id, principal.role,
                                                approve, reason))

    def list_audit(self, principal: Principal) -> list[dict]:
        with self._lock:
            self._require(principal, AUDIT_READERS, "read_audit")
            return self.audit.entries()

    def submit_quote(self, principal: Principal, buyer_org_id: str, sku: str, price_egp: float) -> dict:
        with self._lock:
            self._require(principal, {"supplier"}, "submit_quote")
            if price_egp <= 0:
                raise ValueError("price_egp must be positive")
            quote = Quote(str(uuid4()), principal.org_id, buyer_org_id, sku, price_egp)
            self.quotes.add(quote)
            self.audit.record(principal.user_id, "quote_submitted", output_ref=quote.quote_id)
            return asdict(quote)

    def list_quotes(self, principal: Principal) -> list[dict]:
        with self._lock:
            return [asdict(q) for q in self.quotes.list_for(principal)]

    def get_quote(self, principal: Principal, quote_id: str) -> dict:
        with self._lock:
            return asdict(self.quotes.get(principal, quote_id))

    def assess_risk(self, principal: Principal, cover_days: dict | None = None,
                    level: str | None = None, limit: int | None = None) -> dict:
        """Risk assessment of every material, wrapped in the envelope. Buyer-side roles only."""
        with self._lock:
            self._require(principal, BUYER_ROLES, "read_risk")
            if not self.plant_db_path:
                raise Unavailable("no plant database is configured (set PLANT_DB_PATH)")
            cover_days = cover_days or {}
            if any(days < 0 for days in cover_days.values()):
                raise ValueError("cover_days cannot be negative")
            con = sqlite3.connect(f"file:{self.plant_db_path}?mode=ro", uri=True)
            try:
                loaded = load_histories(con, "", cover_days)
            finally:
                con.close()
            assessments = [assess(h) for h in loaded.histories]
            payload = build_risk_payload(assessments, loaded.unmatched_skus, level, limit)
            envelope = portfolio_envelope(payload, overall_confidence(assessments), RISK_SOURCES)
            self.audit.record(principal.user_id, "risk_assessed", output_ref=envelope.id)
            return envelope.model_dump(mode="json")