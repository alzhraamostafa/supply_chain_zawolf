
import numpy as np
from forecasting import backtest


def test_rolling_ml_forecasts_uses_only_previous_errors(monkeypatch):
    w = np.zeros((2, 16))
    ev = np.zeros((16, 1))

    # Prepare actual demand for historical weeks 9 to 14
    for t in range(9, 14):
        w[:, t] = [t + 1, 2 * t + 2]

    w[:, 14] = [101, 202]

    calls = []

    def fake_ml_forecast(w, ev, t, kind):
        calls.append(t)

        if t < 14:
            return np.array([float(t), float(2 * t)])

        return np.array([100.0, 200.0])

    monkeypatch.setattr(backtest, "ml_forecast", fake_ml_forecast)

    point, lower, upper = backtest._rolling_ml_forecasts(
        w, ev, [14, 15], "ridge"
    )

    # Historical errors must be generated before each forecast
    assert calls == [9, 10, 11, 12, 13, 14, 15]

    assert np.allclose(point[0], [100, 200])
    assert np.allclose(lower[0], [101, 202])
    assert np.allclose(upper[0], [101, 202])



import pandas as pd


def test_weekly_level_includes_ml_intervals(monkeypatch):
    w_df = pd.DataFrame(
        np.tile(np.arange(1, 17, dtype=float), (2, 1))
    )
    ev_df = pd.DataFrame(np.zeros((16, 1)))

    monkeypatch.setattr(
        backtest,
        "weekly_panel",
        lambda df, level: (w_df, ev_df)
    )

    def fake_rolling_forecasts(w, ev, tests, kind):
        tests = list(tests)

        forecasts = [
            np.array([10.0, 20.0]) for _ in tests
        ]
        lower = [
            np.array([0.0, 0.0]) for _ in tests
        ]
        upper = [
            np.array([30.0, 30.0]) for _ in tests
        ]

        return forecasts, lower, upper

    monkeypatch.setattr(
        backtest,
        "_rolling_ml_forecasts",
        fake_rolling_forecasts
    )

    results = backtest.weekly_level(None, "family")

    by_model = {row["model"]: row for row in results}

    assert len(results) == 7

    assert "ridge" in by_model
    assert "gbm" in by_model
    assert "ridge_interval" in by_model
    assert "gbm_interval" in by_model

    assert "interval_coverage" in by_model["ridge_interval"]
    assert "mean_interval_width" in by_model["gbm_interval"]



def test_weekly_sku_allocated_includes_intervals(monkeypatch):
    sku_w = pd.DataFrame(
        np.ones((3, 16)),
        index=["SKU_A", "SKU_B", "SKU_C"]
    )

    fam_w = pd.DataFrame(
        np.ones((1, 16)) * 3,
        index=["Family_A"]
    )

    ev_df = pd.DataFrame(np.zeros((16, 1)))

    monkeypatch.setattr(
        backtest,
        "weekly_panel",
        lambda df, level: (
            (sku_w, pd.DataFrame())
            if level == "item_code"
            else (fam_w, ev_df)
        )
    )

    monkeypatch.setattr(
        backtest,
        "monthly_panel",
        lambda df, level: None
    )

    monkeypatch.setattr(
        backtest,
        "_rolling_ml_forecasts",
        lambda w, ev, tests, kind: (
            [np.array([30.0]) for _ in tests],
            [np.array([20.0]) for _ in tests],
            [np.array([40.0]) for _ in tests]
        )
    )

    df = pd.DataFrame({
        "item_code": ["SKU_A", "SKU_B", "SKU_C"],
        "family": ["Family_A", "Family_A", "Family_A"]
    })

    results = backtest.weekly_sku_allocated(df)

    by_model = {row["model"]: row for row in results}

    assert "family-ridge->alloc" in by_model
    assert "family-gbm->alloc" in by_model

    assert "family-ridge->alloc_interval" in by_model
    assert "family-gbm->alloc_interval" in by_model

    assert "interval_coverage" in by_model[
        "family-ridge->alloc_interval"
    ]

    assert "mean_interval_width" in by_model[
        "family-gbm->alloc_interval"
    ]



def test_sku_allocation_preserves_family_total():
    fam_index = {"Family_A": 0}
    sku_index = ["SKU_A", "SKU_B", "SKU_C"]

    sku_family = pd.Series({
        "SKU_A": "Family_A",
        "SKU_B": "Family_A",
        "SKU_C": "Family_A"
    })

    sku_hist = np.array([40.0, 30.0, 30.0])

    family_forecast = np.array([1000.0])

    result = backtest.allocate_by_share(
        family_forecast,
        fam_index,
        sku_index,
        sku_family,
        sku_hist
    )

    assert np.allclose(result, [400, 300, 300])
    assert np.isclose(result.sum(), family_forecast.sum())


def test_monthly_sku_includes_intervals(monkeypatch):
    m = pd.DataFrame(
        [
            [100, 120, 110, 130, 140, 150],
            [50, 60, 55, 70, 65, 80],
            [200, 180, 190, 210, 220, 230]
        ]
    )

    monkeypatch.setattr(
        backtest,
        "monthly_panel",
        lambda df, level: m
    )

    results = backtest.monthly_sku(None)

    by_model = {row["model"]: row for row in results}

    assert len(results) == 4

    assert "naive" in by_model
    assert "expanding_mean" in by_model

    assert "naive_interval" in by_model
    assert "expanding_mean_interval" in by_model

    assert "interval_coverage" in by_model["naive_interval"]
    assert "mean_interval_width" in by_model["expanding_mean_interval"]



def test_monthly_intervals_use_only_previous_errors(monkeypatch):
    m = pd.DataFrame([
        [100, 120, 110, 130, 140, 150],
        [50, 60, 55, 70, 65, 80],
        [200, 180, 190, 210, 220, 230]
    ])

    monkeypatch.setattr(
        backtest,
        "monthly_panel",
        lambda df, level: m
    )

    original_interval = backtest.prediction_interval
    captured_errors = []

    def tracking_interval(forecast, errors):
        captured_errors.append(np.array(errors, copy=True))
        return original_interval(forecast, errors)

    monkeypatch.setattr(
        backtest,
        "prediction_interval",
        tracking_interval
    )

    backtest.monthly_sku(None)

    # First call belongs to Naive, forecasting April.
    # It must use February and March errors only.
    expected_naive_errors = np.array([
        [20, 10, -20],
        [-10, -5, 10]
    ])

    assert np.allclose(
        captured_errors[0],
        expected_naive_errors
    )

    # April's actual demand must not be used
    # when calculating April's prediction interval.
    assert captured_errors[0].shape == (2, 3)



def test_sku_allocation_when_all_historical_sales_are_zero():
    fam_index = {"Family_A": 0}

    sku_index = ["SKU_A", "SKU_B", "SKU_C"]

    sku_family = pd.Series({
        "SKU_A": "Family_A",
        "SKU_B": "Family_A",
        "SKU_C": "Family_A"
    })

    sku_hist = np.array([0.0, 0.0, 0.0])

    family_forecast = np.array([1000.0])

    result = backtest.allocate_by_share(
        family_forecast,
        fam_index,
        sku_index,
        sku_family,
        sku_hist
    )

    assert np.isclose(result.sum(), 1000.0)
    assert np.allclose(result, [1000/3, 1000/3, 1000/3])


def test_sku_allocation_preserves_family_interval_totals():
    fam_index = {"Family_A": 0}

    sku_index = ["SKU_A", "SKU_B", "SKU_C"]

    sku_family = pd.Series({
        "SKU_A": "Family_A",
        "SKU_B": "Family_A",
        "SKU_C": "Family_A"
    })

    sku_hist = np.array([40.0, 30.0, 30.0])

    family_lower = np.array([800.0])
    family_upper = np.array([1200.0])

    sku_lower = backtest.allocate_by_share(
        family_lower, fam_index, sku_index, sku_family, sku_hist
    )

    sku_upper = backtest.allocate_by_share(
        family_upper, fam_index, sku_index, sku_family, sku_hist
    )

    assert np.isclose(sku_lower.sum(), 800.0)
    assert np.isclose(sku_upper.sum(), 1200.0)
    assert np.all(sku_lower <= sku_upper)
