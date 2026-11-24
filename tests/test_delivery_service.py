import os
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest
from api.delivery_service import DeliveryService
from api.service import ApiService, Forbidden
from common.access import Principal

TODAY = date(2026, 11, 23)
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


def day(n):
    return TODAY + timedelta(days=n)


def shipment(po, material, **over):
    base = dict(po_number=po, material=material, supplier="S1", ordered_qty=100, promised_date=day(10),
                original_needed_by=day(14), needed_by=day(14), eta=day(10))
    base.update(over)
    return base


def reports(env):
    return {r["po_number"]: r for r in env["payload"]["reports"]}


def with_plant(folder):
    path = os.path.join(folder, "plant.db")
    make_plant_db(path)
    return DeliveryService(ApiService().audit, path)


def test_suppliers_cannot_read_delivery_reports():
    with pytest.raises(Forbidden):
        DeliveryService(ApiService().audit).assess(SUPPLIER, [shipment("A", "Glycerin")], TODAY)


def test_at_least_one_shipment_and_no_stray_fields():
    svc = DeliveryService(ApiService().audit)
    with pytest.raises(ValueError):
        svc.assess(BUYER, [], TODAY)
    with pytest.raises(ValueError):
        svc.assess(BUYER, [shipment("A", "Glycerin", colour="red")], TODAY)


def test_plant_context_fills_criticality_and_alternatives():
    with tempfile.TemporaryDirectory() as folder:
        svc = with_plant(folder)
        env = svc.assess(BUYER, [
            shipment("G", "Glycerin", eta=day(17)),       # 3 days short; used by 3 of 4 products, one supplier
            shipment("C", "Carbomer", eta=day(15)),       # 1 day short; used by 1 of 4 products, two suppliers
        ], TODAY)
    r = reports(env)
    assert r["G"]["severity"] == "critical"
    assert any("No alternative supplier on file" in a for a in r["G"]["actions"])
    assert r["C"]["severity"] == "warning"
    assert any("alternative supplier (1 on file)" in a for a in r["C"]["actions"])
    assert env["component"] == "delivery_agent" and env["requires_human_approval"] is True


def test_values_from_the_caller_win_over_the_database():
    with tempfile.TemporaryDirectory() as folder:
        svc = with_plant(folder)
        env = svc.assess(BUYER, [shipment("C", "Carbomer", eta=day(15), criticality=0.95,
                                          alternative_suppliers=5)], TODAY)
    r = reports(env)["C"]
    assert r["severity"] == "critical" and any("(5 on file)" in a for a in r["actions"])


def test_material_not_in_the_bom_is_treated_as_critical():
    with tempfile.TemporaryDirectory() as folder:
        svc = with_plant(folder)
        env = svc.assess(BUYER, [shipment("M", "MYSTERY_SKU", eta=day(15)),
                                 shipment("Z", "Not_In_Database", eta=day(15))], TODAY)
    r = reports(env)
    assert r["M"]["severity"] == "critical" and r["Z"]["severity"] == "critical"
    assert env["confidence"] == 0.25          # M has its supplier count (1 of 2 context items), Z has none


def test_works_without_a_plant_database_but_says_how_little_it_knows():
    env = DeliveryService(ApiService().audit).assess(BUYER, [shipment("A", "Glycerin", eta=day(15))], TODAY)
    assert env["confidence"] == 0.0 and env["payload"]["reports"][0]["severity"] == "critical"
    assert env["source"] == ["shipments supplied by the caller"]


def test_delivery_requests_are_audited():
    audit = ApiService().audit
    env = DeliveryService(audit).assess(BUYER, [shipment("A", "Glycerin")], TODAY)
    last = audit.entries("alice")[-1]
    assert last["action"] == "delivery_assessed" and last["output_ref"] == env["id"]