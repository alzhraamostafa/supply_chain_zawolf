
from __future__ import annotations
from datetime import date
from typing import Optional

from backend.database import query_records, scalar, columns_for


DATE_COLUMNS = {
    "sales": ("fact_commercial_demand_m5", "order_date"),
    "production": ("fact_production_shifts", "production_date"),
    "fleet": ("fact_lastmile_fleet_dispatch", "dispatch_date"),
    "procurement": ("fact_procurement_rfq", "rfq_date"),
}

REQUIRED = {
    "fact_commercial_demand_m5": {
        "order_date", "actual_orders_demanded_pcs",
        "gross_wholesale_revenue_egp", "net_gross_profit_egp",
        "ai_forecast_accuracy_rate", "demand_forecast_variance_pcs"
    },
    "fact_production_shifts": {
        "production_date", "good_units_produced",
        "total_scrap_units", "oee", "availability",
        "performance", "quality", "target_oee"
    },
    "fact_lastmile_fleet_dispatch": {
        "dispatch_date", "on_time_delivery_compliance",
        "payload_capacity_utilization_pct",
        "cuopt_dynamic_savings_egp"
    },
    "fact_procurement_rfq": {
        "rfq_date", "actual_delivered_lead_time_days",
        "contracted_lead_time_days", "supplier_quality_yield_rate",
        "procurement_savings_egp"
    },
}


def date_where(column: str, start_date: Optional[str], end_date: Optional[str]):
    clauses, params = [], []

    if start_date:
        clauses.append(f"{column} >= ?")
        params.append(start_date)

    if end_date:
        clauses.append(f"{column} <= ?")
        params.append(end_date)

    return (
        " WHERE " + " AND ".join(clauses) if clauses else "",
        tuple(params)
    )


def validate_dates(start_date, end_date):
    for label, value in (
        ("start_date", start_date),
        ("end_date", end_date)
    ):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ValueError(f"{label} must use YYYY-MM-DD.")

    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")


def data_health():
    objects = query_records("""
        SELECT name, type
        FROM sqlite_master
        WHERE type IN ('table','view')
        ORDER BY type, name
    """)

    checks = []

    for table, required in REQUIRED.items():
        actual = (
            columns_for(table)
            if any(o["name"] == table for o in objects)
            else set()
        )

        missing = sorted(required - actual)

        checks.append({
            "object": table,
            "status": "ok" if not missing else "missing_columns",
            "missing_columns": missing
        })

    view_cols = (
        columns_for("vw_fefo_expiry_risk")
        if any(o["name"] == "vw_fefo_expiry_risk" for o in objects)
        else set()
    )

    fefo_required = {
        "batch_lot_number", "item_code", "item_description",
        "closing_stock_units", "fefo_expiry_date",
        "stock_cover_days", "reorder_point_rop_units",
        "inventory_health_status"
    }

    missing_fefo = sorted(fefo_required - view_cols)

    checks.append({
        "object": "vw_fefo_expiry_risk",
        "status": "ok" if not missing_fefo else "missing_or_incompatible",
        "missing_columns": missing_fefo
    })

    return {
        "status": "ok" if all(c["status"] == "ok" for c in checks) else "degraded",
        "objects_count": len(objects),
        "objects": objects,
        "checks": checks
    }


def overview(start_date=None, end_date=None):
    validate_dates(start_date, end_date)

    result = {}

    for key, (table, dt) in DATE_COLUMNS.items():
        where, params = date_where(dt, start_date, end_date)

        if key == "sales":
            sql = f"""
                SELECT
                    COUNT(*) AS records,
                    SUM(actual_orders_demanded_pcs) AS demanded_units,
                    SUM(gross_wholesale_revenue_egp) AS gross_revenue_egp,
                    SUM(net_gross_profit_egp) AS gross_profit_egp,

                    CASE
                        WHEN SUM(gross_wholesale_revenue_egp) > 0
                        THEN SUM(net_gross_profit_egp) * 1.0 /
                             SUM(gross_wholesale_revenue_egp)
                    END AS gross_profit_margin,

                    CASE
                        WHEN SUM(actual_orders_demanded_pcs) > 0
                        THEN SUM(
                            ai_forecast_accuracy_rate *
                            actual_orders_demanded_pcs
                        ) * 1.0 / SUM(actual_orders_demanded_pcs)
                    END AS forecast_accuracy_weighted,

                    SUM(demand_forecast_variance_pcs)
                    AS net_forecast_variance

                FROM {table}{where}
            """

        elif key == "production":
            sql = f"""
                SELECT
                    COUNT(*) AS shifts,
                    SUM(good_units_produced) AS good_units,
                    SUM(total_scrap_units) AS scrap_units,

                    CASE
                        WHEN SUM(good_units_produced + total_scrap_units) > 0
                        THEN SUM(total_scrap_units) * 1.0 /
                             SUM(good_units_produced + total_scrap_units)
                    END AS scrap_rate_weighted,

                    AVG(oee) AS mean_shift_oee,
                    AVG(availability) AS mean_availability,
                    AVG(performance) AS mean_performance,
                    AVG(quality) AS mean_quality,
                    AVG(target_oee) AS source_target_oee,
                    SUM(unplanned_dt_min) AS unplanned_downtime_min

                FROM {table}{where}
            """

        elif key == "fleet":
            sql = f"""
                SELECT
                    COUNT(*) AS dispatches,

                    SUM(
                        CASE
                            WHEN on_time_delivery_compliance =
                                 'Compliant On-Time'
                            THEN 1 ELSE 0
                        END
                    ) AS on_time_dispatches,

                    SUM(
                        CASE
                            WHEN on_time_delivery_compliance =
                                 'Congestion Delayed'
                            THEN 1 ELSE 0
                        END
                    ) AS delayed_dispatches,

                    CASE
                        WHEN COUNT(*) > 0
                        THEN SUM(
                            CASE
                                WHEN on_time_delivery_compliance =
                                     'Compliant On-Time'
                                THEN 1.0 ELSE 0
                            END
                        ) / COUNT(*)
                    END AS on_time_rate,

                    AVG(payload_capacity_utilization_pct)
                    AS avg_payload_utilization_raw,

                    SUM(cuopt_dynamic_savings_egp)
                    AS route_savings_egp

                FROM {table}{where}
            """

        else:
            sql = f"""
                SELECT
                    COUNT(*) AS purchase_records,
                    AVG(actual_delivered_lead_time_days)
                    AS avg_actual_lead_time_days,

                    AVG(contracted_lead_time_days)
                    AS avg_contracted_lead_time_days,

                    AVG(lead_time_variance_days)
                    AS avg_lead_time_variance_days,

                    AVG(supplier_quality_yield_rate)
                    AS avg_supplier_quality_yield,

                    SUM(procurement_savings_egp)
                    AS procurement_savings_egp

                FROM {table}{where}
            """

        result[key] = query_records(sql, params)[0]

    result["period"] = {
        "start_date": start_date,
        "end_date": end_date
    }

    result["definitions"] = {
        "oee": "Arithmetic mean of shift-level OEE (source values stored as 0–1).",
        "scrap_rate": "SUM(scrap) / SUM(good units + scrap units), pending business approval.",
        "on_time_delivery": "Compliant On-Time dispatches / all dispatches.",
        "forecast_accuracy": "Demand-weighted historical dataset accuracy, not the separate forecasting model."
    }

    return result


def monthly(table_key, start_date=None, end_date=None):
    table, dt = DATE_COLUMNS[table_key]
    where, params = date_where(dt, start_date, end_date)

    if table_key == "sales":
        sql = f"""
            SELECT
                substr(order_date, 1, 7) AS month_period,
                SUM(actual_orders_demanded_pcs) AS demanded_units,
                SUM(gross_wholesale_revenue_egp) AS revenue_egp,
                SUM(net_gross_profit_egp) AS gross_profit_egp,

                CASE
                    WHEN SUM(gross_wholesale_revenue_egp) > 0
                    THEN SUM(net_gross_profit_egp) * 1.0 /
                         SUM(gross_wholesale_revenue_egp)
                END AS gross_margin

            FROM {table}{where}
            GROUP BY substr(order_date, 1, 7)
            ORDER BY month_period
        """

    elif table_key == "production":
        sql = f"""
            SELECT
                substr(production_date, 1, 7) AS month_period,
                SUM(good_units_produced) AS good_units,
                SUM(total_scrap_units) AS scrap_units,
                AVG(oee) AS mean_oee,

                CASE
                    WHEN SUM(good_units_produced + total_scrap_units) > 0
                    THEN SUM(total_scrap_units) * 1.0 /
                         SUM(good_units_produced + total_scrap_units)
                END AS scrap_rate

            FROM {table}{where}
            GROUP BY substr(production_date, 1, 7)
            ORDER BY month_period
        """

    elif table_key == "fleet":
        sql = f"""
            SELECT
                substr(dispatch_date, 1, 7) AS month_period,
                COUNT(*) AS dispatches,

                SUM(
                    CASE
                        WHEN on_time_delivery_compliance =
                             'Compliant On-Time'
                        THEN 1 ELSE 0
                    END
                ) * 1.0 / COUNT(*) AS on_time_rate,

                SUM(cuopt_dynamic_savings_egp) AS savings_egp

            FROM {table}{where}
            GROUP BY substr(dispatch_date, 1, 7)
            ORDER BY month_period
        """

    else:
        sql = f"""
            SELECT
                substr(rfq_date, 1, 7) AS month_period,
                COUNT(*) AS purchase_records,
                AVG(actual_delivered_lead_time_days) AS avg_actual_lead_time,
                AVG(supplier_quality_yield_rate) AS avg_quality_yield,
                SUM(procurement_savings_egp) AS savings_egp

            FROM {table}{where}
            GROUP BY substr(rfq_date, 1, 7)
            ORDER BY month_period
        """

    return query_records(sql, params)


def fefo_inventory():
    return query_records("""
        SELECT
            batch_lot_number,
            item_code,
            item_description,
            brand,
            closing_stock_units,
            fefo_expiry_date,
            stock_cover_days,
            reorder_point_rop_units,
            inventory_health_status,

            (closing_stock_units - reorder_point_rop_units)
            AS reorder_gap_units

        FROM vw_fefo_expiry_risk

        ORDER BY
            CASE
                WHEN inventory_health_status LIKE 'CRITICAL%' THEN 0
                WHEN inventory_health_status LIKE '%WARNING%' THEN 1
                ELSE 2
            END,
            fefo_expiry_date ASC
    """)


def supplier_performance(start_date=None, end_date=None):
    where, params = date_where("rfq_date", start_date, end_date)

    return query_records(f"""
        SELECT
            supplier_id,
            supplier_name_ar,
            COUNT(*) AS rfq_count,

            AVG(contracted_lead_time_days)
            AS avg_contracted_lead_time,

            AVG(actual_delivered_lead_time_days)
            AS avg_actual_lead_time,

            AVG(lead_time_variance_days)
            AS avg_lead_time_variance,

            AVG(supplier_quality_yield_rate)
            AS avg_quality_yield,

            SUM(procurement_savings_egp)
            AS procurement_savings_egp,

            SUM(triggered_factory_stockout_mg11)
            AS stockout_events

        FROM fact_procurement_rfq{where}

        GROUP BY supplier_id, supplier_name_ar
        ORDER BY avg_actual_lead_time ASC
    """, params)


def machine_performance(start_date=None, end_date=None):
    where, params = date_where("production_date", start_date, end_date)

    return query_records(f"""
        SELECT
            machine_id,
            COUNT(*) AS shifts,
            SUM(good_units_produced) AS good_units,
            SUM(total_scrap_units) AS scrap_units,
            AVG(oee) AS mean_oee,
            AVG(availability) AS mean_availability,
            AVG(performance) AS mean_performance,
            AVG(quality) AS mean_quality,
            SUM(unplanned_dt_min) AS unplanned_downtime_min

        FROM fact_production_shifts{where}
        GROUP BY machine_id
        ORDER BY mean_oee DESC
    """, params)


def fleet_summary(start_date=None, end_date=None):
    where, params = date_where("dispatch_date", start_date, end_date)

    return query_records(f"""
        SELECT
            on_time_delivery_compliance,
            COUNT(*) AS dispatch_count,
            AVG(payload_capacity_utilization_pct)
            AS avg_payload_utilization_raw,
            SUM(cuopt_dynamic_savings_egp) AS route_savings_egp

        FROM fact_lastmile_fleet_dispatch{where}

        GROUP BY on_time_delivery_compliance
        ORDER BY dispatch_count DESC
    """, params)


def decision_insights(start_date=None, end_date=None):
    o = overview(start_date, end_date)
    insights = []

    p = o["production"]
    f = o["fleet"]

    if (
        p["mean_shift_oee"] is not None
        and p["source_target_oee"] is not None
    ):
        gap = p["mean_shift_oee"] - p["source_target_oee"]

        if gap < 0:
            insights.append({
                "severity": "High",
                "area": "Production",
                "title": "OEE below recorded target",
                "evidence": (
                    f"Mean shift OEE is {p['mean_shift_oee']:.1%} "
                    f"versus recorded target {p['source_target_oee']:.1%}."
                ),
                "recommended_action": (
                    "Review the lowest-OEE machines and Pareto of "
                    "unplanned downtime."
                ),
                "basis": "Source target_oee field; mean of shift-level OEE."
            })

        else:
            insights.append({
                "severity": "Info",
                "area": "Production",
                "title": "OEE meets or exceeds recorded target",
                "evidence": (
                    f"Mean shift OEE is {p['mean_shift_oee']:.1%}; "
                    f"recorded target is {p['source_target_oee']:.1%}."
                ),
                "recommended_action": (
                    "Maintain operating practices and investigate shifts "
                    "remaining below target."
                ),
                "basis": "Source target_oee field; mean of shift-level OEE."
            })

    if f["dispatches"]:
        rate = f["on_time_rate"] or 0

        insights.append({
            "severity": "High" if f["delayed_dispatches"] else "Info",
            "area": "Logistics",
            "title": "Delayed delivery dispatches detected",
            "evidence": (
                f"{f['delayed_dispatches']} of {f['dispatches']} dispatches "
                f"are marked Congestion Delayed; on-time rate is {rate:.1%}."
            ),
            "recommended_action": (
                "Segment delayed dispatches by destination, truck, shift "
                "and congestion duration."
            ),
            "basis": "Observed source status categories."
        })

    if p["scrap_rate_weighted"] is not None:
        insights.append({
            "severity": "Info",
            "area": "Quality",
            "title": "Scrap rate calculated from production counts",
            "evidence": (
                f"Weighted scrap rate is {p['scrap_rate_weighted']:.2%} "
                "using scrap / (good + scrap)."
            ),
            "recommended_action": (
                "Compare with stored scrap_rate_pct and confirm the "
                "denominator with Production."
            ),
            "basis": "Candidate formula requiring business-owner approval."
        })

    insights.append({
        "severity": "Warning",
        "area": "Data Quality",
        "title": "Validate fleet payload utilization outliers",
        "evidence": (
            "The supplied source includes payload utilization values above 100%."
        ),
        "recommended_action": (
            "Check shipment weight, vehicle capacity and unit consistency."
        ),
        "basis": "Source data contains payload utilization values above 1."
    })

    return insights


# ==========================================================
# SUPPLIER INTELLIGENCE
# ==========================================================

def supplier_material_options():
    """Return categories and SKUs actually observed in procurement RFQs."""

    return query_records("""
        SELECT
            material_category,
            material_sku_code,
            COUNT(*) AS rfq_count,
            COUNT(DISTINCT supplier_id) AS exact_sku_supplier_count

        FROM fact_procurement_rfq

        GROUP BY material_category, material_sku_code

        ORDER BY material_category, material_sku_code
    """)


def supplier_recommendations(
    material_category: str,
    material_sku_code: str,
    start_date=None,
    end_date=None
):
    """
    Rank historical suppliers within a material category.

    Exact SKU suppliers are identified from actual RFQ records.
    Other suppliers are category-level discovery candidates only.
    """

    if not material_category or not material_sku_code:
        raise ValueError(
            "Both material_category and material_sku_code are required."
        )

    where, params = date_where("rfq_date", start_date, end_date)

    rows = query_records(f"""
        SELECT
            supplier_id,
            supplier_name_ar,
            material_category,
            material_sku_code,

            COUNT(*) AS rfq_count,

            AVG(supplier_quality_yield_rate)
            AS avg_quality_yield,

            AVG(actual_delivered_lead_time_days)
            AS avg_actual_lead_time,

            AVG(contracted_lead_time_days)
            AS avg_contracted_lead_time,

            AVG(lead_time_variance_days)
            AS avg_lead_time_variance,

            AVG(procurement_savings_pct)
            AS avg_savings_pct,

            SUM(procurement_savings_egp)
            AS total_savings_egp,

            SUM(triggered_factory_stockout_mg11)
            AS stockout_events,

            AVG(ai_negotiated_price_egp)
            AS avg_negotiated_price_egp,

            MAX(payment_terms) AS payment_terms,
            MAX(supplier_audit_status) AS supplier_audit_status,
            MAX(supplier_plant_location) AS supplier_plant_location

        FROM fact_procurement_rfq

        {where + ' AND ' if where else ' WHERE '}
        material_category = ?

        GROUP BY
            supplier_id,
            supplier_name_ar,
            material_category,
            material_sku_code
    """, params + (material_category,))

    if not rows:
        return {
            "material_category": material_category,
            "material_sku_code": material_sku_code,
            "exact_sku_suppliers": [],
            "category_candidates": [],
            "alternative_candidates": [],
            "message": (
                "No procurement records found for this category "
                "in the selected period."
            )
        }

    exact = [
        r for r in rows
        if r["material_sku_code"] == material_sku_code
    ]

    by_supplier = {}

    for r in rows:
        sid = r["supplier_id"]

        if sid not in by_supplier:
            by_supplier[sid] = {
                **r,
                "_rfqs": 0,
                "_quality_sum": 0.0,
                "_quality_n": 0,
                "_lead_sum": 0.0,
                "_lead_n": 0,
                "_savings_sum": 0.0,
                "_savings_n": 0,
                "_stockouts": 0,
                "_savings_egp": 0.0
            }

        a = by_supplier[sid]
        count = int(r["rfq_count"] or 0)

        a["_rfqs"] += count

        if r["avg_quality_yield"] is not None:
            a["_quality_sum"] += (
                float(r["avg_quality_yield"]) * count
            )
            a["_quality_n"] += count

        if r["avg_actual_lead_time"] is not None:
            a["_lead_sum"] += (
                float(r["avg_actual_lead_time"]) * count
            )
            a["_lead_n"] += count

        if r["avg_savings_pct"] is not None:
            a["_savings_sum"] += (
                float(r["avg_savings_pct"]) * count
            )
            a["_savings_n"] += count

        a["_stockouts"] += int(r["stockout_events"] or 0)
        a["_savings_egp"] += float(r["total_savings_egp"] or 0)

    candidates = []

    for a in by_supplier.values():
        n = a["_rfqs"]

        candidates.append({
            "supplier_id": a["supplier_id"],
            "supplier_name_ar": a["supplier_name_ar"],
            "rfq_count": n,

            "avg_quality_yield": (
                a["_quality_sum"] / a["_quality_n"]
                if a["_quality_n"] else None
            ),

            "avg_actual_lead_time": (
                a["_lead_sum"] / a["_lead_n"]
                if a["_lead_n"] else None
            ),

            "avg_savings_pct": (
                a["_savings_sum"] / a["_savings_n"]
                if a["_savings_n"] else None
            ),

            "total_savings_egp": a["_savings_egp"],
            "stockout_events": a["_stockouts"],

            "stockout_rate": (
                a["_stockouts"] / n if n else None
            ),

            "payment_terms": a["payment_terms"],
            "supplier_audit_status": a["supplier_audit_status"],
            "supplier_plant_location": a["supplier_plant_location"],

            "has_exact_sku_history": any(
                x["supplier_id"] == a["supplier_id"]
                for x in exact
            )
        })

    def minmax(values, higher=True):
        valid = [
            float(v) for v in values
            if v is not None
        ]

        if not valid:
            return lambda v: 0.5

        lo, hi = min(valid), max(valid)

        def score(v):
            if v is None:
                return 0.5

            if hi == lo:
                return 1.0

            z = (float(v) - lo) / (hi - lo)

            return z if higher else 1.0 - z

        return score

    qscore = minmax(
        [x["avg_quality_yield"] for x in candidates],
        True
    )

    lscore = minmax(
        [x["avg_actual_lead_time"] for x in candidates],
        False
    )

    sscore = minmax(
        [x["avg_savings_pct"] for x in candidates],
        True
    )

    rscore = minmax(
        [x["stockout_rate"] for x in candidates],
        False
    )

    for x in candidates:
        score = (
            0.40 * qscore(x["avg_quality_yield"])
            + 0.30 * lscore(x["avg_actual_lead_time"])
            + 0.20 * sscore(x["avg_savings_pct"])
            + 0.10 * rscore(x["stockout_rate"])
        )

        x["supplier_score"] = round(score * 100, 1)

        if score >= 0.75:
            x["recommendation_tier"] = "Strong historical profile"
        elif score >= 0.45:
            x["recommendation_tier"] = "Review profile"
        else:
            x["recommendation_tier"] = "Higher risk profile"

        x["score_basis"] = (
            "Category-level historical performance; "
            "not proof of SKU compatibility."
        )

    candidates.sort(
        key=lambda x: (
            x["supplier_score"],
            x["rfq_count"]
        ),
        reverse=True
    )

    exact_ids = {
        r["supplier_id"] for r in exact
    }

    for r in exact:
        profile = next(
            (
                x for x in candidates
                if x["supplier_id"] == r["supplier_id"]
            ),
            {}
        )

        r["category_supplier_score"] = profile.get(
            "supplier_score"
        )

        r["category_profile"] = profile

    return {
        "material_category": material_category,
        "material_sku_code": material_sku_code,

        "exact_sku_suppliers": exact,
        "category_candidates": candidates,

        "alternative_candidates": [
            x for x in candidates
            if x["supplier_id"] not in exact_ids
        ],

        "scoring_weights": {
            "quality": 0.40,
            "lead_time": 0.30,
            "savings": 0.20,
            "stockout_risk": 0.10
        },

        "methodology_note": (
            "Price is excluded from cross-SKU scoring because "
            "material prices are not comparable across different SKUs. "
            "Category alternatives are discovery candidates only and "
            "require technical qualification and commercial approval."
        )
    }
