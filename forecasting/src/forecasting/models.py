import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from .config import MIN_HIST
from .features import build_train, build_predict


def make_model(kind: str):
    if kind == "gbm":
        return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150,
                                             min_samples_leaf=10, l2_regularization=1.0, random_state=0)
    if kind == "ridge":
        return Ridge(alpha=5.0)
    raise ValueError(kind)


def ml_forecast(w, ev, t, kind="gbm") -> np.ndarray:
    """Train on targets strictly before week t, predict week t."""
    Xtr, ytr = build_train(w, ev, MIN_HIST, t)
    Xte, sc = build_predict(w, ev, t)
    m = make_model(kind).fit(Xtr, ytr)
    return np.clip(m.predict(Xte), 0, None) * sc