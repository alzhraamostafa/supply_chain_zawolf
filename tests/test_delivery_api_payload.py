import json
from datetime import date, timedelta

from delivery.agent import Shipment, evaluate_all
from delivery.api_payload import build_delivery_payload, input_completeness

TODAY = date(2026, 11, 23)


def day(n):
    return TODAY + timedelta(days=n)


def ship(po, **over):
    base = dict(po_number=po, material="Glycerin", supplier="S1", ordered_qty=100, promised_date=day(10),
                original_needed_by=day(14), needed_by=day(14), eta=day(10), criticality=0.9,
                alternative_suppliers=1)
    base.update(over)
    return Shipment(**base)


def test_counts_and_needs_attention():
    shipments = [ship("A"), ship("B", eta=day(17)), ship("C", eta=day(13))]
    payload = build_delivery_payload(evaluate_all(shipments, TODAY), TODAY)
    assert payload["counts"] == {"critical": 1, "warning": 1, "info": 1}
    assert payload["needs_attention"] == 2 and payload["today"] == "2026-11-23"
    assert [r["po_number"] for r in payload["reports"]] == ["B", "C", "A"]


def test_payload_is_json_safe():
    payload = build_delivery_payload(evaluate_all([ship("B", eta=day(17))], TODAY), TODAY)
    assert json.loads(json.dumps(payload))["reports"][0]["severity"] == "critical"


def test_input_completeness():
    full = ship("A")
    none = ship("B", criticality=None, alternative_suppliers=None)
    half = ship("C", criticality=None)
    assert input_completeness([full]) == 1.0
    assert input_completeness([none]) == 0.0
    assert input_completeness([full, half]) == 0.75
    assert input_completeness([]) == 0.0