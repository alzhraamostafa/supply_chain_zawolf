"""Usage: python scripts/run_backtest.py path/to/db   (or set FORECAST_DB)"""
import csv, datetime, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from forecasting import backtest
from forecasting.config import WEEKLY_LEVELS
from forecasting.data import load_demand

db = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FORECAST_DB")
if not db:
    sys.exit("Pass the .db path as an argument or set FORECAST_DB")
df = load_demand(db)
rows = []
for lv in WEEKLY_LEVELS:
    rows += backtest.weekly_level(df, lv)
rows += backtest.weekly_sku_allocated(df)
rows += backtest.monthly_sku(df)
res = pd.DataFrame(rows)
print(res.to_string(index=False))

out = pathlib.Path(__file__).resolve().parents[1] / "outputs"
out.mkdir(exist_ok=True)
res.to_csv(out / "backtest_results.csv", index=False)
# append-only experiment log
stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
log = out / "experiments.csv"
new = not log.exists()
with open(log, "a", newline="") as f:
    wr = csv.writer(f)
    if new:
        wr.writerow(["run_at_utc", "db", "level", "model", "WAPE", "bias"])
    for r in rows:
        wr.writerow([stamp, pathlib.Path(db).name, r["level"], r["model"], r["WAPE"], r["bias"]])