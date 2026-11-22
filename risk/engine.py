"""Supply risk engine v0.1: transparent and rule-based, every number can be traced.

Two measures:
  shortage_probability  chance the next order arrives after the stock runs out. Needs stock cover.
                        It is the share of past deliveries whose delay was longer than the buffer
                        (cover minus lead time), lightly smoothed. No cover figure -> None (never guessed).
  risk_score            0-1 index of how fragile the supply is (late deliveries, single source, quality).
                        Always available. It is an index, not a probability."""
from dataclasses import dataclass, field

STRUCTURAL_WEIGHTS = {
    "late_rate": 0.40,      # share of past deliveries that arrived late
    "delay_size": 0.20,     # how late, relative to the contracted lead time
    "single_source": 0.27,  # only one supplier for this material
    "quality_gap": 0.13,    # supplier yield below 99%
}

ALERT_THRESHOLD = 0.30      # at or above this, a human should look
HIGH_THRESHOLD = 0.60
CRITICAL_MATERIAL = 0.50    # share of products that use the material
MIN_DELIVERIES_FOR_FULL_CONFIDENCE = 20


@dataclass(frozen=True)
class Delivery:
    contracted_days: float
    actual_days: float
    yield_rate: float = 1.0


@dataclass(frozen=True)
class SupplyHistory:
    material: str
    deliveries: list
    n_suppliers: int
    criticality: float = 0.0            # share of products using this material, 0-1
    cover_days: float | None = None     # days of supply (on hand + open orders). None = UNKNOWN, not zero


@dataclass
class Factor:
    name: str
    score: float
    weight: float
    contribution: float
    note: str


@dataclass
class RiskAssessment:
    material: str
    level: str                          # low | medium | high | critical | unknown
    shortage_probability: float | None
    risk_score: float | None
    confidence: float
    summary: str = ""
    factors: list = field(default_factory=list)
    unknown: list = field(default_factory=list)
    actions: list = field(default_factory=list)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _lead(h: SupplyHistory) -> float:
    return max(1.0, sum(x.contracted_days for x in h.deliveries) / len(h.deliveries))


def shortage_probability(h: SupplyHistory) -> float | None:
    """P(delay of the next order > buffer), estimated from past delays. Needs the stock cover."""
    if h.cover_days is None or not h.deliveries:
        return None
    buffer = h.cover_days - _lead(h)
    if buffer < 0:
        return 1.0                      # stock ends before even an on-time order could arrive
    k = sum(1 for x in h.deliveries if (x.actual_days - x.contracted_days) > buffer)
    return (k + 0.5) / (len(h.deliveries) + 1)


def structural_factors(h: SupplyHistory, weights: dict | None = None) -> list:
    weights = weights or STRUCTURAL_WEIGHTS
    d = h.deliveries
    n = len(d)
    late = [x for x in d if x.actual_days > x.contracted_days]
    mean_delay_ratio = sum(max(0.0, x.actual_days - x.contracted_days) / max(1.0, x.contracted_days) for x in d) / n
    mean_yield = sum(x.yield_rate for x in d) / n
    raw = {
        "late_rate": (_clip(len(late) / n / 0.30), f"{len(late)} of {n} deliveries were late"),
        "delay_size": (_clip(mean_delay_ratio / 0.25), f"average delay is {mean_delay_ratio:.0%} of the lead time"),
        "single_source": (1.0 if h.n_suppliers <= 1 else (0.4 if h.n_suppliers == 2 else 0.0),
                          f"{h.n_suppliers} supplier(s) on file"),
        "quality_gap": (_clip((0.99 - mean_yield) / 0.02), f"average yield {mean_yield:.1%}"),
    }
    total = sum(weights[k] for k in raw)
    factors = [Factor(k, s, weights[k] / total, s * weights[k] / total, note) for k, (s, note) in raw.items()]
    return sorted(factors, key=lambda f: f.contribution, reverse=True)


def _level(basis: float, criticality: float) -> str:
    critical_material = criticality >= CRITICAL_MATERIAL
    if basis >= HIGH_THRESHOLD and critical_material:
        return "critical"
    if basis >= HIGH_THRESHOLD or (basis >= ALERT_THRESHOLD and critical_material):
        return "high"
    if basis >= ALERT_THRESHOLD:
        return "medium"
    return "low"


_ACTIONS = {
    "single_source": "Qualify a second supplier for this material",
    "late_rate": "Ask the supplier for a delivery plan and add buffer to the lead time",
    "delay_size": "Add buffer to the planned lead time for this supplier",
    "quality_gap": "Request a quality review of the supplier's recent deliveries",
}


def assess(h: SupplyHistory, weights: dict | None = None) -> RiskAssessment:
    if not h.deliveries:
        return RiskAssessment(h.material, "unknown", None, None, 0.0,
                              summary="No delivery history, so the risk cannot be assessed.",
                              unknown=["no delivery history"],
                              actions=["Collect delivery history or source this material"])
    factors = structural_factors(h, weights)
    score = round(sum(f.contribution for f in factors), 3)
    prob = shortage_probability(h)
    unknown = [] if prob is not None else ["stock on hand is unknown, so the shortage probability is not computed"]
    basis = prob if prob is not None else score
    level = _level(basis, h.criticality)
    n = len(h.deliveries)
    confidence = round((1.0 if prob is not None else 0.6) * min(1.0, n / MIN_DELIVERIES_FOR_FULL_CONFIDENCE), 2)

    actions = []
    if prob is not None and h.cover_days - _lead(h) < 0:
        actions.append("Expedite an order now or raise safety stock: stock ends before a new order can arrive")
    elif prob is not None and prob >= ALERT_THRESHOLD:
        actions.append("Place the next order earlier or raise safety stock (buffer is thinner than past delays)")
    actions += [_ACTIONS[f.name] for f in factors if f.score >= 0.5]
    actions = actions[:3] if level != "low" else []

    if prob is not None:
        buffer = h.cover_days - _lead(h)
        summary = (f"{h.cover_days:.1f} days of supply against a {_lead(h):.1f}-day lead time "
                   f"(buffer {buffer:+.1f} days). Shortage probability {prob:.0%} "
                   f"based on {n} past deliveries.")
    else:
        summary = f"Supply fragility index {score:.2f} based on {n} past deliveries. Stock level unknown."
    return RiskAssessment(h.material, level, None if prob is None else round(prob, 3), score, confidence,
                          summary, factors, unknown, actions)