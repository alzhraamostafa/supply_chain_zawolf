# Smart Supply Chain — Professional Analytics & Decision Support

This package continues the supplied Streamlit + FastAPI project, keeps its SQLite architecture, and includes the provided database at `data/supply_chain.db`.

## What changed

- Rebuilt the FastAPI analytics layer with reusable date filtering and clearer endpoint contracts.
- Fixed FEFO query to match the actual `vw_fefo_expiry_risk` view columns in the supplied database.
- Corrected on-time delivery calculation using observed categories: `Compliant On-Time` and `Congestion Delayed`.
- Made percentage formatting explicit and ratio-aware (0–1 source ratios).
- Added ratio-of-sums gross profit margin and candidate weighted scrap rate.
- Added period filters to sales, production, procurement and logistics analytics.
- Added machine and supplier scorecards, monthly trends, and explainable rule-based Decision Intelligence.
- Added a Data Quality page and API health/schema checks.
- Kept inventory explicitly labelled as a historical FEFO snapshot, not live inventory.

## Verified facts from the bundled database

- Date coverage: 2026-01-01 to 2026-06-30 for sales, production and fleet; procurement starts 2026-01-06.
- OEE, availability, performance, quality, forecast accuracy, gross margin and supplier yield are stored as ratios (0–1).
- `vw_fefo_expiry_risk` columns are: `batch_lot_number`, `item_code`, `item_description`, `brand`, `closing_stock_units`, `fefo_expiry_date`, `stock_cover_days`, `reorder_point_rop_units`, `inventory_health_status`.
- On-time categories observed: `Compliant On-Time`, `Congestion Delayed`.
- Fleet `payload_capacity_utilization_pct` has values above 1.0 (maximum observed 6.4138), so the metric is flagged and not presented as a trusted headline value.
- The historical forecast accuracy field is not evidence that the separate/new forecasting model has been integrated.

## Run on Windows PowerShell

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

In a second terminal:

```powershell
.\venv\Scripts\Activate.ps1
python -m streamlit run dashboard/app.py
```

## Date filters

The dashboard provides a global From/To filter. API endpoints accept ISO dates, for example:

`/api/overview?start_date=2026-01-01&end_date=2026-03-31`

## KPI definitions and caveats

- **OEE:** arithmetic mean of shift-level `oee`; source values are ratios. This is not a plant-volume-weighted OEE. The source field `target_oee` is used as the available target.
- **Scrap rate:** `SUM(total_scrap_units) / SUM(good_units_produced + total_scrap_units)`. This is a candidate aggregation; obtain Production sign-off on denominator and rework treatment.
- **On-time delivery:** count of `Compliant On-Time` / all dispatches. This follows the categories found in the database.
- **Gross profit margin:** `SUM(net_gross_profit_egp) / SUM(gross_wholesale_revenue_egp)`, not the simple average of row margins.
- **Forecast accuracy:** demand-weighted average of the historical `ai_forecast_accuracy_rate`. Do not call it the new forecasting model's performance.
- **FEFO:** the supplied view is a historical snapshot. The date filter does not change the snapshot.
- **Fleet payload utilization:** do not use as a headline KPI until values above 100% are investigated.

Targets other than OEE are intentionally not invented. Add approved targets in `config/kpi_targets.json` after agreement with business stakeholders.

## Decision Intelligence

The current module is explainable, rule-based decision support. It highlights OEE vs source target, delayed dispatches, scrap-rate definition checks, and fleet utilization data-quality issues. Recommendations are diagnostic prompts, not proof of root cause and not autonomous decisions.

## Tests

From the project root:

```powershell
pytest -q
```
