"""The rules behind the API, independent of the web framework (so they are easy to test)."""
import threading
from dataclasses import asdict
from uuid import uuid4

from common.access import BUYER_ROLES, Principal, Quote, QuoteStore
from common.approval import ApprovalWorkflow
from common.audit import AuditLog

AUDIT_READERS = frozenset({"procurement_manager", "finance_manager"})


class Forbidden(Exception):
    """The caller's role does not allow this action."""


class NotFound(Exception):
    pass


class ApiService:
    def __init__(self, audit_path: str = ":memory:"):
        self.audit = AuditLog(audit_path)
        self.approvals = ApprovalWorkflow(self.audit)
        self.quotes = QuoteStore(self.audit)
        self._lock = threading.RLock()

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
            if request_id not in self.approvals.requests:
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
