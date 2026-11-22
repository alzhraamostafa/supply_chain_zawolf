"""Wrap a RiskAssessment in the shared envelope (component 'risk_engine')."""
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