from fastapi.testclient import TestClient

from api.main import create_app
from api.service import ApiService


def client():
    return TestClient(create_app(ApiService()))


def who(user, org, role):
    return {"X-User-Id": user, "X-Org-Id": org, "X-Role": role}


BUYER = who("alice", "factory-1", "buyer")
MANAGER = who("carol", "factory-1", "procurement_manager")
SUP_A = who("sa", "supplier-A", "supplier")
SUP_B = who("sb", "supplier-B", "supplier")


def test_health_is_open_and_reports_sandbox():
    body = client().get("/health").json()
    assert body == {"status": "ok", "sandbox": True}


def test_missing_identity_is_rejected():
    assert client().get("/quotes").status_code == 401


def test_supplier_cannot_submit_an_approval():
    r = client().post("/approvals", json={"action": "create_po", "amount_egp": 1000}, headers=SUP_A)
    assert r.status_code == 403


def test_approval_flow_over_http():
    c = client()
    r = c.post("/approvals", json={"action": "create_po", "amount_egp": 100000}, headers=BUYER)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    rid = r.json()["id"]
    assert c.post(f"/approvals/{rid}/decision", json={"approve": True}, headers=BUYER).status_code == 409
    ok = c.post(f"/approvals/{rid}/decision", json={"approve": True}, headers=MANAGER)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert c.post("/approvals/missing/decision", json={"approve": True}, headers=MANAGER).status_code == 404
    assert c.get("/audit", headers=BUYER).status_code == 403
    assert c.get("/audit", headers=MANAGER).status_code == 200


def test_invalid_body_is_rejected():
    r = client().post("/approvals", json={"action": "create_po", "amount_egp": -5}, headers=BUYER)
    assert r.status_code == 422


def test_supplier_isolation_over_http():
    c = client()
    qa = c.post("/quotes", json={"buyer_org_id": "factory-1", "sku": "Glycerin", "price_egp": 100}, headers=SUP_A).json()
    c.post("/quotes", json={"buyer_org_id": "factory-1", "sku": "Glycerin", "price_egp": 95}, headers=SUP_B)
    assert c.get(f"/quotes/{qa['quote_id']}", headers=SUP_B).status_code == 404
    assert c.get(f"/quotes/{qa['quote_id']}", headers=SUP_A).status_code == 200
    assert len(c.get("/quotes", headers=SUP_A).json()) == 1
    assert len(c.get("/quotes", headers=BUYER).json()) == 2
