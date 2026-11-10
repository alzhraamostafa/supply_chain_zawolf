"""Baselines: the forecast for week index t uses only weeks before t."""
import numpy as np


def naive(w: np.ndarray, t: int) -> np.ndarray:
    return w[:, t - 1]


def ma(w: np.ndarray, t: int, k: int) -> np.ndarray:
    return w[:, t - k:t].mean(axis=1)