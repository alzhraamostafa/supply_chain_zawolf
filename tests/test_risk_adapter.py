import sqlite3

from risk.adapter import assess_all, load_histories

SCHEMA = """
CREATE TABLE dim_products (item_code TEXT);
CREATE TABLE materials (material_id INTEGER, material_name TEXT);
CREATE TABLE packaging_items (packaging_sku TEXT);
CREATE TABLE product_bom_items (item_code TEXT, material_id INTEGER, weight_fraction REAL);
CREATE TABLE product_packaging_items (item_code TEXT, packaging_sku TEXT);
CREATE TABLE fact_procurement_rfq (rfq_id INTEGER, rfq_date TEXT, supplier_id TEXT, material_sku_code TEXT,
    contracted_lead_time_days INTEGER, actual_delivered_lead_time_days INTEGER, supplier_quality_yield_rate REAL);
"""


def db():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO dim_products VALUES (?)", [("P1",), ("P2",), ("P3",), ("P4",)])
    con.executemany("INSERT INTO materials VALUES (?,?)", [(1, "Glycerin"), (2, "Carbomer"), (3, "Unused_Dye")])
    con.execute("INSERT INTO packaging_items VALUES ('BOTTLE')")
    # Glycerin is in 3 of 4 products, Carbomer in 1, the bottle in 2
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
    return con


def by_name(loaded):
    return {h.material: h for h in loaded.histories}


def test_histories_are_built_from_rfq_rows():
    h = by_name(load_histories(db()))
    assert len(h["Glycerin"].deliveries) == 10 and h["Glycerin"].n_suppliers == 1
    assert [d.actual_days - d.contracted_days for d in h["Glycerin"].deliveries].count(3) == 2
    assert h["Carbomer"].n_suppliers == 2


def test_criticality_is_the_share_of_products_using_the_item():
    h = by_name(load_histories(db()))
    assert h["Glycerin"].criticality == 0.75
    assert h["Carbomer"].criticality == 0.25
    assert h["BOTTLE"].criticality == 0.5


def test_items_without_history_are_unknown_not_safe():
    results = {a.material: a for a in assess_all(db())}
    assert results["Unused_Dye"].level == "unknown" and results["BOTTLE"].level == "unknown"


def test_rfq_sku_with_no_bom_match_is_reported():
    loaded = load_histories(db())
    assert loaded.unmatched_skus == ["MYSTERY_SKU"]


def test_stock_cover_switches_on_the_shortage_probability():
    results = {a.material: a for a in assess_all(db(), cover_days={"Glycerin": 6})}
    assert results["Glycerin"].shortage_probability == 1.0          # 6 days of cover < 8-day lead time
    assert results["Carbomer"].shortage_probability is None


def test_results_are_sorted_most_severe_first():
    results = assess_all(db(), cover_days={"Glycerin": 6})
    assert results[0].material == "Glycerin"
    assert results[-1].level == "unknown"