
import numpy as np
import pytest

from forecasting.intervals import prediction_interval


def test_prediction_interval():
    forecast = np.array([100.0])
    errors = np.array([-20, -10, 0, 10, 30])

    lower, upper = prediction_interval(forecast, errors)

    assert np.allclose(lower, [84.0])
    assert np.allclose(upper, [122.0])


def test_prediction_interval_never_negative():
    forecast = np.array([5.0])
    errors = np.array([-20, -10, 0, 10, 30])

    lower, upper = prediction_interval(forecast, errors)

    assert np.all(lower >= 0)
    assert np.all(upper >= 0)


def test_prediction_interval_requires_enough_errors():
    with pytest.raises(ValueError):
        prediction_interval([100], [10])



def test_prediction_interval_handles_multiple_series():
    forecast = np.array([100.0, 200.0])

    errors = np.array([
        [-20, -40],
        [-10, -20],
        [0, 0],
        [10, 20],
        [30, 60]
    ])

    lower, upper = prediction_interval(forecast, errors)

    assert np.allclose(lower, [84.0, 168.0])
    assert np.allclose(upper, [122.0, 244.0])
