"""Smoke tests against the bundled SQLite database; run with pytest."""
from backend.database import query_records, columns_for
from backend import analytics

def test_fefo_view_columns_match_query():
    required={"batch_lot_number","item_code","item_description","closing_stock_units",
              "fefo_expiry_date","stock_cover_days","reorder_point_rop_units","inventory_health_status"}
    assert required.issubset(columns_for("vw_fefo_expiry_risk"))
    assert len(analytics.fefo_inventory()) > 0

def test_on_time_categories_are_known():
    rows=query_records("SELECT DISTINCT on_time_delivery_compliance status FROM fact_lastmile_fleet_dispatch")
    assert {r["status"] for r in rows} == {"Compliant On-Time","Congestion Delayed"}

def test_percentages_are_ratio_scaled():
    row=query_records("SELECT MIN(oee) mn,MAX(oee) mx,AVG(oee) av FROM fact_production_shifts")[0]
    assert 0 <= row["mn"] <= 1 and 0 <= row["mx"] <= 1
    assert 0.7 < row["av"] < 0.95

def test_date_filtered_overview():
    result=analytics.overview("2026-01-01","2026-01-31")
    assert result["sales"]["records"] > 0
    assert result["production"]["shifts"] > 0
    assert result["fleet"]["dispatches"] > 0

def test_scrap_rate_is_bounded():
    result=analytics.overview()
    assert 0 <= result["production"]["scrap_rate_weighted"] <= 1
