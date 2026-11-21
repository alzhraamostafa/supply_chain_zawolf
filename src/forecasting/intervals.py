
"""Prediction intervals based on historical rolling-origin forecast errors."""

import numpy as np


def prediction_interval(point_forecast, historical_errors):
    """
    Build P10-P90 prediction intervals from historical forecast errors.

    Errors must be:
        actual_demand - previous_forecast

    For 2D errors:
        rows = historical forecast origins
        columns = individual time series

    Only errors from forecast origins before the current forecast may be used.
    """
    forecast = np.asarray(point_forecast, dtype=float)
    errors = np.asarray(historical_errors, dtype=float)

    if errors.ndim not in (1, 2) or errors.shape[0] < 2:
        raise ValueError("At least two historical errors are required.")

    if not np.all(np.isfinite(errors)):
        raise ValueError("Historical errors must be finite.")

    if not np.all(np.isfinite(forecast)):
        raise ValueError("Point forecasts must be finite.")

    if errors.ndim == 2 and errors.shape[1:] != forecast.shape:
        raise ValueError("Error columns must match the forecast shape.")

    q10, q90 = np.quantile(errors, [0.10, 0.90], axis=0)

    lower = np.maximum(forecast + q10, 0.0)
    upper = np.maximum(forecast + q90, 0.0)

    return lower, upper
