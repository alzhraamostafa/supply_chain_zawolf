"""Usage: python scripts/run_backtest.py path/to/db   (or set FORECAST_DB)"""
# import csv, datetime, os, pathlib, sys
import os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from forecasting import backtest
from forecasting.config import WEEKLY_LEVELS
from forecasting.data import load_demand
from forecasting.reporting import save_results



db = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FORECAST_DB")

if not db:
    sys.exit("Pass the .db path as an argument or set FORECAST_DB")

if not pathlib.Path(db).is_file():
    sys.exit(f"Database file not found: {db}")

df = load_demand(db)

rows = []
for lv in WEEKLY_LEVELS:
    rows += backtest.weekly_level(df, lv)
rows += backtest.weekly_sku_allocated(df)
rows += backtest.monthly_sku(df)
res = pd.DataFrame(rows)
print(res.to_string(index=False))


out = pathlib.Path(__file__).resolve().parents[1] / "outputs"
save_results(rows, db, out)

# Per-SKU model comparison
comparison, best = backtest.weekly_sku_model_comparison(df)

comparison.to_csv(
    out / "sku_model_comparison.csv",
    index=False
)

best.to_csv(
    out / "sku_best_models.csv",
    index=False
)

print("\n=== Best Model per SKU ===")
print(best.to_string(index=False))

print("\nPer-SKU comparison files saved successfully.")



# Per-SKU model selection: validation + final test
(
    validation_comparison,
    selected_models,
    final_sku_results,
    final_overall_comparison
) = backtest.weekly_sku_model_selection(df, validation_weeks=5)

# Save validation and final test results
validation_comparison.to_csv(
    out / "sku_validation_comparison.csv",
    index=False
)

selected_models.to_csv(
    out / "sku_selected_models.csv",
    index=False
)

final_sku_results.to_csv(
    out / "sku_final_test_results.csv",
    index=False
)

final_overall_comparison.to_csv(
    out / "sku_final_overall_comparison.csv",
    index=False
)

print("\n=== Final Test: Overall Model Comparison ===")
print(final_overall_comparison.to_string(index=False))

print("\n=== Final Test: Per-SKU Selected Models ===")
print(final_sku_results.to_string(index=False))

print("\nSKU model selection results saved successfully.")

