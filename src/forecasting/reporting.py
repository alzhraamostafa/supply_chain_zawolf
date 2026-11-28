
import csv
import datetime
import pathlib
import pandas as pd


def save_results(rows, db, output_dir):
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    res = pd.DataFrame(rows)

    expected_columns = [
        "level",
        "model",
        "WAPE",
        "bias",
        "interval_coverage",
        "mean_interval_width"
    ]

    res = res.reindex(columns=expected_columns)
    res.to_csv(output_dir / "backtest_results.csv", index=False)

    # append-only experiment log
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    log = output_dir / "experiments.csv"
    new = not log.exists() or log.stat().st_size == 0

    with open(log, "a", newline="") as f:
        wr = csv.writer(f)

        if new:
            wr.writerow([
                "run_at_utc",
                "db",
                "level",
                "model",
                "WAPE",
                "bias",
                "interval_coverage",
                "mean_interval_width"
            ])

        for r in rows:
            wr.writerow([
                stamp,
                pathlib.Path(db).name,
                r["level"],
                r["model"],
                r["WAPE"],
                r["bias"],
                r.get("interval_coverage", ""),
                r.get("mean_interval_width", "")
            ])
