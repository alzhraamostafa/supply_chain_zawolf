import threading

import pytest
from api.service import ApiService, Forbidden, NotFound
from common.access import AccessDenied, Principal
from common.approval import ApprovalError

BUYER = Principal("alice", "factory-1", "buyer")
MANAGER = Principal("carol", "factory-1", "procurement_manager")
SUP_A = Principal("sa", "supplier-A", "supplier")
SUP_B = Principal("sb", "supplier-B", "supplier")


def test_supplier_cannot_submit_or_decide_approvals():
    svc = ApiService()
    with pytest.raises(Forbidden):
        svc.submit_approval(SUP_A, "create_po", 1_000)
    with pytest.raises(Forbidden):
        svc.decide_approval(SUP_A, "any", True)


def test_forbidden_attempts_are_audited():
    svc = ApiService()
    with pytest.raises(Forbidden):
        svc.submit_approval(SUP_A, "create_po", 1_000)
    assert svc.audit.entries("sa")[0]["action"] == "forbidden:submit_approval"


def test_full_approval_flow():
    svc = ApiService()
    req = svc.submit_approval(BUYER, "create_po", 100_000)
    assert req["status"] == "pending" and req["required_role"] == "procurement_manager"
    with pytest.raises(ApprovalError):
        svc.decide_approval(BUYER, req["id"], True)          # maker cannot decide
    done = svc.decide_approval(MANAGER, req["id"], True)
    assert done["status"] == "approved" and done["checker"] == "carol"
    with pytest.raises(ApprovalError):
        svc.decide_approval(MANAGER, req["id"], False, "again")   # decisions are final


def test_unknown_approval_is_not_found():
    with pytest.raises(NotFound):
        ApiService().decide_approval(MANAGER, "nope", True)


def test_only_managers_read_the_audit_log():
    svc = ApiService()
    svc.submit_approval(BUYER, "create_po", 1_000)
    with pytest.raises(Forbidden):
        svc.list_audit(BUYER)
    assert len(svc.list_audit(MANAGER)) >= 1


def test_supplier_isolation_through_the_service():
    svc = ApiService()
    qa = svc.submit_quote(SUP_A, "factory-1", "Glycerin", 100.0)
    qb = svc.submit_quote(SUP_B, "factory-1", "Glycerin", 95.0)
    assert [q["quote_id"] for q in svc.list_quotes(SUP_A)] == [qa["quote_id"]]
    with pytest.raises(AccessDenied):
        svc.get_quote(SUP_A, qb["quote_id"])
    assert {q["quote_id"] for q in svc.list_quotes(BUYER)} == {qa["quote_id"], qb["quote_id"]}


def test_only_suppliers_submit_quotes_and_price_must_be_positive():
    svc = ApiService()
    with pytest.raises(Forbidden):
        svc.submit_quote(BUYER, "factory-1", "Glycerin", 10.0)
    with pytest.raises(ValueError):
        svc.submit_quote(SUP_A, "factory-1", "Glycerin", 0)


def test_service_works_from_other_threads():
    svc = ApiService()
    errors = []

    def work():
        try:
            svc.submit_quote(SUP_A, "factory-1", "Glycerin", 100.0)
            svc.list_quotes(BUYER)
        except Exception as exc:       # any error fails the test below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(svc.list_quotes(BUYER)) == 5
