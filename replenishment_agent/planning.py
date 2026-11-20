"""Deterministic planning math. No database writes, no LLM.

Pipeline:  weekly product orders -> BOM explosion -> weekly material need
           -> mean / std -> reorder point (ROP) and order quantity.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

# base unit stored in the ledger, and how many base units one RFQ price/MOQ unit covers
KIND_UNIT = {
    "chemical":          ("g",   1000),   # RFQ price and MOQ are per kg -> 1000 g
    "primary_packaging": ("pcs", 1),
    "closure_packaging": ("pcs", 1),
}
RFQ_KIND = {"Chemical Gradients": "chemical", "Primary Packaging": "primary_packaging",
            "Closures & Pumps": "closure_packaging"}


def canon(name: str, aliases: dict) -> str:
    return aliases.get(name, name)


# ---------------------------------------------------------------- BOM
def build_bom(con, aliases: dict):
    """One row per product x material: quantity per finished unit in base units (g or pcs).
    Returns (bom DataFrame, warnings list)."""
    import json
    rows, warnings = [], []
    q = """SELECT b.item_code, b.chemical_gradients_json, b.primary_pack_sku, b.closure_cap_sku,
                  p.nominal_size_value_unverified AS size, p.size_unit, p.specific_gravity_observed AS sg
           FROM product_bom_snapshots b JOIN products p USING(item_code)"""
    for r in con.execute(q):
        if r["size_unit"] is None:
            warnings.append(f"{r['item_code']}: size unit not approved, product skipped")
            continue
        # ml -> grams with density; g -> grams as is.  Density/size are UNVERIFIED in the source.
        mass_g = r["size"] * (r["sg"] if r["size_unit"] == "ml" else 1.0)
        for name, share in json.loads(r["chemical_gradients_json"]).items():
            rows.append((r["item_code"], canon(name, aliases), "chemical", "g", share * mass_g))
        if r["primary_pack_sku"]:
            rows.append((r["item_code"], canon(r["primary_pack_sku"], aliases), "primary_packaging", "pcs", 1.0))
        if r["closure_cap_sku"]:
            rows.append((r["item_code"], canon(r["closure_cap_sku"], aliases), "closure_packaging", "pcs", 1.0))
    bom = pd.DataFrame(rows, columns=["item_code", "material", "kind", "unit", "qty_per_unit"])
    # two source names can collapse into one canonical material inside one product
    bom = bom.groupby(["item_code", "material", "kind", "unit"], as_index=False).qty_per_unit.sum()
    return bom, warnings


def scrap_rates(con) -> dict:
    """Scrap per product from production history, used as an allowance on top of the BOM."""
    q = """SELECT item_code, SUM(good_units_produced) g,
                  SUM(scrap_supplier_container+scrap_supplier_cap+scrap_operational_body+
                      scrap_operational_cap+scrap_operational_pump+scrap_operational_plug_ball) s
           FROM production_shift_history GROUP BY item_code"""
    out = {}
    for r in con.execute(q):
        tot = (r["g"] or 0) + (r["s"] or 0)
        out[r["item_code"]] = min(0.15, (r["s"] or 0) / tot) if tot else 0.0
    return out


# ---------------------------------------------------------------- demand
def weekly_units(con, as_of: str) -> pd.DataFrame:
    """Recorded order quantity per week (Mon-Sun) x product. Only COMPLETE weeks up to as_of.
    NOTE: recorded orders are not true demand (lost sales are invisible)."""
    df = pd.read_sql("SELECT order_date, item_code, ordered_quantity_pcs q FROM commercial_order_history", con)
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["week"] = df["order_date"].dt.to_period("W-SUN").dt.start_time
    wk = df.groupby(["week", "item_code"]).q.sum().unstack(fill_value=0)
    first_day, as_of_ts = df["order_date"].min(), pd.Timestamp(as_of)
    full = [w for w in wk.index
            if w >= first_day.normalize() and w + pd.Timedelta(days=6) <= as_of_ts]
    full_index = pd.date_range(min(full), max(full), freq="7D")
    return wk.reindex(full_index, fill_value=0)


def material_weekly(weekly: pd.DataFrame, bom: pd.DataFrame, scrap: dict, use_scrap=True) -> pd.DataFrame:
    """weeks x materials, in base units (g / pcs), gross of scrap allowance."""
    b = bom.copy()
    factor = b["item_code"].map(lambda i: 1 + scrap.get(i, 0.0)) if use_scrap else 1.0
    b["gross"] = b["qty_per_unit"] * factor
    m = b.pivot_table(index="item_code", columns="material", values="gross", aggfunc="sum", fill_value=0.0)
    w = weekly.reindex(columns=m.index, fill_value=0)
    return w.astype(float) @ m


# ---------------------------------------------------------------- sourcing
def sourcing(con, aliases: dict) -> pd.DataFrame:
    """Latest quote, MOQ, supplier and lead-time stats per canonical material (from RFQ history)."""
    df = pd.read_sql("""SELECT r.rfq_id, r.rfq_date, r.supplier_id, s.supplier_name, s.payment_terms,
                               r.material_sku_code, r.material_category, r.contracted_lead_time_days c_lt,
                               r.actual_delivered_lead_time_days a_lt, r.moq_units,
                               r.initial_rfq_quote_price_piastres price
                        FROM procurement_rfq_history r JOIN suppliers s USING(supplier_id)""", con)
    df["material"] = df["material_sku_code"].map(lambda n: canon(n, aliases))
    out = []
    for m, g in df.groupby("material"):
        last = g.sort_values(["rfq_date", "rfq_id"]).iloc[-1]
        out.append(dict(material=m, supplier_id=last.supplier_id, supplier_name=last.supplier_name,
                        payment_terms=last.payment_terms, rfq_id=int(last.rfq_id),
                        price_piastres=int(round(g.price.median())), price_min=int(g.price.min()), price_max=int(g.price.max()),
                        moq_rfq_units=float(g.moq_units.max()),
                        lead_mean=float(g.a_lt.mean()), lead_sd=float(g.a_lt.std(ddof=0)),
                        lead_contracted=float(g.c_lt.mean()), n_rfq=len(g)))
    return pd.DataFrame(out).set_index("material")


# ---------------------------------------------------------------- reorder logic
@dataclass
class Assessment:
    material: str
    kind: str
    unit: str
    status: str = "OK"        # OK | ALERT | STOCK_UNKNOWN | NO_SUPPLIER | NO_DEMAND
    severity: str | None = None
    on_hand: float | None = None
    open_supply: float = 0.0
    mu_week: float = 0.0
    mu_day: float = 0.0
    sigma_day: float = 0.0
    lead_days: int | None = None
    lead_sd: float | None = None
    safety_stock: float | None = None
    rop: float | None = None
    position: float | None = None
    cover_days: float | None = None
    stockout_date: str | None = None
    order_by: str | None = None
    shortfall: float | None = None
    moq_base: int | None = None
    order_qty: int = 0
    supplier_id: str | None = None
    supplier_name: str | None = None
    payment_terms: str | None = None
    rfq_id: int | None = None
    price_piastres: int | None = None
    price_basis: int | None = None
    est_cost_egp: float | None = None
    est_cost_low_egp: float | None = None
    est_cost_high_egp: float | None = None

    def to_dict(self):
        return {k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                for k, v in asdict(self).items()}


def assess_material(material, kind, mat_series: pd.Series, src, stock, open_supply,
                    policy: dict, as_of: str) -> Assessment:
    unit, factor = KIND_UNIT[kind]
    a = Assessment(material=material, kind=kind, unit=unit)
    win, sig_w = policy["window_weeks"], policy["sigma_weeks"]
    a.mu_week = float(mat_series.tail(win).mean())
    a.mu_day = a.mu_week / 7.0
    a.sigma_day = float(mat_series.tail(sig_w).std(ddof=1)) / math.sqrt(7.0) if len(mat_series) > 1 else 0.0
    if a.mu_week <= 0:
        a.status = "NO_DEMAND"
        return a
    if src is None:
        a.status = "NO_SUPPLIER"            # no purchasing history: cannot build a purchase line
        a.on_hand = stock
        return a
    a.supplier_id, a.supplier_name = src["supplier_id"], src["supplier_name"]
    a.payment_terms, a.rfq_id = src["payment_terms"], int(src["rfq_id"])
    a.price_piastres, a.price_basis = int(src["price_piastres"]), factor
    a.moq_base = int(round(src["moq_rfq_units"] * factor))
    a.lead_days = int(math.ceil(src["lead_mean"]))
    a.lead_sd = float(src["lead_sd"])
    z, review = policy["service_level_z"], policy["review_days"]
    a.safety_stock = z * math.sqrt(a.lead_days * a.sigma_day ** 2 + (a.mu_day * a.lead_sd) ** 2)
    a.rop = a.mu_day * a.lead_days + a.safety_stock
    a.open_supply = float(open_supply)
    if stock is None:
        a.status = "STOCK_UNKNOWN"          # never assume zero: the ledger has no opening record
        return a
    a.on_hand = float(stock)
    a.position = a.on_hand + a.open_supply
    a.cover_days = a.on_hand / a.mu_day
    d0 = date.fromisoformat(as_of)
    a.stockout_date = (d0 + timedelta(days=a.cover_days)).isoformat()
    a.order_by = max(d0, d0 + timedelta(days=a.cover_days - a.lead_days)).isoformat()
    if a.position > a.rop:
        a.status = "OK"
        return a
    target = a.mu_day * (a.lead_days + review) + a.safety_stock
    a.shortfall = target - a.position
    a.order_qty = int(math.ceil(a.shortfall / a.moq_base) * a.moq_base)   # round UP to MOQ multiple
    a.severity = "critical" if a.cover_days < a.lead_days else "warning"
    a.status = "ALERT"
    per = a.order_qty / factor / 100.0
    a.est_cost_egp = round(per * a.price_piastres, 2)           # median of all quotes
    a.est_cost_low_egp = round(per * int(src["price_min"]), 2)   # cheapest quote seen
    a.est_cost_high_egp = round(per * int(src["price_max"]), 2)  # dearest quote seen
    return a
