import numpy as np


def wape(actual, forecast) -> float:
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    return float(np.abs(a - f).sum() / a.sum())


def bias(actual, forecast) -> float:
    a, f = np.asarray(actual, float), np.asarray(forecast, float)
    return float((f - a).sum() / a.sum())