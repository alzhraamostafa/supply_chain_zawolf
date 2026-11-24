"""Wrap delivery reports in the shared envelope (component 'delivery_agent')."""
from contracts.envelope import OutputEnvelope


def delivery_envelope(payload: dict, confidence: float, source: list[str]) -> OutputEnvelope:
    return OutputEnvelope(
        component="delivery_agent",
        source=source,
        confidence=confidence,
        autonomy_level=0,
        requires_human_approval=True,
        assumptions=[
            "Dates are taken as given by the supplier and the production plan",
            "Unknown criticality is treated as critical (the cautious choice)",
        ],
        payload=payload,
    )