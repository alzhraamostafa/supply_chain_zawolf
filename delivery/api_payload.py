"""Pure helpers that turn delivery reports into the API payload."""
from dataclasses import asdict
from datetime import date


def build_delivery_payload(reports, today: date) -> dict:
    counts = {"critical": 0, "warning": 0, "info": 0}
    for r in reports:
        counts[r.severity] += 1
    return {
        "today": today.isoformat(),
        "counts": counts,
        "needs_attention": counts["critical"] + counts["warning"],
        "reports": [asdict(r) for r in reports],
    }


def input_completeness(shipments) -> float:
    """Share of the optional context (criticality, alternative suppliers) that is known."""
    if not shipments:
        return 0.0
    known = sum((s.criticality is not None) + (s.alternative_suppliers is not None) for s in shipments)
    return round(known / (2 * len(shipments)), 2)