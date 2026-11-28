
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from backend import analytics
from backend.database import DB_PATH

app = FastAPI(
    title="Smart Supply Chain Analytics API",
    version="2.1.0",
    description=(
        "Historical supply chain analytics, KPI monitoring, "
        "supplier intelligence and explainable recommendations."
    )
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["GET"],
)


def date_params(start_date, end_date):
    try:
        analytics.validate_dates(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/")
def root():
    return {
        "service": "Smart Supply Chain Analytics API",
        "version": "2.1.0",
        "docs": "/docs"
    }


@app.get("/api/health")
def health():
    if not DB_PATH.exists():
        return {
            "status": "database_missing",
            "database_path": str(DB_PATH)
        }

    try:
        result = analytics.data_health()
        result["database"] = DB_PATH.name
        return result

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Health check failed: {exc}"
        )


@app.get("/api/overview")
def overview(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    date_params(start_date, end_date)

    try:
        return analytics.overview(start_date, end_date)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Overview query failed: {exc}"
        )


@app.get("/api/sales/monthly")
def sales_monthly(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.monthly("sales", start_date, end_date)


@app.get("/api/production/monthly")
def production_monthly(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.monthly("production", start_date, end_date)


@app.get("/api/logistics/monthly")
def logistics_monthly(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.monthly("fleet", start_date, end_date)


@app.get("/api/procurement/monthly")
def procurement_monthly(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.monthly("procurement", start_date, end_date)


@app.get("/api/sales/top-products")
def top_products(
    limit: int = Query(10, ge=1, le=100),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    date_params(start_date, end_date)

    from backend.database import query_records

    where, params = analytics.date_where(
        "order_date", start_date, end_date
    )

    return query_records(
        f"""
        SELECT
            item_code,
            item_description,
            SUM(actual_orders_demanded_pcs) AS demanded_units,
            SUM(gross_wholesale_revenue_egp) AS revenue_egp,
            SUM(net_gross_profit_egp) AS gross_profit_egp

        FROM fact_commercial_demand_m5
        {where}

        GROUP BY item_code, item_description
        ORDER BY revenue_egp DESC
        LIMIT ?
        """,
        params + (limit,)
    )


@app.get("/api/production/machines")
def machines(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.machine_performance(start_date, end_date)


@app.get("/api/inventory/fefo")
def fefo():
    try:
        return analytics.fefo_inventory()

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"FEFO view query failed: {exc}"
        )


@app.get("/api/procurement/suppliers")
def suppliers(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.supplier_performance(start_date, end_date)


@app.get("/api/fleet/summary")
def fleet(start_date=None, end_date=None):
    date_params(start_date, end_date)
    return analytics.fleet_summary(start_date, end_date)


@app.get("/api/decision/insights")
def insights(start_date=None, end_date=None):
    date_params(start_date, end_date)

    try:
        return analytics.decision_insights(start_date, end_date)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Decision analysis failed: {exc}"
        )


@app.get("/api/filters")
def filters():
    from backend.database import query_records

    return {
        "products": query_records(
            """
            SELECT item_code, item_description
            FROM dim_products
            ORDER BY item_code
            """
        ),
        "suppliers": query_records(
            """
            SELECT supplier_id, supplier_name
            FROM dim_suppliers
            ORDER BY supplier_name
            """
        ),
        "machines": query_records(
            """
            SELECT machine_id
            FROM dim_machines
            ORDER BY machine_id
            """
        )
    }


# ==========================================================
# SUPPLIER INTELLIGENCE API
# ==========================================================

@app.get("/api/procurement/material-options")
def material_options():
    try:
        rows = analytics.supplier_material_options()

        categories = sorted({
            r["material_category"]
            for r in rows
            if r["material_category"]
        })

        return {
            "categories": categories,
            "materials": rows,
            "total_materials": len(rows)
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Material options query failed: {exc}"
        )


@app.get("/api/procurement/materials")
def materials_by_category(
    category: str = Query(..., min_length=1)
):
    try:
        rows = analytics.supplier_material_options()

        return [
            {
                "material_sku_code": r["material_sku_code"],
                "rfq_count": r["rfq_count"],
                "exact_sku_supplier_count":
                    r["exact_sku_supplier_count"]
            }
            for r in rows
            if r["material_category"] == category
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Material lookup failed: {exc}"
        )


@app.get("/api/procurement/supplier-recommendations")
def supplier_recommendations(
    material_category: str = Query(..., min_length=1),
    material_sku_code: str = Query(..., min_length=1),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    date_params(start_date, end_date)

    try:
        return analytics.supplier_recommendations(
            material_category=material_category,
            material_sku_code=material_sku_code,
            start_date=start_date,
            end_date=end_date
        )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Supplier recommendation failed: {exc}"
        )


@app.get("/api/procurement/supplier-intelligence/health")
def supplier_intelligence_health():
    try:
        options = analytics.supplier_material_options()

        return {
            "status": "ok",
            "material_options": len(options),
            "categories": len({
                r["material_category"]
                for r in options
                if r["material_category"]
            }),
            "message": (
                "Supplier Intelligence endpoints are available."
            )
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Supplier Intelligence health check failed: {exc}"
        )
