import json
import pytest
from datetime import date
from pydantic import ValidationError
from contracts.forecast import ForecastPoint, ForecastPayload, to_envelope


def point(**over):
    base = dict(series_id="Body Lotion", week_start=date(2026, 6, 22), p50=100.0)
    base.update(over)
    return ForecastPoint(**base)


def test_quantiles_must_be_ordered():
    with pytest.raises(ValidationError):
        point(p10=120.0)
    with pytest.raises(ValidationError):
        point(p90=80.0)


def test_negative_forecast_rejected():
    with pytest.raises(ValidationError):
        point(p50=-1.0)


def test_payload_needs_at_least_one_forecast():
    with pytest.raises(ValidationError):
        ForecastPayload(level="family", horizon_weeks=1, algorithm="ridge", forecasts=[])


def test_envelope_is_json_serializable():
    payload = ForecastPayload(level="family", horizon_weeks=1, algorithm="ridge",
                              forecasts=[point(p10=80.0, p90=130.0)], backtest_wape=0.16)
    env = to_envelope(payload, source=["fact_commercial_demand_m5"], confidence=0.8)
    assert env.component == "demand_forecast"
    assert env.requires_human_approval is True
    json.dumps(env.model_dump(mode="json"))
