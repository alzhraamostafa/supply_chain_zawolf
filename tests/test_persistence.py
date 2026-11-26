import os
import sqlite3
import tempfile
from contextlib import contextmanager

import pytest
from api.service import ApiService
from common.access import AccessDenied, Principal, Quote, QuoteStore
from common.approval import ApprovalError, ApprovalWorkflow
from common.audit import AuditLog

BUYER = Principal("alice", "factory-1", "buyer")
MANAGER = Principal("carol", "factory-1", "procurement_manager")
SUP_A = Principal("sa", "supplier-A", "supplier")
SUP_B = Principal("sb", "supplier-B", "supplier")


@contextmanager
def service(path):
    svc = ApiService(path)
    try:
        yield svc
    finally:
        svc.close()


def test_approvals_survive_a_restart_and_decisions_stay_final():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "state.db")
        with service(path) as first:
            req = first.submit_approval(BUYER, "create_po", 100_000)
        with service(path) as second:                      # a restart
            assert second.approvals.get(req["id"]).status == "pending"
            assert second.decide_approval(MANAGER, req["id"], True)["status"] == "approved"
        with service(path) as third:
            assert third.approvals.get(req["id"]).status == "approved"
            with pytest.raises(ApprovalError):
                third.decide_approval(MANAGER, req["id"], False, "changed my mind")


def test_quotes_survive_a_restart_and_suppliers_stay_isolated():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "state.db")
        with service(path) as first:
            qa = first.submit_quote(SUP_A, "factory-1", "Glycerin", 100.0)
        with service(path) as second:
            assert second.get_quote(SUP_A, qa["quote_id"])["price_egp"] == 100.0
            with pytest.raises(AccessDenied):
                second.get_quote(SUP_B, qa["quote_id"])
            assert [q["quote_id"] for q in second.list_quotes(BUYER)] == [qa["quote_id"]]


def test_the_audit_log_survives_a_restart():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "state.db")
        with service(path) as first:
            first.submit_approval(BUYER, "create_po", 1_000)
        with service(path) as second:
            actions = [e["action"] for e in second.list_audit(MANAGER)]
    assert "approval_requested:create_po" in actions


def test_a_decided_request_cannot_be_changed_or_deleted_even_with_raw_sql():
    audit = AuditLog()
    wf = ApprovalWorkflow(audit)
    req = wf.submit("alice", "create_po", 1_000)
    wf.decide(req.id, "bob", "buyer", True)
    with pytest.raises(sqlite3.DatabaseError):
        wf.con.execute("UPDATE approval_requests SET status = 'rejected' WHERE id = ?", (req.id,))
    with pytest.raises(sqlite3.DatabaseError):
        wf.con.execute("DELETE FROM approval_requests WHERE id = ?", (req.id,))
    assert wf.get(req.id).status == "approved"


def test_a_stale_second_decision_cannot_overwrite_the_first():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "state.db")
        audit = AuditLog(path)
        wf1 = ApprovalWorkflow(audit, db_path=path)
        wf2 = ApprovalWorkflow(audit, db_path=path)
        try:
            req = wf1.submit("alice", "create_po", 1_000)
            stale = wf2.get(req.id)                        # wf2 still believes the request is pending
            wf1.decide(req.id, "bob", "buyer", True)
            wf2.get = lambda _request_id: stale
            with pytest.raises(ApprovalError):
                wf2.decide(req.id, "carol", "buyer", False, "too late")
            assert wf1.get(req.id).status == "approved"
        finally:
            wf2.close()
            wf1.close()
            audit.close()


def test_quotes_cannot_be_changed_or_deleted_and_ids_are_unique():
    store = QuoteStore()
    quote = Quote("q-1", "supplier-A", "factory-1", "Glycerin", 100.0)
    store.add(quote)
    with pytest.raises(ValueError):
        store.add(quote)
    with pytest.raises(sqlite3.DatabaseError):
        store.con.execute("UPDATE quotes SET price_egp = 1 WHERE quote_id = 'q-1'")
    with pytest.raises(sqlite3.DatabaseError):
        store.con.execute("DELETE FROM quotes WHERE quote_id = 'q-1'")