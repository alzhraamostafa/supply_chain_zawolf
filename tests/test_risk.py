import random

from risk.engine import (ALERT_THRESHOLD, STRUCTURAL_WEIGHTS, Delivery, SupplyHistory, assess,
                         shortage_probability)
from risk.scenarios import make_scenario


def history(delays, lead=8, n_suppliers=2, criticality=0.0, cover=None, yield_rate=0.995):
    return SupplyHistory("Glycerin", [Delivery(lead, lead + d, yield_rate) for d in delays],
                         n_suppliers, criticality, cover)


def test_no_history_is_unknown_not_safe():
    a = assess(SupplyHistory("X", [], 1))
    assert a.level == "unknown" and a.shortage_probability is None and a.confidence == 0.0
    assert a.actions


def test_unknown_stock_is_not_treated_as_zero():
    a = assess(history([0] * 20, cover=None))
    assert a.shortage_probability is None
    assert any("stock on hand is unknown" in u for u in a.unknown)
    assert a.confidence == 0.6            # 20 deliveries, but no stock figure


def test_stock_below_lead_time_is_a_certain_shortage():
    a = assess(history([0] * 20, lead=8, cover=5))
    assert a.shortage_probability == 1.0
    assert a.level in ("high", "critical")
    assert any("Expedite" in x for x in a.actions)


def test_reliable_supplier_with_a_big_buffer_is_low_risk():
    a = assess(history([0] * 25, lead=8, n_suppliers=3, cover=20))
    assert a.shortage_probability < 0.05 and a.level == "low" and a.actions == []


def test_probability_comes_from_how_often_past_delays_exceeded_the_buffer():
    delays = [0] * 14 + [5] * 6                      # 6 of 20 deliveries were 5 days late
    p_thin = shortage_probability(history(delays, lead=8, cover=11))    # buffer 3 days
    p_wide = shortage_probability(history(delays, lead=8, cover=16))    # buffer 8 days
    assert abs(p_thin - (6 + 0.5) / 21) < 1e-9
    assert abs(p_wide - 0.5 / 21) < 1e-9


def test_critical_material_raises_the_level():
    delays = [0] * 14 + [5] * 6
    normal = assess(history(delays, cover=11, criticality=0.1))
    critical = assess(history(delays, cover=11, criticality=0.9))
    order = ["low", "medium", "high", "critical"]
    assert order.index(critical.level) > order.index(normal.level)


def test_explanation_adds_up_to_the_score_and_is_sorted():
    a = assess(history([0] * 15 + [4] * 5, n_suppliers=1))
    assert abs(sum(f.contribution for f in a.factors) - a.risk_score) < 0.01
    contributions = [f.contribution for f in a.factors]
    assert contributions == sorted(contributions, reverse=True)


def test_single_source_raises_the_score():
    one = assess(history([0] * 20, n_suppliers=1)).risk_score
    three = assess(history([0] * 20, n_suppliers=3)).risk_score
    assert one > three


def test_one_delivery_gives_low_confidence_but_no_crash():
    a = assess(history([0], cover=20))
    assert a.confidence <= 0.05


def test_structural_weights_sum_to_one():
    assert abs(sum(STRUCTURAL_WEIGHTS.values()) - 1.0) < 1e-9


def test_planted_scenarios_precision_and_recall():
    """The plan's targets: precision >= 70% and recall >= 70%. A missed shortage is worse than a false alarm,
    so recall must be at least 85% here."""
    for seed in (42, 7):
        rng = random.Random(seed)
        tp = fp = fn = 0
        for _ in range(2000):
            h, shortage = make_scenario(rng)
            alert = assess(h).shortage_probability >= ALERT_THRESHOLD
            tp += alert and shortage
            fp += alert and not shortage
            fn += (not alert) and shortage
        assert tp / (tp + fp) >= 0.70
        assert tp / (tp + fn) >= 0.85