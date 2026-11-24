import os
import sqlite3
import tempfile

from fastapi.testclient import TestClient

from api.main import create_app
from api.service import ApiService

SCHEMA = """
CREATE TABLE dim_products (item_code TEXT);
CREATE TABLE materials (material_id INTEGER, material_name TEXT);
CREATE TABLE packaging_items (packaging_sku TEXT);
CREATE TABLE product_bom_items (item_code TEXT, material_id INTEGER, weight_fraction REAL);
CREATE TABLE product_packaging_items (item_code TEXT, packaging_sku TEXT);
CREATE TABLE fact_procurement_rfq (rfq_id INTEGER, rfq_date TEXT, supplier_id TEXT, material_sku_code TEXT,
    contracted_lead_time_days INTEGER, actual_delivered_lead_time_days INTEGER, supplier_quality_yield_rate REAL);
"""


def make_plant_db(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO dim_products VALUES (?)", [("P1",), ("P2",), ("P3",), ("P4",)])
    con.executemany("INSERT INTO materials VALUES (?,?)", [(1, "Glycerin"), (2, "Carbomer")])
    con.executemany("INSERT INTO product_bom_items VALUES (?,?,?)",
                    [("P1", 1, 1.0), ("P2", 1, 1.0), ("P3", 1, 0.5), ("P3", 2, 0.5)])
    rows = [(i, f"2026-01-{i + 1:02d}", "S1", "Glycerin", 8, 8, 0.995) for i in range(10)]
    con.executemany("INSERT INTO fact_procurement_rfq VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def who(user, org, role):
    return {"X-User-Id": user, "X-Org-Id": org, "X-Role": role}


BUYER = who("alice", "factory-1", "buyer")
MANAGER = who("carol", "factory-1", "procurement_manager")
SUPPLIER = who("sa", "supplier-A", "supplier")


def late_glycerin():
    return {"po_number": "PO-1", "material": "Glycerin", "supplier": "S1", "ordered_qty": 100,
            "promised_date": "2026-12-03", "original_needed_by": "2026-12-07", "needed_by": "2026-12-07",
            "eta": "2026-12-10"}


def client(folder):
    path = os.path.join(folder, "plant.db")
    make_plant_db(path)
    return TestClient(create_app(ApiService(plant_db_path=path)))


def test_supplier_cannot_read_delivery_reports():
    with tempfile.TemporaryDirectory() as folder:
        r = client(folder).post("/delivery/assess", json={"shipments": [late_glycerin()]}, headers=SUPPLIER)
    assert r.status_code == 403


def test_buyer_gets_the_delivery_envelope():
    with tempfile.TemporaryDirectory() as folder:
        r = client(folder).post("/delivery/assess",
                                json={"today": "2026-11-23", "shipments": [late_glycerin()]}, headers=BUYER)
    assert r.status_code == 200
    body = r.json()
    assert body["component"] == "delivery_agent" and body["requires_human_approval"] is True
    report = body["payload"]["reports"][0]
    assert report["severity"] == "critical" and report["cause"] == "supplier" and report["slack_days"] == -3


def test_bad_input_is_rejected():
    with tempfile.TemporaryDirectory() as folder:
        c = client(folder)
        assert c.post("/delivery/assess", json={"shipments": []}, headers=BUYER).status_code == 422
        bad_date = dict(late_glycerin(), eta="not-a-date")
        assert c.post("/delivery/assess", json={"shipments": [bad_date]}, headers=BUYER).status_code == 422
        bad_qty = dict(late_glycerin(), ordered_qty=0)
        assert c.post("/delivery/assess", json={"shipments": [bad_qty]}, headers=BUYER).status_code == 422


def test_delivery_calls_appear_in_the_audit_log():
    with tempfile.TemporaryDirectory() as folder:
        c = client(folder)
        c.post("/delivery/assess", json={"today": "2026-11-23", "shipments": [late_glycerin()]}, headers=BUYER)
        entries = c.get("/audit", headers=MANAGER).json()
    assert any(e["action"] == "delivery_assessed" for e in entries)