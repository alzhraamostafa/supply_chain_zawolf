"""Data-quality checks on the plant database.
Each check takes a sqlite3 connection and returns a list of problems (empty list = pass)."""
import sqlite3

FK_CHECKS = {
    "product_bom_items.item_code -> dim_products":
        "SELECT COUNT(*) FROM product_bom_items WHERE item_code NOT IN (SELECT item_code FROM dim_products)",
    "product_bom_items.material_id -> materials":
        "SELECT COUNT(*) FROM product_bom_items WHERE material_id NOT IN (SELECT material_id FROM materials)",
    "product_packaging_items.packaging_sku -> packaging_items":
        "SELECT COUNT(*) FROM product_packaging_items WHERE packaging_sku NOT IN (SELECT packaging_sku FROM packaging_items)",
    "fact_procurement_rfq.supplier_id -> dim_suppliers":
        "SELECT COUNT(*) FROM fact_procurement_rfq WHERE supplier_id NOT IN (SELECT supplier_id FROM dim_suppliers)",
}


def bom_fractions_sum_to_one(con: sqlite3.Connection, tol: float = 0.001) -> list[str]:
    rows = con.execute(
        "SELECT item_code, SUM(weight_fraction) FROM product_bom_items GROUP BY item_code").fetchall()
    return [f"{code}: fractions sum to {total:.4f}" for code, total in rows if abs(total - 1) > tol]


def foreign_keys_valid(con: sqlite3.Connection) -> list[str]:
    problems = []
    for name, sql in FK_CHECKS.items():
        n = con.execute(sql).fetchone()[0]
        if n:
            problems.append(f"{name}: {n} orphan rows")
    return problems


def rfq_covers_bom(con: sqlite3.Connection, min_share: float = 0.9) -> list[str]:
    rfq = {r[0] for r in con.execute("SELECT DISTINCT material_sku_code FROM fact_procurement_rfq")}
    problems = []
    for label, sql in (("materials", "SELECT material_name FROM materials"),
                       ("packaging items", "SELECT packaging_sku FROM packaging_items")):
        needed = {r[0] for r in con.execute(sql)}
        share = len(needed & rfq) / len(needed) if needed else 1.0
        if share < min_share:
            problems.append(f"only {len(needed & rfq)} of {len(needed)} {label} appear in RFQs ({share:.0%})")
    return problems


def single_supplier_skus(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT material_sku_code, COUNT(DISTINCT supplier_id) FROM fact_procurement_rfq GROUP BY 1").fetchall()
    single = [sku for sku, n in rows if n < 2]
    if single:
        return [f"{len(single)} of {len(rows)} SKUs have only one supplier, so quotes cannot be compared"]
    return []


def price_spread(con: sqlite3.Connection, max_ratio: float = 3.0) -> list[str]:
    rows = con.execute(
        "SELECT material_sku_code, MAX(initial_rfq_quote_price_egp) * 1.0 / MIN(initial_rfq_quote_price_egp) AS r "
        "FROM fact_procurement_rfq WHERE initial_rfq_quote_price_egp > 0 "
        "GROUP BY 1 HAVING r > ? ORDER BY r DESC", (max_ratio,)).fetchall()
    return [f"{sku}: quoted price varies {ratio:.1f}x" for sku, ratio in rows]


def customer_locations_distinct(con: sqlite3.Connection) -> list[str]:
    n_cust = con.execute("SELECT COUNT(*) FROM dim_customers").fetchone()[0]
    n_loc = con.execute("SELECT COUNT(DISTINCT latitude || ',' || longitude) FROM dim_customers").fetchone()[0]
    if n_cust > 1 and n_loc < n_cust:
        return [f"{n_cust} customers share only {n_loc} distinct location(s)"]
    return []


def positive_quantities_and_prices(con: sqlite3.Connection) -> list[str]:
    n = con.execute(
        "SELECT COUNT(*) FROM fact_procurement_rfq WHERE order_quantity <= 0 OR initial_rfq_quote_price_egp <= 0"
    ).fetchone()[0]
    return [f"{n} RFQ rows with a zero or negative quantity or price"] if n else []


ALL_CHECKS = {
    "bom_fractions_sum_to_one": bom_fractions_sum_to_one,
    "foreign_keys_valid": foreign_keys_valid,
    "rfq_covers_bom": rfq_covers_bom,
    "single_supplier_skus": single_supplier_skus,
    "price_spread": price_spread,
    "customer_locations_distinct": customer_locations_distinct,
    "positive_quantities_and_prices": positive_quantities_and_prices,
}


def run_all(con: sqlite3.Connection) -> dict[str, list[str]]:
    return {name: check(con) for name, check in ALL_CHECKS.items()}
