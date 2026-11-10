"""Scale-free features. A row (series i, week t) uses only weeks before t,
plus the calendar flags of week t (calendar is known in advance)."""
import numpy as np
from .config import LAGS


def row_features(w, ev, i, t):
    hist = w[i, :t]
    scale = hist[-8:].mean() + 1.0
    f = [hist[-k] / scale for k in range(1, LAGS + 1)]
    f += [hist[-4:].mean() / scale, hist[-4:].std() / scale, np.log1p(scale)]
    f += list(ev[t])
    return f, scale


def build_train(w, ev, t_lo, t_hi):
    X, y = [], []
    for t in range(t_lo, t_hi):
        for i in range(w.shape[0]):
            f, scale = row_features(w, ev, i, t)
            X.append(f)
            y.append(w[i, t] / scale)
    return np.array(X), np.array(y)


def build_predict(w, ev, t):
    X, sc = [], []
    for i in range(w.shape[0]):
        f, scale = row_features(w, ev, i, t)
        X.append(f)
        sc.append(scale)
    return np.array(X), np.array(sc)