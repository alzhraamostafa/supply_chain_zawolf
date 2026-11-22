from risk.engine import Delivery, SupplyHistory, assess
from risk.envelope import to_envelope


def test_assessment_fits_the_envelope():
    a = assess(SupplyHistory("Glycerin", [Delivery(8, 8)] * 20, 1, 0.9, cover_days=12))
    env = to_envelope(a, source=["fact_procurement_rfq"])
    assert env.component == "risk_engine"
    assert env.requires_human_approval is True and env.autonomy_level == 0
    assert env.payload["level"] == a.level
    assert env.confidence == a.confidence