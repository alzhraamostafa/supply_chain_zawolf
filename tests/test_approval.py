import pytest
from common.audit import AuditLog
from common.approval import ApprovalWorkflow, ApprovalError


def make():
    audit = AuditLog()
    return ApprovalWorkflow(audit), audit


def test_submit_creates_pending_request_and_audit_row():
    wf, audit = make()
    req = wf.submit("alice", "create_po", 100_000)
    assert req.status == "pending" and req.required_role == "procurement_manager"
    rows = audit.entries("alice")
    assert rows[0]["approval_status"] == "pending" and rows[0]["output_ref"] == req.id


def test_required_role_boundaries():
    wf, _ = make()
    assert wf.required_role(50_000) == "buyer"
    assert wf.required_role(50_001) == "procurement_manager"
    assert wf.required_role(500_001) == "finance_manager"


def test_maker_cannot_decide_own_request():
    wf, _ = make()
    req = wf.submit("alice", "create_po", 1_000)
    with pytest.raises(ApprovalError):
        wf.decide(req.id, "alice", "finance_manager", approve=True)


def test_role_too_low_is_refused():
    wf, _ = make()
    req = wf.submit("alice", "create_po", 100_000)
    with pytest.raises(ApprovalError):
        wf.decide(req.id, "bob", "buyer", approve=True)
    with pytest.raises(ApprovalError):
        wf.decide(req.id, "bob", "intern", approve=True)


def test_approval_is_recorded_and_final():
    wf, audit = make()
    req = wf.submit("alice", "create_po", 100_000)
    done = wf.decide(req.id, "carol", "procurement_manager", approve=True)
    assert done.status == "approved" and done.checker == "carol" and done.decided_at
    assert audit.entries("carol")[0]["approval_status"] == "approved"
    with pytest.raises(ApprovalError):
        wf.decide(req.id, "dave", "finance_manager", approve=False, reason="changed my mind")


def test_rejection_needs_a_reason():
    wf, audit = make()
    req = wf.submit("alice", "create_po", 1_000)
    with pytest.raises(ValueError):
        wf.decide(req.id, "bob", "buyer", approve=False)
    done = wf.decide(req.id, "bob", "buyer", approve=False, reason="price too high")
    assert done.status == "rejected" and done.reason == "price too high"
    assert audit.entries("bob")[0]["approval_status"] == "rejected"


def test_unknown_request_and_negative_amount():
    wf, _ = make()
    with pytest.raises(ApprovalError):
        wf.decide("nope", "bob", "buyer", approve=True)
    with pytest.raises(ValueError):
        wf.submit("alice", "create_po", -5)
