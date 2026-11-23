import os
import sqlite3
import tempfile

import pytest
from api.service import ApiService, Forbidden, Unavailable
from common.access import Principal

BUYER = Principal("alice", "factory-1", "buyer")
SUPPLIER = Principal("sa", "supplier-A", "supplier")

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


def by_material(env):
    return {a["material"]: a for a in env["payload"]["assessments"]}


def test_suppliers_cannot_read_risk():
    with pytest.raises(Forbidden):
        ApiService().assess_risk(SUPPLIER)


def test_risk_needs_a_configured_plant_database():
    with pytest.raises(Unavailable):
        ApiService().assess_risk(BUYER)


def test_buyer_gets_the_envelope_with_every_item():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "plant.db")
        make_plant_db(path)
        env = ApiService(plant_db_path=path).assess_risk(BUYER)
    assert env["component"] == "risk_engine" and env["requires_human_approval"] is True
    assert env["autonomy_level"] == 0 and env["source"]
    payload = env["payload"]
    assert sum(payload["counts"].values()) == 5          # Glycerin, Carbomer, Unused_Dye, BOTTLE, MYSTERY_SKU
    assert payload["unmatched_skus"] == ["MYSTERY_SKU"] and payload["stock_known_for"] == 0


def test_stock_cover_switches_on_the_shortage_probability():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "plant.db")
        make_plant_db(path)
        env = ApiService(plant_db_path=path).assess_risk(BUYER, cover_days={"Glycerin": 6})
    assert by_material(env)["Glycerin"]["shortage_probability"] == 1.0
    assert env["payload"]["stock_known_for"] == 1


def test_level_filter_and_validation():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "plant.db")
        make_plant_db(path)
        svc = ApiService(plant_db_path=path)
        env = svc.assess_risk(BUYER, level="unknown")
        assert env["payload"]["assessments"] and all(a["level"] == "unknown" for a in env["payload"]["assessments"])
        with pytest.raises(ValueError):
            svc.assess_risk(BUYER, level="catastrophic")
        with pytest.raises(ValueError):
            svc.assess_risk(BUYER, cover_days={"Glycerin": -1})


def test_risk_requests_are_audited():
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "plant.db")
        make_plant_db(path)
        svc = ApiService(plant_db_path=path)
        env = svc.assess_risk(BUYER)
        last = svc.audit.entries("alice")[-1]
    assert last["action"] == "risk_assessed" and last["output_ref"] == env["id"]