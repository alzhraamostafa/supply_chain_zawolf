"""Maker-Checker approval workflow. Every step is written to the audit log."""
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
    def __init__(self, audit: AuditLog, thresholds=None):
        self.audit = audit
        self.thresholds = thresholds or DEFAULT_THRESHOLDS
        self.requests: dict[str, ApprovalRequest] = {}

    def required_role(self, amount_egp: float) -> str:
        for limit, role in self.thresholds:
            if amount_egp <= limit:
                return role
        return self.thresholds[-1][1]

    def submit(self, maker: str, action: str, amount_egp: float) -> ApprovalRequest:
        if not maker or not action:
            raise ValueError("maker and action are required")
        if amount_egp < 0:
            raise ValueError("amount_egp cannot be negative")
        req = ApprovalRequest(id=str(uuid4()), action=action, amount_egp=amount_egp,
                              maker=maker, required_role=self.required_role(amount_egp))
        self.requests[req.id] = req
        self.audit.record(maker, f"approval_requested:{action}",
                          output_ref=req.id, approval_status="pending")
        return req

    def decide(self, request_id: str, checker: str, checker_role: str,
               approve: bool, reason: str | None = None) -> ApprovalRequest:
        req = self.requests.get(request_id)
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
        req.status = "approved" if approve else "rejected"
        req.checker, req.reason = checker, reason
        req.decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.audit.record(checker, f"approval_{req.status}:{req.action}",
                          input_ref=req.id, approval_status=req.status)
        return req
