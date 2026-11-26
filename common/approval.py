"""Maker-Checker approval workflow. Requests are stored in SQLite; every step is written to the audit log."""
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from .audit import AuditLog

ROLE_RANK = {"buyer": 1, "procurement_manager": 2, "finance_manager": 3}

# (max amount in EGP, role needed to approve), ascending.
# PLACEHOLDER VALUES: the Business Analyst owns the real approval thresholds.
DEFAULT_THRESHOLDS = [
    (50_000, "buyer"),
    (500_000, "procurement_manager"),
    (float("inf"), "finance_manager"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    amount_egp REAL NOT NULL CHECK (amount_egp >= 0),
    maker TEXT NOT NULL,
    required_role TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    checker TEXT,
    reason TEXT,
    decided_at TEXT
);
CREATE TRIGGER IF NOT EXISTS approval_decision_is_final BEFORE UPDATE ON approval_requests
WHEN OLD.status <> 'pending'
BEGIN SELECT RAISE(ABORT, 'a decided request cannot change'); END;
CREATE TRIGGER IF NOT EXISTS approval_no_delete BEFORE DELETE ON approval_requests
BEGIN SELECT RAISE(ABORT, 'approval requests cannot be deleted'); END;
"""


class ApprovalError(Exception):
    pass


@dataclass
class ApprovalRequest:
    id: str
    action: str
    amount_egp: float
    maker: str
    required_role: str
    status: str = "pending"
    checker: str | None = None
    reason: str | None = None
    decided_at: str | None = None


class ApprovalWorkflow:
    def __init__(self, audit: AuditLog, thresholds=None, db_path: str = ":memory:"):
        self.audit = audit
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self.con.close()

    def required_role(self, amount_egp: float) -> str:
        for limit, role in self.thresholds:
            if amount_egp <= limit:
                return role
        return self.thresholds[-1][1]

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._lock:
            row = self.con.execute(
                "SELECT id, action, amount_egp, maker, required_role, status, checker, reason, decided_at "
                "FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        return ApprovalRequest(*row) if row else None

    def submit(self, maker: str, action: str, amount_egp: float) -> ApprovalRequest:
        if not maker or not action:
            raise ValueError("maker and action are required")
        if amount_egp < 0:
            raise ValueError("amount_egp cannot be negative")
        req = ApprovalRequest(id=str(uuid4()), action=action, amount_egp=amount_egp,
                              maker=maker, required_role=self.required_role(amount_egp))
        with self._lock:
            self.con.execute(
                "INSERT INTO approval_requests (id, action, amount_egp, maker, required_role, status) "
                "VALUES (?, ?, ?, ?, ?, 'pending')",
                (req.id, req.action, req.amount_egp, req.maker, req.required_role))
            self.con.commit()
        self.audit.record(maker, f"approval_requested:{action}",
                          output_ref=req.id, approval_status="pending")
        return req

    def decide(self, request_id: str, checker: str, checker_role: str,
               approve: bool, reason: str | None = None) -> ApprovalRequest:
        req = self.get(request_id)
        if req is None:
            raise ApprovalError("unknown request")
        if req.status != "pending":
            raise ApprovalError("request already decided")
        if checker == req.maker:
            raise ApprovalError("maker cannot decide their own request")
        if ROLE_RANK.get(checker_role, 0) < ROLE_RANK[req.required_role]:
            raise ApprovalError(f"requires role {req.required_role} or higher")
        if not approve and not reason:
            raise ValueError("a reason is required to reject")
        status = "approved" if approve else "rejected"
        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            # the WHERE clause makes the decision atomic: only one decider can move a request out of 'pending'
            cur = self.con.execute(
                "UPDATE approval_requests SET status = ?, checker = ?, reason = ?, decided_at = ? "
                "WHERE id = ? AND status = 'pending'", (status, checker, reason, decided_at, request_id))
            self.con.commit()
        if cur.rowcount == 0:
            raise ApprovalError("request already decided")
        req.status, req.checker, req.reason, req.decided_at = status, checker, reason, decided_at
        self.audit.record(checker, f"approval_{status}:{req.action}",
                          input_ref=req.id, approval_status=status)
        return req