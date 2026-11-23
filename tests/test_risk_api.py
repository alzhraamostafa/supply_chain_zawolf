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
    con.executemany("INSERT INTO materials VALUES (?,?)", [(1, "Glycerin"), (2, "Carbomer"), (3, "Unused_Dye")])
    con.execute("INSERT INTO packaging_items VALUES ('BOTTLE')")
    con.executemany("INSERT INTO product_bom_items VALUES (?,?,?)",
                    [("P1", 1, 1.0), ("P2", 1, 1.0), ("P3", 1, 0.5), ("P3", 2, 0.5)])
    con.executemany("INSERT INTO product_packaging_items VALUES (?,?)", [("P1", "BOTTLE"), ("P2", "BOTTLE")])
    rows = []
    for i in range(10):
        late = 3 if i in (2, 5) else 0
        rows.append((i, f"2026-01-{i + 1:02d}", "S1", "Glycerin", 8, 8 + late, 0.995))
    rows.append((20, "2026-02-01", "S1", "Carbomer", 5, 5, 0.99))
    rows.append((21, "2026-02-02", "S2", "Carbomer", 5, 5, 0.99))
    rows.append((30, "2026-02-03", "S3", "MYSTERY_SKU", 6, 6, 0.99))
    con.executemany("INSERT INTO fact_procurement_rfq VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def who(user, org, role):
    return {"X-User-Id": user, "X-Org-Id": org, "X-Role": role}


BUYER = who("alice", "factory-1", "buyer")
MANAGER = who("carol", "factory-1", "procurement_manager")
SUPPLIER = who("sa", "supplier-A", "supplier")


def client_with_plant(folder):
    path = os.path.join(folder, "plant.db")
    make_plant_db(path)
    return TestClient(create_app(ApiService(plant_db_path=path)))


def test_supplier_cannot_read_risk():
    with tempfile.TemporaryDirectory() as folder:
        assert client_with_plant(folder).get("/risk", headers=SUPPLIER).status_code == 403


def test_buyer_gets_the_risk_envelope():
    with tempfile.TemporaryDirectory() as folder:
        r = client_with_plant(folder).get("/risk", headers=BUYER)
    assert r.status_code == 200
    body = r.json()
    assert body["component"] == "risk_engine" and body["requires_human_approval"] is True
    assert sum(body["payload"]["counts"].values()) == 5


def test_stock_figures_switch_on_the_shortage_probability():
    with tempfile.TemporaryDirectory() as folder:
        r = client_with_plant(folder).post("/risk/assess", json={"cover_days": {"Glycerin": 6}}, headers=BUYER)
    assert r.status_code == 200 and r.json()["payload"]["stock_known_for"] == 1


def test_bad_input_is_rejected():
    with tempfile.TemporaryDirectory() as folder:
        c = client_with_plant(folder)
        assert c.get("/risk?level=catastrophic", headers=BUYER).status_code == 422
        assert c.post("/risk/assess", json={"cover_days": {"Glycerin": -2}}, headers=BUYER).status_code == 422


def test_missing_plant_database_is_a_503():
    c = TestClient(create_app(ApiService()))
    assert c.get("/risk", headers=BUYER).status_code == 503


def test_risk_calls_appear_in_the_audit_log():
    with tempfile.TemporaryDirectory() as folder:
        c = client_with_plant(folder)
        c.get("/risk", headers=BUYER)
        entries = c.get("/audit", headers=MANAGER).json()
    assert any(e["action"] == "risk_assessed" for e in entries)