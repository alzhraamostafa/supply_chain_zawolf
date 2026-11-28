
import csv
import pandas as pd

from forecasting.reporting import save_results


def test_save_results_creates_files(tmp_path):
    rows = [
        {
            "level": "family",
            "model": "ridge",
            "WAPE": 0.16,
            "bias": 0.02,
            "interval_coverage": 0.85,
            "mean_interval_width": 20.0
        }
    ]

    output_dir = tmp_path / "outputs"

    save_results(rows, "data/test.db", output_dir)

    results_file = output_dir / "backtest_results.csv"
    log_file = output_dir / "experiments.csv"

    assert results_file.exists()
    assert log_file.exists()

    with open(log_file, newline="") as f:
        saved_rows = list(csv.reader(f))

    assert len(saved_rows) == 2
    assert saved_rows[0][0] == "run_at_utc"
    assert saved_rows[1][1] == "test.db"
    assert saved_rows[1][2] == "family"


def test_save_results_appends_to_log(tmp_path):
    rows = [
        {
            "level": "family",
            "model": "ridge",
            "WAPE": 0.16,
            "bias": 0.02
        }
    ]

    output_dir = tmp_path / "outputs"

    save_results(rows, "data/test.db", output_dir)
    save_results(rows, "data/test.db", output_dir)

    with open(output_dir / "experiments.csv", newline="") as f:
        saved_rows = list(csv.reader(f))

    assert len(saved_rows) == 3


def test_save_results_writes_header_to_empty_log(tmp_path):
    rows = [
        {
            "level": "family",
            "model": "ridge",
            "WAPE": 0.16,
            "bias": 0.02
        }
    ]

    output_dir = tmp_path / "outputs"
    output_dir.mkdir()

    log_file = output_dir / "experiments.csv"
    log_file.touch()

    save_results(rows, "data/test.db", output_dir)

    with open(log_file, newline="") as f:
        saved_rows = list(csv.reader(f))

    assert len(saved_rows) == 2
    assert saved_rows[0][0] == "run_at_utc"


def test_save_results_overwrites_backtest_results(tmp_path):
    output_dir = tmp_path / "outputs"

    first_rows = [
        {
            "level": "family",
            "model": "ridge",
            "WAPE": 0.16,
            "bias": 0.02
        }
    ]

    second_rows = [
        {
            "level": "brand",
            "model": "gbm",
            "WAPE": 0.20,
            "bias": -0.03
        }
    ]

    save_results(first_rows, "data/test.db", output_dir)
    save_results(second_rows, "data/test.db", output_dir)

    results = pd.read_csv(output_dir / "backtest_results.csv")

    assert len(results) == 1
    assert results.iloc[0]["level"] == "brand"
    assert results.iloc[0]["model"] == "gbm"
    assert results.iloc[0]["WAPE"] == 0.20


def test_save_results_handles_missing_interval_values(tmp_path):
    rows = [
        {
            "level": "family",
            "model": "ridge",
            "WAPE": 0.16,
            "bias": 0.02
        }
    ]

    output_dir = tmp_path / "outputs"

    save_results(rows, "data/test.db", output_dir)

    results = pd.read_csv(output_dir / "backtest_results.csv")

    assert pd.isna(results.loc[0, "interval_coverage"])
    assert pd.isna(results.loc[0, "mean_interval_width"])
