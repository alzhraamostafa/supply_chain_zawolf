import pytest
from risk.api_payload import build_risk_payload, overall_confidence
from risk.engine import Delivery, SupplyHistory, assess


def item(name, delays, cover=None, criticality=0.0, n_suppliers=1):
    deliveries = [Delivery(8, 8 + d, 0.995) for d in delays]
    return assess(SupplyHistory(name, deliveries, n_suppliers, criticality, cover))


def sample():
    return [
        item("calm", [0] * 20, cover=30, n_suppliers=3),                 # low
        item("short", [0] * 20, cover=5, criticality=0.9),               # critical (stock below lead time)
        item("no_history", []),                                          # unknown
        item("shaky", [0] * 12 + [3] * 8, cover=9, criticality=0.1),     # at least medium
    ]


def test_counts_and_order_most_severe_first():
    payload = build_risk_payload(sample(), [])
    assert sum(payload["counts"].values()) == 4
    assert payload["counts"]["critical"] == 1 and payload["counts"]["unknown"] == 1
    assert payload["assessments"][0]["material"] == "short"
    assert payload["assessments"][-1]["level"] == "unknown"
    assert payload["stock_known_for"] == 3


def test_level_filter_keeps_the_full_counts():
    payload = build_risk_payload(sample(), [], level="unknown")
    assert [a["material"] for a in payload["assessments"]] == ["no_history"]
    assert sum(payload["counts"].values()) == 4


def test_limit_and_validation():
    assert len(build_risk_payload(sample(), [], limit=2)["assessments"]) == 2
    with pytest.raises(ValueError):
        build_risk_payload(sample(), [], level="catastrophic")
    with pytest.raises(ValueError):
        build_risk_payload(sample(), [], limit=0)


def test_unmatched_skus_are_passed_through():
    assert build_risk_payload(sample(), ["MYSTERY"])["unmatched_skus"] == ["MYSTERY"]


def test_overall_confidence_ignores_unknown_items():
    assert overall_confidence([item("no_history", [])]) == 0.0
    both = overall_confidence(sample())
    assert 0 < both <= 1