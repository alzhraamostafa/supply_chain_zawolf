from forecasting.data import ALLOWED, LEAKY

def test_leaky_columns_never_allowed():
    assert not (set(ALLOWED) & LEAKY)
