"""Rolling-origin (expanding window), 1-step-ahead backtests. Each fn returns a list of result rows."""
import numpy as np
import pandas as pd
from .baselines import naive, ma, croston, sba, tsb
from .config import FIRST_TEST_WEEK, FIRST_TEST_MONTH, MIN_HIST
from .data import weekly_panel, monthly_panel
from .hierarchy import allocate_by_share
from .metrics import wape, bias
from .models import ml_forecast
from .intervals import prediction_interval


def _row(level, model, A, P):
    return dict(level=level, model=model, WAPE=round(wape(A, np.array(P)), 3), bias=round(bias(A, np.array(P)), 3))


def _interval_row(level, model, actual, lower, upper):
    """Evaluate prediction interval coverage and average width."""
    actual = np.asarray(actual, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)

    valid = (
        np.isfinite(actual)
        & np.isfinite(lower)
        & np.isfinite(upper)
    )

    if not valid.any():
        coverage = np.nan
        mean_width = np.nan
    else:
        coverage = np.mean(
            (actual[valid] >= lower[valid])
            & (actual[valid] <= upper[valid])
        )
        mean_width = np.mean(upper[valid] - lower[valid])

    return {
        "level": level,
        "model": f"{model}_interval",
        "WAPE": np.nan,
        "bias": np.nan,
        "interval_coverage": round(float(coverage), 3),
        "mean_interval_width": round(float(mean_width), 3),
    }


def _rolling_ml_forecasts(w, ev, tests, kind):
    """
    Generate point forecasts and P10-P90 intervals using
    only historical forecast errors available before each test week.
    """
    tests = list(tests)

    point_forecasts = []
    lower_bounds = []
    upper_bounds = []

    historical_errors = []
    forecast_cache = {}
    next_origin = MIN_HIST + 1

    for t in tests:

        # Add errors from forecast origins strictly before week t
        while next_origin < t:

            if next_origin not in forecast_cache:
                previous_forecast = ml_forecast(
                    w, ev, next_origin, kind
                )
                forecast_cache[next_origin] = previous_forecast

            previous_forecast = forecast_cache[next_origin]

            error = w[:, next_origin] - previous_forecast
            historical_errors.append(error)

            next_origin += 1

        # Forecast the current week
        forecast = ml_forecast(w, ev, t, kind)
        forecast_cache[t] = forecast
        point_forecasts.append(forecast)

        # Calculate intervals when enough historical errors exist
        if len(historical_errors) >= 2:
            errors_array = np.vstack(historical_errors)

            lower, upper = prediction_interval(
                forecast, errors_array
            )
        else:
            lower = np.full_like(forecast, np.nan)
            upper = np.full_like(forecast, np.nan)

        lower_bounds.append(lower)
        upper_bounds.append(upper)

    return point_forecasts, lower_bounds, upper_bounds



def weekly_level(df, level):
    w_df, ev_df = weekly_panel(df, level)
    w, ev = w_df.values, ev_df.values

    tests = range(FIRST_TEST_WEEK, w.shape[1])
    A = np.array([w[:, t] for t in tests])

    # Existing baseline forecasts
    P = {
        "naive": [naive(w, t) for t in tests],
        "ma4": [ma(w, t, 4) for t in tests],
        "ma8": [ma(w, t, 8) for t in tests],
    }

    results = []

    # Ridge and GBM forecasts with prediction intervals
    for kind in ["ridge", "gbm"]:
        forecasts, lower, upper = _rolling_ml_forecasts(
            w, ev, tests, kind
        )

        P[kind] = forecasts

        results.append(
            _interval_row(
                f"weekly_{level}",
                kind,
                A,
                lower,
                upper
            )
        )

    # Keep the original WAPE and Bias evaluation
    results = [
        _row(f"weekly_{level}", k, A, v)
        for k, v in P.items()
    ] + results

    return results




def weekly_family_wape(df):
    w_df, ev_df = weekly_panel(df, "family")

    w = w_df.values
    ev = ev_df.values

    tests = list(range(FIRST_TEST_WEEK, w.shape[1]))

    # Actual demand: rows = test weeks, columns = families
    A = np.array([w[:, t] for t in tests])

    # Generate forecasts using the existing methods
    P = {
        "naive": [naive(w, t) for t in tests],
        "ma4": [ma(w, t, 4) for t in tests],
        "ma8": [ma(w, t, 8) for t in tests],
    }

    for kind in ["ridge", "gbm"]:
        forecasts, _, _ = _rolling_ml_forecasts(
            w, ev, tests, kind
        )
        P[kind] = forecasts

    records = []

    for model, forecasts in P.items():
        F = np.asarray(forecasts)

        for j, family in enumerate(w_df.index):
            actual = A[:, j]
            predicted = F[:, j]

            denominator = np.abs(actual).sum()

            wape = (
                np.abs(actual - predicted).sum() / denominator
                if denominator > 0
                else np.nan
            )

            records.append({
                "family": family,
                "model": model,
                "WAPE": wape
            })

    result = pd.DataFrame(records)

    # Show the best model for each family
    best = (
        result.dropna(subset=["WAPE"])
        .sort_values("WAPE")
        .groupby("family")
        .first()
        .reset_index()
    )

    return result, best





def weekly_family_model_selection(df, validation_weeks=5):
    w_df, ev_df = weekly_panel(df, "family")

    w = w_df.values
    ev = ev_df.values

    tests = list(range(FIRST_TEST_WEEK, w.shape[1]))

    if len(tests) <= validation_weeks:
        raise ValueError("Not enough test weeks for validation and final test.")

    validation_tests = tests[:validation_weeks]
    final_tests = tests[validation_weeks:]

    def get_forecasts(test_weeks):
        forecasts = {
            "naive": [naive(w, t) for t in test_weeks],
            "ma4": [ma(w, t, 4) for t in test_weeks],
            "ma8": [ma(w, t, 8) for t in test_weeks],
        }

        for kind in ["ridge", "gbm"]:
            predictions = []

            for t in test_weeks:
                pred, _, _ = _rolling_ml_forecasts(
                    w, ev, [t], kind
                )
                predictions.append(pred[0])

            forecasts[kind] = predictions

        return forecasts

    validation_predictions = get_forecasts(validation_tests)
    final_predictions = get_forecasts(final_tests)

    def calculate_wape(actual, predicted):
        denominator = np.abs(actual).sum()

        if denominator == 0:
            return np.nan

        return np.abs(actual - predicted).sum() / denominator

    validation_actual = np.array([w[:, t] for t in validation_tests])
    final_actual = np.array([w[:, t] for t in final_tests])

    models = list(validation_predictions.keys())
    families = list(w_df.index)

    # Select one model per family using validation weeks only
    selected_models = {}

    for j, family in enumerate(families):
        scores = {}

        for model in models:
            predictions = np.asarray(
                validation_predictions[model]
            )[:, j]

            scores[model] = calculate_wape(
                validation_actual[:, j],
                predictions
            )

        selected_models[family] = min(
            scores, key=lambda model: (
                scores[model] if np.isfinite(scores[model])
                else float("inf")
            )
        )

    # Evaluate selected models on unseen final weeks
    records = []

    for strategy in ["ridge", "gbm", "family_selected"]:
        for j, family in enumerate(families):
            if strategy == "family_selected":
                model = selected_models[family]
            else:
                model = strategy

            predictions = np.asarray(
                final_predictions[model]
            )[:, j]

            records.append({
                "family": family,
                "strategy": strategy,
                "selected_model": model,
                "WAPE": calculate_wape(
                    final_actual[:, j],
                    predictions
                )
            })

    result = pd.DataFrame(records)

    # Overall WAPE across all families
    overall = []

    for strategy in ["ridge", "gbm", "family_selected"]:
        predictions = []

        for j, family in enumerate(families):
            if strategy == "family_selected":
                model = selected_models[family]
            else:
                model = strategy

            predictions.append(
                np.asarray(final_predictions[model])[:, j]
            )

        predictions = np.column_stack(predictions)

        overall.append({
            "strategy": strategy,
            "overall_WAPE": calculate_wape(
                final_actual,
                predictions
            )
        })

    return result, pd.DataFrame(overall)




def weekly_sku_allocated(df):
    sku_w, _ = weekly_panel(df, "item_code")
    fam_w, ev_df = weekly_panel(df, "family")

    S = sku_w.values
    f_w = fam_w.values
    ev = ev_df.values

    sku_family = (
        df.drop_duplicates("item_code")
        .set_index("item_code").family
    )
    fam_index = {f: i for i, f in enumerate(fam_w.index)}

    tests = list(range(FIRST_TEST_WEEK, f_w.shape[1]))
    A = np.array([S[:, t] for t in tests])

    # Existing SKU baselines + intermittent demand methods
    P = {
        "ma8": [ma(S, t, 8) for t in tests],
        "ma4": [ma(S, t, 4) for t in tests],
        "croston": [croston(S, t) for t in tests],
        "sba": [sba(S, t) for t in tests],
        "tsb": [tsb(S, t) for t in tests],
    }

    interval_results = []

    for kind in ["ridge", "gbm"]:

        # Forecast family demand and calculate its intervals
        fam_forecasts, fam_lower, fam_upper = _rolling_ml_forecasts(
            f_w, ev, tests, kind
        )

        for window in [4, 8, 12]:

            sku_forecasts = []
            sku_lower = []
            sku_upper = []

            for i, t in enumerate(tests):

                # Historical SKU demand using the selected window
                sku_hist = S[:, t - window:t].sum(axis=1)

                sku_forecasts.append(
                    allocate_by_share(
                        fam_forecasts[i], fam_index,
                        sku_w.index, sku_family, sku_hist
                    )
                )

                sku_lower.append(
                    allocate_by_share(
                        fam_lower[i], fam_index,
                        sku_w.index, sku_family, sku_hist
                    )
                )

                sku_upper.append(
                    allocate_by_share(
                        fam_upper[i], fam_index,
                        sku_w.index, sku_family, sku_hist
                    )
                )

            # Keep the original model name for the 8-week window
            model_name = (
                f"family-{kind}->alloc"
                if window == 8
                else f"family-{kind}->alloc-{window}w"
            )

            P[model_name] = sku_forecasts

            interval_results.append(
                _interval_row(
                    "weekly_sku",
                    model_name,
                    A,
                    sku_lower,
                    sku_upper
                )
            )

    results = [
        _row("weekly_sku", k, A, v)
        for k, v in P.items()
    ]

    return results + interval_results



def monthly_sku(df):
    m = monthly_panel(df, "item_code").values

    tests = list(range(FIRST_TEST_MONTH, m.shape[1]))
    A = np.array([m[:, t] for t in tests])

    P = {}
    interval_results = []

    for kind in ["naive", "expanding_mean"]:

        forecasts = []
        lower_bounds = []
        upper_bounds = []

        historical_errors = []
        next_origin = 1

        for t in tests:

            # Add errors from previous monthly forecasts only
            while next_origin < t:

                if kind == "naive":
                    previous_forecast = m[:, next_origin - 1]
                else:
                    previous_forecast = m[:, :next_origin].mean(axis=1)

                error = m[:, next_origin] - previous_forecast
                historical_errors.append(error)

                next_origin += 1

            # Forecast the current month
            if kind == "naive":
                forecast = m[:, t - 1]
            else:
                forecast = m[:, :t].mean(axis=1)

            forecasts.append(forecast)

            # Calculate P10-P90 intervals
            if len(historical_errors) >= 2:
                errors_array = np.vstack(historical_errors)

                lower, upper = prediction_interval(
                    forecast, errors_array
                )
            else:
                lower = np.full_like(forecast, np.nan)
                upper = np.full_like(forecast, np.nan)

            lower_bounds.append(lower)
            upper_bounds.append(upper)

        P[kind] = forecasts

        interval_results.append(
            _interval_row(
                "monthly_sku",
                kind,
                A,
                lower_bounds,
                upper_bounds
            )
        )

    results = [
        _row("monthly_sku", kind, A, forecasts)
        for kind, forecasts in P.items()
    ]

    return results + interval_results



def weekly_sku_model_comparison(df):
    sku_w, _ = weekly_panel(df, "item_code")
    fam_w, ev_df = weekly_panel(df, "family")

    S = sku_w.values
    f_w = fam_w.values
    ev = ev_df.values

    sku_family = (
        df.drop_duplicates("item_code")
        .set_index("item_code").family
    )
    fam_index = {f: i for i, f in enumerate(fam_w.index)}

    tests = list(range(FIRST_TEST_WEEK, S.shape[1]))
    A = np.array([S[:, t] for t in tests])

    # Direct SKU-level forecasts
    P = {
        "ma4": [ma(S, t, 4) for t in tests],
        "ma8": [ma(S, t, 8) for t in tests],
        "croston": [croston(S, t) for t in tests],
        "sba": [sba(S, t) for t in tests],
        "tsb": [tsb(S, t) for t in tests],
    }

    # Family forecasts allocated to SKUs using 8-week shares
    for kind in ["ridge", "gbm"]:
        fam_forecasts, _, _ = _rolling_ml_forecasts(
            f_w, ev, tests, kind
        )

        sku_forecasts = []

        for i, t in enumerate(tests):
            sku_hist = S[:, t - 8:t].sum(axis=1)

            sku_forecasts.append(
                allocate_by_share(
                    fam_forecasts[i],
                    fam_index,
                    sku_w.index,
                    sku_family,
                    sku_hist
                )
            )

        P[f"family-{kind}->alloc"] = sku_forecasts

    # Calculate WAPE and Bias separately for each SKU
    records = []

    for model, forecasts in P.items():
        F = np.asarray(forecasts)

        for j, sku in enumerate(sku_w.index):
            actual = A[:, j]
            predicted = F[:, j]

            denominator = np.abs(actual).sum()

            if denominator == 0:
                sku_wape = np.nan
                sku_bias = np.nan
            else:
                sku_wape = (
                    np.abs(actual - predicted).sum()
                    / denominator
                )

                sku_bias = (
                    (predicted - actual).sum()
                    / denominator
                )

            records.append({
                "item_code": sku,
                "family": sku_family.loc[sku],
                "model": model,
                "WAPE": sku_wape,
                "bias": sku_bias
            })

    comparison = pd.DataFrame(records)

    # Select the best model for each SKU using the lowest WAPE
    best = (
        comparison.dropna(subset=["WAPE"])
        .sort_values("WAPE")
        .groupby("item_code")
        .first()
        .reset_index()
    )

    return comparison, best



def weekly_sku_model_selection(df, validation_weeks=5):
    sku_w, _ = weekly_panel(df, "item_code")
    fam_w, ev_df = weekly_panel(df, "family")

    S = sku_w.values
    f_w = fam_w.values
    ev = ev_df.values

    sku_family = (
        df.drop_duplicates("item_code")
        .set_index("item_code").family
    )
    fam_index = {f: i for i, f in enumerate(fam_w.index)}

    tests = list(range(FIRST_TEST_WEEK, S.shape[1]))

    if validation_weeks < 1 or validation_weeks >= len(tests):
        raise ValueError(
            "validation_weeks must be at least 1 and smaller than the number of test weeks."
        )

    A = np.array([S[:, t] for t in tests])

    # Direct SKU-level forecasts
    P = {
        "ma4": [ma(S, t, 4) for t in tests],
        "ma8": [ma(S, t, 8) for t in tests],
        "croston": [croston(S, t) for t in tests],
        "sba": [sba(S, t) for t in tests],
        "tsb": [tsb(S, t) for t in tests],
    }

    # Family forecasts allocated to SKUs using 8-week shares
    for kind in ["ridge", "gbm"]:
        fam_forecasts, _, _ = _rolling_ml_forecasts(
            f_w, ev, tests, kind
        )

        sku_forecasts = []

        for i, t in enumerate(tests):
            sku_hist = S[:, t - 8:t].sum(axis=1)

            sku_forecasts.append(
                allocate_by_share(
                    fam_forecasts[i],
                    fam_index,
                    sku_w.index,
                    sku_family,
                    sku_hist
                )
            )

        P[f"family-{kind}->alloc"] = sku_forecasts

    # Convert forecasts to arrays: (weeks, SKUs)
    P = {
        model: np.asarray(forecasts)
        for model, forecasts in P.items()
    }

    # Split validation and final test
    val_actual = A[:validation_weeks]
    final_actual = A[validation_weeks:]

    # Evaluate every model for every SKU on validation data
    validation_records = []

    for model, forecasts in P.items():
        val_forecast = forecasts[:validation_weeks]

        for j, sku in enumerate(sku_w.index):
            actual = val_actual[:, j]
            predicted = val_forecast[:, j]
            denominator = np.abs(actual).sum()

            if denominator == 0:
                sku_wape = np.nan
                sku_bias = np.nan
            else:
                sku_wape = (
                    np.abs(actual - predicted).sum() / denominator
                )
                sku_bias = (
                    (predicted - actual).sum() / denominator
                )

            validation_records.append({
                "item_code": sku,
                "family": sku_family.loc[sku],
                "model": model,
                "WAPE": sku_wape,
                "bias": sku_bias
            })

    validation_comparison = pd.DataFrame(validation_records)

    # Select one model per SKU using validation WAPE only
    selected_models = (
        validation_comparison.dropna(subset=["WAPE"])
        .sort_values("WAPE")
        .groupby("item_code")
        .first()
        .reset_index()
    )

    selected_map = selected_models.set_index("item_code")["model"].to_dict()

    # Evaluate selected models on the untouched final test period
    final_records = []
    selected_forecasts = []

    for j, sku in enumerate(sku_w.index):
        model = selected_map.get(sku)

        if model is None:
            continue

        predicted = P[model][validation_weeks:, j]
        actual = final_actual[:, j]
        denominator = np.abs(actual).sum()

        if denominator == 0:
            sku_wape = np.nan
            sku_bias = np.nan
        else:
            sku_wape = (
                np.abs(actual - predicted).sum() / denominator
            )
            sku_bias = (
                (predicted - actual).sum() / denominator
            )

        final_records.append({
            "item_code": sku,
            "family": sku_family.loc[sku],
            "selected_model": model,
            "final_WAPE": sku_wape,
            "final_bias": sku_bias
        })

        selected_forecasts.append(predicted)

    final_sku_results = pd.DataFrame(final_records)

    # Overall final-test comparison against every individual model
    overall_records = []

    for model, forecasts in P.items():
        final_forecast = forecasts[validation_weeks:]

        overall_records.append({
            "model": model,
            "WAPE": wape(final_actual, final_forecast),
            "bias": bias(final_actual, final_forecast)
        })

    # Add the per-SKU selected-model combination
    if selected_forecasts:
        selected_forecasts = np.asarray(selected_forecasts).T
        sku_positions = {
            sku: j for j, sku in enumerate(sku_w.index)
            }
        selected_actual = np.column_stack([
        final_actual[:, sku_positions[sku]]
        for sku in final_sku_results["item_code"]
        ])

        overall_records.append({
            "model": "sku_selected",
            "WAPE": wape(selected_actual, selected_forecasts),
            "bias": bias(selected_actual, selected_forecasts)
        })

    final_overall_comparison = (
        pd.DataFrame(overall_records)
        .sort_values("WAPE")
        .reset_index(drop=True)
    )

    return (
        validation_comparison,
        selected_models,
        final_sku_results,
        final_overall_comparison
    )


