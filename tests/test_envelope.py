import pytest
from pydantic import ValidationError
from contracts.envelope import OutputEnvelope


def make(**over):
    base = dict(component="demand_forecast", source=["fact_commercial_demand_m5"],
                confidence=0.8, payload={"horizon_weeks": 1})
    base.update(over)
    return OutputEnvelope(**base)


def test_valid_envelope_defaults():
    e = make()
    assert e.requires_human_approval is True
    assert e.autonomy_level == 0
    assert e.id and e.created_at.tzinfo is not None


def test_source_is_required():
    with pytest.raises(ValidationError):
        make(source=[])


def test_confidence_must_be_between_0_and_1():
    with pytest.raises(ValidationError):
        make(confidence=1.5)


def test_unknown_component_rejected():
    with pytest.raises(ValidationError):
        make(component="magic")


def test_low_autonomy_cannot_skip_approval():
    with pytest.raises(ValidationError):
        make(autonomy_level=1, requires_human_approval=False)
