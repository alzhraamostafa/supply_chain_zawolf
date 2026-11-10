from forecasting.metrics import wape, bias

def test_wape_and_bias():
    assert wape([10, 10], [8, 12]) == 0.2
    assert bias([10, 10], [8, 8]) == -0.2
