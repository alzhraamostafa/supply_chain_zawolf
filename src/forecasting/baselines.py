
"""Baselines: the forecast for week index t uses only weeks before t."""
import numpy as np


def naive(w: np.ndarray, t: int) -> np.ndarray:
    return w[:, t - 1]


def ma(w: np.ndarray, t: int, k: int) -> np.ndarray:
    return w[:, t - k:t].mean(axis=1)


def croston_series(y: np.ndarray, alpha: float = 0.1) -> float:
    """Croston forecast for one intermittent-demand series."""
    y = np.asarray(y, dtype=float)
    positive = np.flatnonzero(y > 0)

    if len(positive) == 0:
        return 0.0

    first = positive[0]
    demand_size = y[first]
    interval = first + 1

    previous = first

    for idx in positive[1:]:
        gap = idx - previous
        demand_size = alpha * y[idx] + (1 - alpha) * demand_size
        interval = alpha * gap + (1 - alpha) * interval
        previous = idx

    return demand_size / interval


def croston(w: np.ndarray, t: int, alpha: float = 0.1) -> np.ndarray:
    """Apply Croston independently to each series using weeks before t."""
    return np.array([
        croston_series(w[i, :t], alpha)
        for i in range(w.shape[0])
    ])


def sba(w: np.ndarray, t: int, alpha: float = 0.1) -> np.ndarray:
    """Syntetos-Boylan Approximation."""
    return (1 - alpha / 2) * croston(w, t, alpha)


def tsb_series(
    y: np.ndarray,
    alpha: float = 0.1,
    beta: float = 0.1
) -> float:
    """Teunter-Syntetos-Babai forecast for one series."""
    y = np.asarray(y, dtype=float)

    if len(y) == 0:
        return 0.0

    first = np.flatnonzero(y > 0)

    if len(first) == 0:
        return 0.0

    probability = 1.0
    demand_size = y[first[0]]

    for value in y:
        occurred = float(value > 0)

        probability += beta * (occurred - probability)

        if occurred:
            demand_size += alpha * (value - demand_size)

    return probability * demand_size


def tsb(
    w: np.ndarray,
    t: int,
    alpha: float = 0.1,
    beta: float = 0.1
) -> np.ndarray:
    """Apply TSB independently to each series using weeks before t."""
    return np.array([
        tsb_series(w[i, :t], alpha, beta)
        for i in range(w.shape[0])
    ])


