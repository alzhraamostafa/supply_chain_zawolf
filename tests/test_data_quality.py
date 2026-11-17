import sqlite3

from data_quality.checks import (ALL_CHECKS, bom_fractions_sum_to_one, customer_locations_distinct,
                                 foreign_keys_valid, positive_quantities_and_prices, price_spread,
                                 rfq_covers_bom, run_all, single_supplier_skus)

SCHEMA = """
CREATE TABLE dim_products (item_code TEXT);
CREATE TABLE materials (material_id INTEGER, material_name TEXT);
CREATE TABLE packaging_items (packaging_sku TEXT);
CREATE TABLE product_bom_items (item_code TEXT, material_id INTEGER, weight_fraction REAL);
CREATE TABLE product_packaging_items (item_code TEXT, packaging_sku TEXT);
CREATE TABLE dim_suppliers (supplier_id INTEGER);
CREATE TABLE fact_procurement_rfq (supplier_id INTEGER, material_sku_code TEXT,
    initial_rfq_quote_price_egp REAL, order_quantity REAL);
CREATE TABLE dim_customers (customer_id TEXT, latitude REAL, longitude REAL);
"""


def db():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    return con


def test_bom_fractions():
    con = db()
    con.executemany("INSERT INTO product_bom_items VALUES (?,?,?)",
                    [("A", 1, 0.6), ("A", 2, 0.4), ("B", 1, 0.6), ("B", 2, 0.3)])
    problems = bom_fractions_sum_to_one(con)
    assert len(problems) == 1 and problems[0].startswith("B:")


def test_foreign_keys():
    con = db()
    assert foreign_keys_valid(con) == []
    con.execute("INSERT INTO product_bom_items VALUES ('X', 99, 1.0)")
    problems = foreign_keys_valid(con)
    assert any("dim_products" in p for p in problems) and any("materials" in p for p in problems)


def test_rfq_coverage():
    con = db()
    con.executemany("INSERT INTO materials VALUES (?,?)", [(1, "Glycerin"), (2, "Carbomer")])
    con.execute("INSERT INTO fact_procurement_rfq VALUES (1, 'Glycerin', 10, 5)")
    assert len(rfq_covers_bom(con)) == 1
    con.execute("INSERT INTO fact_procurement_rfq VALUES (1, 'Carbomer', 10, 5)")
    assert rfq_covers_bom(con) == []


def test_single_supplier():
    con = db()
    con.executemany("INSERT INTO fact_procurement_rfq VALUES (?,?,?,?)",
                    [(1, "Glycerin", 10, 5), (1, "Carbomer", 10, 5), (2, "Carbomer", 11, 5)])
    problems = single_supplier_skus(con)
    assert len(problems) == 1 and problems[0].startswith("1 of 2")


def test_price_spread():
    con = db()
    con.executemany("INSERT INTO fact_procurement_rfq VALUES (?,?,?,?)",
                    [(1, "A", 10, 5), (2, "A", 50, 5), (1, "B", 10, 5), (2, "B", 12, 5)])
    problems = price_spread(con)
    assert len(problems) == 1 and problems[0].startswith("A:")


def test_customer_locations():
    con = db()
    con.executemany("INSERT INTO dim_customers VALUES (?,?,?)", [("c1", 30.0, 31.0), ("c2", 30.0, 31.0)])
    assert len(customer_locations_distinct(con)) == 1
    con.execute("UPDATE dim_customers SET latitude = 29.0 WHERE customer_id = 'c2'")
    assert customer_locations_distinct(con) == []


def test_positive_values():
    con = db()
    con.execute("INSERT INTO fact_procurement_rfq VALUES (1, 'A', 0, 5)")
    assert len(positive_quantities_and_prices(con)) == 1


def test_run_all_returns_every_check():
    assert set(run_all(db())) == set(ALL_CHECKS)
