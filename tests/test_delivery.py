from datetime import date, timedelta

from delivery.agent import Shipment, evaluate, evaluate_all

TODAY = date(2026, 11, 23)


def day(n):
    return TODAY + timedelta(days=n)


def ship(**over):
    base = dict(po_number="PO-1", material="Glycerin", supplier="SUP-EG-01", ordered_qty=1000,
                promised_date=day(10), original_needed_by=day(14), needed_by=day(14), eta=day(10),
                criticality=0.9, alternative_suppliers=1)
    base.update(over)
    return Shipment(**base)


def types(report):
    return {i.type for i in report.issues}


def test_on_time_shipment_is_on_track():
    r = evaluate(ship(), TODAY)
    assert r.status == "on_track" and r.severity == "info" and r.cause == "none"
    assert r.issues == [] and r.actions == [] and r.slack_days == 4


def test_supplier_delay_with_slack_is_a_warning_not_a_stockout():
    r = evaluate(ship(eta=day(13)), TODAY)          # 3 days late, still 1 day before it is needed
    assert types(r) == {"supplier_delay"} and r.cause == "supplier"
    assert r.severity == "warning" and r.slack_days == 1
    assert "Ask SUP-EG-01" in r.actions[0]


def test_supplier_delay_on_a_critical_material_that_causes_a_stockout():
    r = evaluate(ship(eta=day(17)), TODAY)          # arrives 3 days after production needs it
    assert types(r) == {"supplier_delay", "stockout_risk"} and r.cause == "supplier"
    assert r.severity == "critical" and r.slack_days == -3
    assert any("Expedite" in a for a in r.actions)
    assert any("alternative supplier (1 on file)" in a for a in r.actions)
    assert any("production plan" in a for a in r.actions)


def test_small_stockout_on_a_minor_material_is_only_a_warning():
    r = evaluate(ship(eta=day(15), criticality=0.1), TODAY)     # 1 day short, material used by few products
    assert "stockout_risk" in types(r) and r.severity == "warning"


def test_plan_change_is_not_blamed_on_the_supplier():
    r = evaluate(ship(needed_by=day(8)), TODAY)     # supplier on time, but production now needs it earlier
    assert "supplier_delay" not in types(r) and "plan_change" in types(r)
    assert r.cause == "plan" and "stockout_risk" in types(r) and r.severity == "critical"
    assert "need date moved earlier" in r.actions[0]


def test_plan_moved_later_is_good_news_not_an_exception():
    r = evaluate(ship(needed_by=day(20)), TODAY)
    assert types(r) == {"plan_change"} and r.status == "on_track" and r.severity == "info"
    assert r.cause == "none" and r.slack_days == 10


def test_plan_moved_earlier_with_plenty_of_slack_is_only_informational():
    r = evaluate(ship(needed_by=day(12)), TODAY)    # moved 2 days earlier, still 2 days of slack
    assert types(r) == {"plan_change"} and r.severity == "info"


def test_plan_moved_earlier_leaving_one_day_of_slack_is_a_warning():
    r = evaluate(ship(needed_by=day(11)), TODAY)    # slack is now 1 day
    assert r.severity == "warning" and r.cause == "plan"


def test_supplier_delay_and_plan_change_together():
    r = evaluate(ship(eta=day(13), needed_by=day(11)), TODAY)
    assert r.cause == "both" and {"supplier_delay", "plan_change", "stockout_risk"} <= types(r)


def test_short_delivery_thresholds():
    assert evaluate(ship(received_qty=985, received_date=day(10)), TODAY).issues == []      # within 2%
    mild = evaluate(ship(received_qty=900, received_date=day(10)), TODAY)
    assert types(mild) == {"short_delivery"} and mild.severity == "warning"
    assert "100" in mild.actions[0]
    bad = evaluate(ship(received_qty=700, received_date=day(10)), TODAY)
    assert bad.severity == "critical"                                                       # <80% of a critical material


def test_failed_inspection_holds_the_lot():
    r = evaluate(ship(received_qty=1000, received_date=day(10), quality_ok=False), TODAY)
    assert types(r) == {"quality_hold"} and r.severity == "critical"
    assert any("Hold the lot" in a for a in r.actions)


def test_overdue_with_no_news_is_flagged_and_never_assumed_fine():
    r = evaluate(ship(promised_date=day(-2), eta=None, needed_by=day(1), original_needed_by=day(1)), TODAY)
    assert "no_update" in types(r) and r.severity == "warning" and r.slack_days == 1
    waiting = evaluate(ship(promised_date=day(-5), eta=None, needed_by=day(-1), original_needed_by=day(-1)), TODAY)
    assert "stockout_risk" in types(waiting) and waiting.severity == "critical"
    assert "at least 1 day(s)" in [i.message for i in waiting.issues if i.type == "stockout_risk"][0]


def test_not_yet_due_with_no_news_is_fine():
    r = evaluate(ship(eta=None), TODAY)
    assert r.status == "on_track" and r.slack_days is None


def test_unknown_criticality_is_treated_as_critical():
    r = evaluate(ship(eta=day(15), criticality=None), TODAY)        # 1 day short
    assert r.severity == "critical"
    assert "criticality unknown" in [i.message for i in r.issues if i.type == "stockout_risk"][0]


def test_unknown_alternatives_are_said_to_be_unknown():
    r = evaluate(ship(eta=day(17), alternative_suppliers=None), TODAY)
    assert any("Check whether an alternative supplier" in a for a in r.actions)
    none_on_file = evaluate(ship(eta=day(17), alternative_suppliers=0), TODAY)
    assert any("No alternative supplier on file" in a for a in none_on_file.actions)


def test_every_report_needs_a_human_and_results_are_sorted():
    reports = evaluate_all([ship(po_number="A"), ship(po_number="B", eta=day(17)),
                            ship(po_number="C", eta=day(13))], TODAY)
    assert [r.po_number for r in reports] == ["B", "C", "A"]
    assert all(r.requires_human_approval for r in reports)