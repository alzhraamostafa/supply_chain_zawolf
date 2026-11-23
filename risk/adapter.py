"""Build supply histories from the plant database and assess every material.
Works with any DB-API connection: SQLite (schema="") or the shared Postgres (schema="raw")."""
from dataclasses import dataclass, field

from .engine import Delivery, RiskAssessment, SupplyHistory, assess

LEVEL_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}


@dataclass
class Loaded:
    histories: list
    unmatched_skus: list = field(default_factory=list)   # in the RFQ history, but not in any BOM


def _rows(con, sql: str) -> list:
    cur = con.cursor()
    cur.execute(sql)
    return cur.fetchall()


def load_histories(con, schema: str = "", cover_days: dict | None = None) -> Loaded:
    p = f"{schema}." if schema else ""
    cover_days = cover_days or {}

    n_products = _rows(con, f"SELECT COUNT(*) FROM {p}dim_products")[0][0] or 1
    usage = {name: n for name, n in _rows(con, (
        f"SELECT m.material_name, COUNT(DISTINCT b.item_code) FROM {p}product_bom_items b "
        f"JOIN {p}materials m ON m.material_id = b.material_id GROUP BY m.material_name"))}
    usage.update({sku: n for sku, n in _rows(con, (
        f"SELECT packaging_sku, COUNT(DISTINCT item_code) FROM {p}product_packaging_items "
        "GROUP BY packaging_sku"))})
    known = {r[0] for r in _rows(con, f"SELECT material_name FROM {p}materials")}
    known |= {r[0] for r in _rows(con, f"SELECT packaging_sku FROM {p}packaging_items")}

    deliveries: dict = {}
    suppliers: dict = {}
    for sku, supplier, contracted, actual, yld in _rows(con, (
            f"SELECT material_sku_code, supplier_id, contracted_lead_time_days, "
            f"actual_delivered_lead_time_days, supplier_quality_yield_rate "
            f"FROM {p}fact_procurement_rfq ORDER BY rfq_date, rfq_id")):
        deliveries.setdefault(sku, []).append(Delivery(float(contracted), float(actual), float(yld)))
        suppliers.setdefault(sku, set()).add(supplier)

    histories = []
    for sku in sorted(known | set(deliveries)):
        histories.append(SupplyHistory(
            material=sku,
            deliveries=deliveries.get(sku, []),
            n_suppliers=len(suppliers.get(sku, ())),
            criticality=usage.get(sku, 0) / n_products,
            cover_days=cover_days.get(sku)))
    unmatched = sorted(set(deliveries) - known)
    return Loaded(histories, unmatched)


def assess_all(con, schema: str = "", cover_days: dict | None = None) -> list[RiskAssessment]:
    """Every material, most severe first."""
    loaded = load_histories(con, schema, cover_days)
    results = [assess(h) for h in loaded.histories]
    return sorted(results, key=lambda a: (LEVEL_ORDER[a.level], -(a.risk_score or 0), a.material))