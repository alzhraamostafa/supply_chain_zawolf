import numpy as np
from forecasting.features import build_predict

def test_features_ignore_future_weeks():
    rng = np.random.default_rng(0)
    w = rng.integers(1, 100, size=(5, 20)).astype(float)
    ev = np.zeros((20, 5))
    t = 12
    a, _ = build_predict(w, ev, t)
    w2 = w.copy()
    w2[:, t:] = 9999          # change the future
    b, _ = build_predict(w2, ev, t)
    assert np.array_equal(a, b)
