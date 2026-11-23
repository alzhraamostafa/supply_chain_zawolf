"""Wrap risk results in the shared envelope (component 'risk_engine')."""
from dataclasses import asdict

from contracts.envelope import OutputEnvelope

from .engine import RiskAssessment


def to_envelope(assessment: RiskAssessment, source: list[str]) -> OutputEnvelope:
    return OutputEnvelope(
        component="risk_engine",
        source=source,
        confidence=assessment.confidence,
        autonomy_level=0,
        requires_human_approval=True,
        assumptions=["The next delay is assumed to resemble past delays"] + assessment.unknown,
        payload=asdict(assessment),
    )


def portfolio_envelope(payload: dict, confidence: float, source: list[str]) -> OutputEnvelope:
    return OutputEnvelope(
        component="risk_engine",
        source=source,
        confidence=confidence,
        autonomy_level=0,
        requires_human_approval=True,
        assumptions=[
            "The next delay is assumed to resemble past delays",
            "Items without a stock figure get a fragility index only, not a shortage probability",
        ],
        payload=payload,
    )