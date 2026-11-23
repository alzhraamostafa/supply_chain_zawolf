"""Pure helpers that turn risk assessments into the API payload."""
from dataclasses import asdict

from .adapter import LEVEL_ORDER

LEVELS = tuple(LEVEL_ORDER)


def build_risk_payload(assessments, unmatched_skus, level=None, limit=None) -> dict:
    if level is not None and level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    if limit is not None and not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    ordered = sorted(assessments, key=lambda a: (LEVEL_ORDER[a.level], -(a.risk_score or 0), a.material))
    counts = {lv: sum(1 for a in ordered if a.level == lv) for lv in LEVELS}
    shown = [a for a in ordered if level is None or a.level == level]
    if limit:
        shown = shown[:limit]
    return {
        "counts": counts,
        "stock_known_for": sum(1 for a in ordered if a.shortage_probability is not None),
        "assessments": [asdict(a) for a in shown],
        "unmatched_skus": list(unmatched_skus),
    }


def overall_confidence(assessments) -> float:
    scored = [a.confidence for a in assessments if a.level != "unknown"]
    return round(sum(scored) / len(scored), 2) if scored else 0.0