"""Delivery tracking for purchase orders.

Status chain (a supplier may skip steps):
    sent -> acknowledged -> in_production -> shipped -> in_transit -> out_for_delivery -> delivered
    side states: delayed, exception
Updates come from
    - the supplier's emails (parse_status_email, routed by the [PO-...] tag in the subject)
    - a carrier tracking API (CarrierAdapter; configure in messaging.json -> carriers)
    - a person (agent.py track ...)
'shipped' records WHAT was shipped (quantity per PO line). 'delivered' can post the goods receipt, which raises stock.
From the events we measure: time to confirm, time to ship, transit time, total lead time, days late,
shipped vs ordered vs received, and a supplier scorecard. Observed lead times can replace the RFQ-history
lead times in the reorder calculation (policy.json: use_observed_lead_times).
"""
from __future__ import annotations
import json, re, statistics
from datetime import date, datetime

import workflow as wf
from db import now_utc, tx

CHAIN = ["sent", "acknowledged", "in_production", "shipped", "in_transit", "out_for_delivery", "delivered"]
SIDE = ["delayed", "exception"]
CARRIERS = ["Aramex", "DHL", "FedEx", "UPS", "Bosta", "Egypt Post", "SMSA", "J&T", "Mylerz", "R2S"]


class TrackingError(Exception):
    pass


def _ts(at) -> str:
    if at is None:
        return now_utc()
    s = str(at)
    return s + "T12:00:00Z" if len(s) == 10 else s


def _day(ts: str) -> date:
    return date.fromisoformat(ts[:10])


def _days(a, b):
    return None if a is None or b is None else (_day(b) - _day(a)).days


def fmt_qty(q, unit):
    return f"{q / 1000:,.1f} kg" if unit == "g" else f"{q:,} pcs"


def _po(con, po_id):
    po = con.execute("SELECT * FROM purchase_orders WHERE purchase_order_id=?", (po_id,)).fetchone()
    if po is None:
        raise TrackingError("purchase order not found")
    return po


def shipped_so_far(con, po_id) -> dict:
    return {r[0]: r[1] for r in con.execute(
        "SELECT sl.purchase_order_line_id, SUM(sl.qty_base_units) FROM ext_shipment_lines sl "
        "JOIN ext_shipment_events e USING(event_id) WHERE e.purchase_order_id=? GROUP BY 1", (po_id,))}


def received_so_far(con, po_id) -> dict:
    return {r[0]: r[1] for r in con.execute(
        "SELECT l.purchase_order_line_id, COALESCE(SUM(g.accepted_quantity_base_units),0) FROM purchase_order_lines l "
        "LEFT JOIN goods_receipt_lines g USING(purchase_order_line_id) WHERE l.purchase_order_id=? GROUP BY 1", (po_id,))}


def record(con, po_id, status, actor, at=None, source="manual", carrier=None, tracking_number=None, eta=None,
           note=None, shipped: dict | None = None, receive_location=None) -> int:
    """shipped = {po_line_id: qty}; for 'shipped' the default is everything not shipped yet.
    receive_location: with status 'delivered', also posts a goods receipt of the shipped quantity."""
    if status not in CHAIN + SIDE:
        raise TrackingError(f"unknown status {status}; use one of {CHAIN + SIDE}")
    po = _po(con, po_id)
    if po["status"] in ("draft", "approved", "cancelled") and status != "sent":
        raise TrackingError(f"purchase order is {po['status']}; it must be sent before it can be tracked")
    lines = {r["purchase_order_line_id"]: r for r in
             con.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id=?", (po_id,))}
    ship_plan = {}
    if status == "shipped":
        done = shipped_so_far(con, po_id)
        if shipped:
            bad = [k for k in shipped if k not in lines]
            if bad:
                raise TrackingError(f"lines {bad} are not on {po['po_number']}")
            ship_plan = {k: int(v) for k, v in shipped.items()}
        else:
            ship_plan = {k: l["quantity_base_units"] - done.get(k, 0) for k, l in lines.items()
                         if l["quantity_base_units"] - done.get(k, 0) > 0}
    with tx(con):
        cur = con.execute("INSERT INTO ext_shipment_events(purchase_order_id,status,event_at_utc,recorded_at_utc,actor,"
                          "source,carrier,tracking_number,eta_date,note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (po_id, status, _ts(at), now_utc(), actor, source, carrier, tracking_number, eta, note))
        ev = cur.lastrowid
        for line_id, qty in ship_plan.items():
            con.execute("INSERT INTO ext_shipment_lines(event_id,purchase_order_line_id,qty_base_units) VALUES (?,?,?)",
                        (ev, line_id, qty))
    if status == "delivered" and receive_location is not None and po["status"] in ("sent", "partially_received"):
        sh, rc = shipped_so_far(con, po_id), received_so_far(con, po_id)
        accepted = {k: sh[k] - rc.get(k, 0) for k in sh if sh[k] - rc.get(k, 0) > 0} if sh else None
        if accepted is None or accepted:
            wf.receive_purchase_order(con, po_id, receive_location, actor, accepted=accepted,
                                      delivery_ref=tracking_number or f"DELIVERY-EV{ev}")
    return ev


# ------------------------------------------------------------------ reading the history
def timeline(con, po_id, today: str | None = None) -> dict:
    po = _po(con, po_id)
    ev = [dict(r) for r in con.execute("SELECT * FROM ext_shipment_events WHERE purchase_order_id=? "
                                       "ORDER BY event_at_utc, event_id", (po_id,))]
    first = {}
    for e in ev:
        first.setdefault(e["status"], e["event_at_utc"])
    if "sent" not in first:
        r = con.execute("SELECT event_at_utc FROM purchase_order_events WHERE purchase_order_id=? AND new_status='sent' "
                        "ORDER BY event_id LIMIT 1", (po_id,)).fetchone()
        if r:
            first["sent"] = r[0]
    lines = [dict(r) for r in con.execute("SELECT purchase_order_line_id, material_reference, quantity_base_units, "
                                          "base_unit_snapshot, expected_delivery_date FROM purchase_order_lines "
                                          "WHERE purchase_order_id=?", (po_id,))]
    promised = max((l["expected_delivery_date"] for l in lines if l["expected_delivery_date"]), default=None)
    etas = [e["eta_date"] for e in ev if e["eta_date"]]
    sh, rc = shipped_so_far(con, po_id), received_so_far(con, po_id)
    for l in lines:
        l["material"] = l.pop("material_reference").removeprefix("MAT:")
        l["ordered"] = l.pop("quantity_base_units")
        l["shipped"] = sh.get(l["purchase_order_line_id"], 0)
        l["received"] = rc.get(l["purchase_order_line_id"], 0)
    delivered = first.get("delivered")
    today = today or date.today().isoformat()
    order_by = _order_by(con, po)
    current = next((e["status"] for e in reversed(ev)), "sent" if "sent" in first else po["status"])
    late = None
    if promised:
        late = _days(promised, delivered) if delivered else max(0, _days(promised, today))
    return dict(
        po_number=po["po_number"], supplier_id=po["supplier_id"], po_status=po["status"], current=current,
        order_by=order_by, sent_at=first.get("sent"), promised=promised, latest_eta=etas[-1] if etas else None,
        reached={s: first[s] for s in CHAIN + SIDE if s in first},
        days=dict(order_by_to_sent=_days(order_by, first.get("sent")),
                  sent_to_acknowledged=_days(first.get("sent"), first.get("acknowledged")),
                  sent_to_shipped=_days(first.get("sent"), first.get("shipped")),
                  shipped_to_delivered=_days(first.get("shipped"), delivered),
                  total_lead_time=_days(first.get("sent"), delivered)),
        days_late=late, carrier=next((e["carrier"] for e in reversed(ev) if e["carrier"]), None),
        tracking_number=next((e["tracking_number"] for e in reversed(ev) if e["tracking_number"]), None),
        lines=lines, events=ev)


def _order_by(con, po):
    """The 'order by' date the agent gave when it raised the alert (earliest over the PO's materials)."""
    if not po["recommendation_id"]:
        return None
    r = con.execute("SELECT proposal_json FROM recommendations WHERE recommendation_id=?",
                    (po["recommendation_id"],)).fetchone()
    mats = {r2[0] for r2 in con.execute("SELECT stock_item_id FROM purchase_order_lines WHERE purchase_order_id=?",
                                        (po["purchase_order_id"],))}
    dates = [l["order_by"] for l in json.loads(r[0]).get("lines", []) if l.get("stock_item_id") in mats and l.get("order_by")]
    return min(dates) if dates else None


def open_orders(con, env_id):
    return [r[0] for r in con.execute("SELECT purchase_order_id FROM purchase_orders WHERE environment_id=? "
                                      "AND status IN ('sent','partially_received') ORDER BY purchase_order_id", (env_id,))]


def exceptions(con, env_id, today: str, ack_days: int = 2) -> list[dict]:
    """Everything a buyer should chase: late, unconfirmed, ETA moved, short shipment, delivered not received."""
    out = []
    for po_id in open_orders(con, env_id):
        t = timeline(con, po_id, today)
        base = dict(po_number=t["po_number"], supplier_id=t["supplier_id"], days_late=t["days_late"] or 0)
        if "delivered" not in t["reached"] and t["promised"] and today > t["promised"]:
            out.append(dict(base, reason="late",
                            detail=f"Promised {t['promised']}, now {t['current']}, {t['days_late']} day(s) late. "
                                   f"Tracking: {t['carrier'] or '-'} {t['tracking_number'] or ''}"))
        if t["sent_at"] and not (set(t["reached"]) - {"sent"}) and _days(t["sent_at"], today) > ack_days:
            out.append(dict(base, reason="not confirmed",
                            detail=f"Sent {t['sent_at'][:10]}; no confirmation from the supplier after "
                                   f"{_days(t['sent_at'], today)} days."))
        if t["latest_eta"] and t["promised"] and t["latest_eta"] > t["promised"]:
            out.append(dict(base, reason="ETA moved",
                            detail=f"Supplier now says {t['latest_eta']} (promised {t['promised']})."))
        if "shipped" in t["reached"]:
            short = [l for l in t["lines"] if l["shipped"] < l["ordered"]]
            if short:
                out.append(dict(base, reason="short shipment", detail="; ".join(
                    f"{l['material']}: shipped {fmt_qty(l['shipped'], l['base_unit_snapshot'])} of "
                    f"{fmt_qty(l['ordered'], l['base_unit_snapshot'])}" for l in short)))
        if "delivered" in t["reached"] and any(l["received"] < l["shipped"] for l in t["lines"]):
            out.append(dict(base, reason="delivered, not received",
                            detail="Carrier/supplier says delivered but the warehouse has not posted the goods receipt."))
    return out


def observed_lead_times(con, env_id) -> dict:
    """{(supplier_id, material): [total lead days, ...]} from delivered orders."""
    out = {}
    for po_id, in con.execute("SELECT DISTINCT purchase_order_id FROM ext_shipment_events e JOIN purchase_orders p "
                              "USING(purchase_order_id) WHERE p.environment_id=? AND e.status='delivered'", (env_id,)):
        t = timeline(con, po_id)
        if t["days"]["total_lead_time"] is None:
            continue
        for l in t["lines"]:
            out.setdefault((t["supplier_id"], l["material"]), []).append(t["days"]["total_lead_time"])
    return out


def scorecard(con, env_id) -> list[dict]:
    rows = {}
    for po_id, in con.execute("SELECT purchase_order_id FROM purchase_orders WHERE environment_id=? AND status IN "
                              "('sent','partially_received','received') AND purchase_order_id IN "
                              "(SELECT purchase_order_id FROM ext_shipment_events)", (env_id,)):   # tracked orders only
        t = timeline(con, po_id)
        s = rows.setdefault(t["supplier_id"], dict(supplier_id=t["supplier_id"], orders=0, delivered=0, lead=[],
                                                   on_time=0, ordered=0, received=0, ack=[]))
        s["orders"] += 1
        if t["days"]["sent_to_acknowledged"] is not None:
            s["ack"].append(t["days"]["sent_to_acknowledged"])
        if "delivered" in t["reached"]:
            s["delivered"] += 1
            if t["days"]["total_lead_time"] is not None:
                s["lead"].append(t["days"]["total_lead_time"])
            s["on_time"] += (t["days_late"] or 0) <= 0
        s["ordered"] += sum(l["ordered"] for l in t["lines"])
        s["received"] += sum(l["received"] for l in t["lines"])
    out = []
    for s in rows.values():
        out.append(dict(supplier_id=s["supplier_id"], orders=s["orders"], delivered=s["delivered"],
                        avg_confirm_days=round(statistics.mean(s["ack"]), 1) if s["ack"] else None,
                        avg_lead_days=round(statistics.mean(s["lead"]), 1) if s["lead"] else None,
                        lead_sd=round(statistics.pstdev(s["lead"]), 1) if len(s["lead"]) > 1 else None,
                        on_time_pct=round(100 * s["on_time"] / s["delivered"]) if s["delivered"] else None,
                        fill_rate_pct=round(100 * s["received"] / s["ordered"]) if s["ordered"] else None))
    return out


# ------------------------------------------------------------------ supplier / carrier messages
STATUS_WORDS = [  # most advanced first: "shipped ... will be delivered" is 'shipped', not 'delivered'
    ("delivered", r"\bhas been delivered|\bwas delivered|\bdelivered (?:to|at|today|on)|تم التسليم|تم التوصيل|تم تسليم"),
    ("out_for_delivery", r"out for delivery|خرج?ت? للتسليم|خرجت للتوصيل|جاري التوصيل|مع المندوب"),
    ("in_transit", r"in transit|on the way|في الطريق"),
    ("shipped", r"\bshipped\b|\bdispatched\b|has left our|تم الشحن|تم شحن|تم إرسال الشحنة"),
    ("delayed", r"\bdelay|\bpostpone|تأخير|تأجيل|سيتأخر"),
    ("in_production", r"in production|being produced|under production|تحت التصنيع|قيد التصنيع|جاري التصنيع"),
    ("acknowledged", r"confirm(?:ed|ing)? (?:receipt|your order|the order)|order (?:is )?confirmed|acknowledge|"
                     r"تم استلام أمر|نؤكد استلام|تأكيد استلام"),
]
TRACK = re.compile(r"(?:tracking|awb|waybill|رقم التتبع|رقم الشحنة|بوليصة)\s*(?:no\.?|number|#|رقم)?\s*[:#]?\s*"
                   r"([A-Z0-9][A-Z0-9-]{5,})", re.I)
ETA = re.compile(r"(?:eta|expected|arriv\w*|deliver\w* (?:on|by)|موعد الوصول|الوصول المتوقع|يصل)\D{0,20}"
                 r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})", re.I)


def parse_status_email(text: str, po_lines: list | None = None) -> dict:
    t = text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    status = next((s for s, pat in STATUS_WORDS if re.search(pat, t, re.I)), None)
    m = TRACK.search(t)
    e = ETA.search(t)
    eta = None
    if e:
        v = e.group(1)
        if "/" in v:
            d, mo, y = v.split("/")
            v = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        eta = v
    carrier = next((c for c in CARRIERS if re.search(re.escape(c), t, re.I)), None)
    shipped = {}
    if status == "shipped" and po_lines:              # "Sodium_Chloride: 800 kg" -> what was put on the truck
        import scraper
        for raw in t.splitlines():
            q = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(kg|ton|tons|pcs|pieces|كجم|طن|قطعة)", raw, re.I)
            if not q:
                continue
            score = lambda l: scraper.name_score(raw, l["material"], l.get("supplier_name"), l.get("supplier_code"))
            best = max(po_lines, key=score)
            if score(best) >= 0.6:
                v, u = float(q.group(1).replace(",", "")), q.group(2).lower()
                mult = 1_000_000 if u in ("ton", "tons", "طن") else 1000 if u in ("kg", "كجم") else 1
                shipped[best["purchase_order_line_id"]] = int(v * (mult if best["unit"] == "g" else 1))
    return dict(status=status, tracking_number=m.group(1) if m else None, carrier=carrier, eta=eta,
                shipped=shipped or None)


class CarrierAdapter:
    """Implement status(tracking_number) -> list of dict(status, at, eta, note) for a carrier's tracking API."""
    name = "base"

    def status(self, tracking_number: str) -> list[dict]:   # pragma: no cover
        raise NotImplementedError


class GenericJsonCarrier(CarrierAdapter):              # pragma: no cover (needs a real API)
    """messaging.json -> carriers -> {"Bosta": {"url": "https://.../track/{tracking}", "token_env": "...",
    "events_path": "data.events", "status_field": "state", "time_field": "timestamp",
    "status_map": {"DELIVERED": "delivered", "OUT_FOR_DELIVERY": "out_for_delivery", ...}}}"""

    def __init__(self, name, cfg):
        self.name, self.cfg = name, cfg

    def status(self, tracking_number):
        import os, requests
        headers = {}
        if self.cfg.get("token_env"):
            headers["Authorization"] = f"Bearer {os.environ.get(self.cfg['token_env'], '')}"
        data = requests.get(self.cfg["url"].format(tracking=tracking_number), headers=headers, timeout=20).json()
        for part in self.cfg.get("events_path", "").split("."):
            data = data.get(part, []) if part else data
        out = []
        for e in data:
            st = self.cfg["status_map"].get(str(e.get(self.cfg["status_field"])))
            if st:
                out.append(dict(status=st, at=e.get(self.cfg.get("time_field")), eta=None, note=self.name))
        return out


def refresh_from_carriers(con, env_id, carriers_cfg: dict, actor="carrier_api") -> int:   # pragma: no cover
    n = 0
    for po_id in open_orders(con, env_id):
        t = timeline(con, po_id)
        cfg = carriers_cfg.get(t["carrier"] or "")
        if not cfg or not t["tracking_number"]:
            continue
        have = {(e["status"], e["event_at_utc"]) for e in t["events"]}
        for e in GenericJsonCarrier(t["carrier"], cfg).status(t["tracking_number"]):
            if (e["status"], _ts(e["at"])) not in have:
                record(con, po_id, e["status"], actor, at=e["at"], source="carrier_api", carrier=t["carrier"],
                       tracking_number=t["tracking_number"], note=e.get("note"))
                n += 1
    return n
