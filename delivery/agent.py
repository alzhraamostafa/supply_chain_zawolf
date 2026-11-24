"""Delivery & exception agent v0.1: compares each shipment with the plan and proposes actions.
Rules only. Every proposal needs a human. 'today' is passed in, so results are reproducible."""
from dataclasses import dataclass, field
from datetime import date

SHORT_TOLERANCE = 0.02      # up to 2% short is accepted
BADLY_SHORT = 0.80          # received less than 80% of the order
CRITICAL_MATERIAL = 0.50    # share of products using the material
SEVERE_DAYS_LATE = 3        # arriving this many days after the need date is critical for any material

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Shipment:
    po_number: str
    material: str
    supplier: str
    ordered_qty: float
    promised_date: date             # what the supplier promised when the order was placed
    original_needed_by: date        # when production needed it when the order was placed
    needed_by: date                 # when production needs it now
    eta: date | None = None         # the supplier's latest estimate (None = no update)
    received_qty: float | None = None
    received_date: date | None = None
    quality_ok: bool | None = None  # None = not inspected yet
    criticality: float | None = None          # share of products using the material, None = unknown
    alternative_suppliers: int | None = None  # None = unknown


@dataclass
class Issue:
    type: str       # supplier_delay | plan_change | stockout_risk | short_delivery | quality_hold | no_update
    message: str


@dataclass
class ExceptionReport:
    po_number: str
    material: str
    supplier: str
    status: str                 # on_track | exception
    cause: str                  # none | supplier | plan | both  (what moved the timing)
    severity: str               # info | warning | critical
    slack_days: int | None      # need date minus arrival; negative = production waits
    issues: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    requires_human_approval: bool = True


def evaluate(s: Shipment, today: date) -> ExceptionReport:
    arrival = s.received_date or s.eta
    overdue_without_news = arrival is None and today > s.promised_date
    effective_arrival = today if overdue_without_news else arrival   # at least today, when nothing is known
    slack = (s.needed_by - effective_arrival).days if effective_arrival else None

    supplier_delay = max(0, (arrival - s.promised_date).days) if arrival else 0
    plan_shift = (s.needed_by - s.original_needed_by).days           # negative = needed earlier
    cause = ("both" if supplier_delay and plan_shift < 0 else
             "supplier" if supplier_delay and plan_shift >= 0 else
             "plan" if plan_shift < 0 else "none")

    critical_material = s.criticality is None or s.criticality >= CRITICAL_MATERIAL
    unknown_note = " (criticality unknown, treated as critical)" if s.criticality is None else ""
    issues: list = []
    if supplier_delay:
        issues.append(Issue("supplier_delay", f"{s.supplier} is {supplier_delay} day(s) later than promised"))
    if plan_shift:
        direction = "earlier" if plan_shift < 0 else "later"
        issues.append(Issue("plan_change", f"the factory moved the need date {abs(plan_shift)} day(s) {direction}; "
                                           "this is not a supplier delay"))
    if overdue_without_news:
        issues.append(Issue("no_update", f"promised {s.promised_date}, nothing received and no update "
                                         f"({(today - s.promised_date).days} day(s) overdue)"))
    stockout = slack is not None and slack < 0
    if stockout:
        qualifier = "at least " if overdue_without_news else ""
        issues.append(Issue("stockout_risk", f"arrives {qualifier}{-slack} day(s) after production needs it"
                                             f"{unknown_note}"))
    short_ratio = None
    if s.received_qty is not None and s.ordered_qty > 0:
        short_ratio = s.received_qty / s.ordered_qty
        if short_ratio < 1 - SHORT_TOLERANCE:
            issues.append(Issue("short_delivery", f"received {s.received_qty:g} of {s.ordered_qty:g} "
                                                  f"({short_ratio:.0%}){unknown_note}"))
    if s.quality_ok is False:
        issues.append(Issue("quality_hold", f"inspection failed{unknown_note}"))

    types = {i.type for i in issues}
    relief_only = types <= {"plan_change"} and plan_shift > 0
    thin_slack_after_plan = types == {"plan_change"} and slack is not None and slack <= 1
    if not issues or relief_only or (types == {"plan_change"} and not thin_slack_after_plan):
        severity = "info"
    elif ((stockout and (critical_material or slack <= -SEVERE_DAYS_LATE))
          or ("quality_hold" in types and critical_material)
          or (short_ratio is not None and short_ratio < BADLY_SHORT and critical_material)):
        severity = "critical"
    else:
        severity = "warning"

    actions: list = []
    if stockout:
        if cause in ("plan", "both"):
            actions.append("The need date moved earlier: expedite this order, or move the need date back if possible")
        else:
            actions.append("Expedite this order or ask the supplier for a partial shipment now")
        if s.alternative_suppliers is None:
            actions.append("Check whether an alternative supplier is available")
        elif s.alternative_suppliers >= 1:
            actions.append(f"Move part of the volume to an alternative supplier ({s.alternative_suppliers} on file)")
        else:
            actions.append("No alternative supplier on file: start sourcing one")
        actions.append(f"Adjust the production plan: schedule products that do not use {s.material} first")
    elif supplier_delay:
        actions.append(f"Ask {s.supplier} to confirm the new date and the reason (slack is {slack} day(s))")
    if overdue_without_news:
        actions.append("Ask the supplier for a status update today")
    if "short_delivery" in types:
        missing = s.ordered_qty - s.received_qty
        actions.append(f"Request the missing {missing:g} units or reissue the order for the balance")
    if "quality_hold" in types:
        actions.append("Hold the lot, notify quality, and request a replacement from the supplier")
    actions = list(dict.fromkeys(actions))[:4]

    return ExceptionReport(s.po_number, s.material, s.supplier,
                           "on_track" if severity == "info" else "exception",
                           cause, severity, slack, issues, actions)


def evaluate_all(shipments, today: date) -> list[ExceptionReport]:
    """Most severe first, then the smallest slack."""
    reports = [evaluate(s, today) for s in shipments]
    return sorted(reports, key=lambda r: (_SEVERITY_ORDER[r.severity],
                                          r.slack_days if r.slack_days is not None else 10**6, r.po_number))