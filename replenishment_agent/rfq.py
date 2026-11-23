"""Requests for quotation (RFQ): the supplier websites show no prices, so we ask.

Flow:  purchase request (draft or approved)
         -> create_rfqs: one RFQ per supplier who can supply the material
              (suppliers from purchase history + website matches a person confirmed)
         -> approve_rfq  (a person, not the agent: maker != checker)
         -> send_rfq     (email, or a prepared text for a website form / phone, see suppliers_contacts.json)
         -> replies are read by quotes.py
An RFQ asks for prices; it does not commit us to buy.
"""
from __future__ import annotations
import json
from datetime import date, timedelta

import drafter
import scraper
from db import now_utc, tx

OPEN = ("draft", "approved", "sent", "quoted")


class RFQError(Exception):
    pass


def _event(con, rfq_id, actor, status, reason):
    con.execute("INSERT INTO ext_rfq_events(rfq_id,event_at_utc,actor,new_status,reason) VALUES (?,?,?,?,?)",
                (rfq_id, now_utc(), actor, status, reason))


def candidate_suppliers(con, material: str, aliases: dict, limit: int) -> list[str]:
    """History suppliers first (best quality rating first), then suppliers found on the web and confirmed."""
    hist = [r[0] for r in con.execute(
        "SELECT r.supplier_id, MAX(s.quality_rating) q FROM procurement_rfq_history r JOIN suppliers s USING(supplier_id) "
        "WHERE r.material_sku_code IN (SELECT ? UNION SELECT key FROM json_each(?) WHERE value=?) "
        "GROUP BY r.supplier_id ORDER BY q DESC", (material, json.dumps(aliases), material))]
    out = list(hist)
    for s in scraper.suppliers_offering(con, material):
        if s not in out:
            out.append(s)
    return out[:limit]


def create_rfqs(con, pr_id: int, actor: str, contacts: dict, aliases: dict, *, max_suppliers=3,
                reply_days=3, llm=None) -> list[int]:
    pr = con.execute("SELECT * FROM purchase_requests WHERE purchase_request_id=?", (pr_id,)).fetchone()
    if pr is None:
        raise RFQError("purchase request not found")
    if pr["status"] == "rejected":
        raise RFQError("purchase request was rejected")
    lines = con.execute("""SELECT l.purchase_request_line_id, l.stock_item_id, l.requested_quantity_base_units qty,
                                  l.quantity_policy_json, s.item_name material, s.base_unit unit
                           FROM purchase_request_lines l JOIN stock_items s USING(stock_item_id)
                           WHERE l.purchase_request_id=?""", (pr_id,)).fetchall()
    by_supplier: dict[str, list] = {}
    for ln in lines:
        pol = json.loads(ln["quantity_policy_json"])
        as_of = pol.get("as_of") or date.today().isoformat()
        needed_by = (date.fromisoformat(as_of) + timedelta(days=int(pol.get("lead_days") or 0))).isoformat()
        for sup in candidate_suppliers(con, ln["material"], aliases, max_suppliers):
            by_supplier.setdefault(sup, []).append(dict(ln=ln, needed_by=needed_by))
    names = {r[0]: r[1] for r in con.execute("SELECT supplier_id, supplier_name FROM suppliers")}
    created = []
    for sup, items in by_supplier.items():
        exists = con.execute(f"SELECT 1 FROM ext_rfqs WHERE purchase_request_id=? AND supplier_id=? "
                             f"AND status IN ({','.join('?' * len(OPEN))})", (pr_id, sup, *OPEN)).fetchone()
        if exists:
            continue
        c = contacts.get(sup, {})
        channel = c.get("rfq_channel") or ("email" if c.get("email") else "manual")
        if channel == "email" and not c.get("email"):
            channel = "manual"
        recipient = c.get("email") if channel == "email" else (c.get("form_url") or c.get("website") or c.get("phone"))
        lang = c.get("language", "en")
        n = con.execute("SELECT COALESCE(MAX(rfq_id),0)+1 FROM ext_rfqs").fetchone()[0]
        number = f"RFQ-{pr['environment_id']}-{n:05d}"
        for i in items:      # the supplier's own name/code for the item, so they recognise it and reply with it
            i["s_name"], i["s_code"] = scraper.supplier_name_for(con, sup, i["ln"]["material"])
        msg_lines = [dict(material=i["ln"]["material"], qty=i["ln"]["qty"], unit=i["ln"]["unit"],
                          needed_by=i["needed_by"], supplier_name=i["s_name"], supplier_code=i["s_code"])
                     for i in items]
        subject, body, source = drafter.rfq_message(names.get(sup, sup).split(" (")[0], number, msg_lines, lang, llm)
        with tx(con):
            cur = con.execute("INSERT INTO ext_rfqs(rfq_number,environment_id,purchase_request_id,supplier_id,channel,"
                              "recipient,language,subject,body,body_source,status,created_by,created_at_utc,reply_due_date)"
                              " VALUES (?,?,?,?,?,?,?,?,?,?,'draft',?,?,?)",
                              (number, pr["environment_id"], pr_id, sup, channel, recipient, lang, subject, body, source,
                               actor, now_utc(), (date.today() + timedelta(days=reply_days)).isoformat()))
            rid = cur.lastrowid
            for i in items:
                con.execute("INSERT INTO ext_rfq_lines(rfq_id,purchase_request_line_id,stock_item_id,material,unit,"
                            "qty_base_units,needed_by,supplier_product_name,supplier_product_code) VALUES (?,?,?,?,?,?,?,?,?)",
                            (rid, i["ln"]["purchase_request_line_id"], i["ln"]["stock_item_id"], i["ln"]["material"],
                             i["ln"]["unit"], i["ln"]["qty"], i["needed_by"], i["s_name"], i["s_code"]))
            _event(con, rid, actor, "draft", f"drafted from {pr['request_number']}")
        created.append(rid)
    return created


def _get(con, rfq_id):
    r = con.execute("SELECT * FROM ext_rfqs WHERE rfq_id=?", (rfq_id,)).fetchone()
    if r is None:
        raise RFQError("RFQ not found")
    return r


def approve_rfq(con, rfq_id, by, note="approved to send"):
    r = _get(con, rfq_id)
    if r["status"] != "draft":
        raise RFQError(f"RFQ is {r['status']}; only a draft can be approved")
    if by == r["created_by"]:
        raise RFQError("maker and checker must be different people")
    with tx(con):
        con.execute("UPDATE ext_rfqs SET status='approved' WHERE rfq_id=?", (rfq_id,))
        _event(con, rfq_id, by, "approved", note)


def send_rfq(con, rfq_id, by, mailer) -> str:
    """Email channel: sent (or dry run). Other channels: text saved for a person, who then runs mark_sent."""
    r = _get(con, rfq_id)
    if r["status"] != "approved":
        raise RFQError(f"RFQ is {r['status']}; it must be approved before sending")
    if r["channel"] == "email":
        st = mailer.send_email(con, "rfq", r["rfq_number"], r["recipient"], r["subject"], r["body"])
        if st == "failed":
            raise RFQError("email failed; see ext_outbox.error")
        with tx(con):
            con.execute("UPDATE ext_rfqs SET status='sent' WHERE rfq_id=?", (rfq_id,))
            _event(con, rfq_id, by, "sent", "email sent" if st == "sent" else "DRY RUN: email written to outbox only")
        return st
    path = mailer.save_manual(con, "rfq", r["rfq_number"], r["recipient"], r["subject"], r["body"])
    return f"manual: submit the text in {path} at {r['recipient'] or 'the supplier website'}, then run: rfq-mark-sent --rfq {rfq_id} --by NAME"


def mark_sent(con, rfq_id, by, note="submitted manually on the supplier website / by phone"):
    r = _get(con, rfq_id)
    if r["status"] != "approved":
        raise RFQError(f"RFQ is {r['status']}; it must be approved")
    with tx(con):
        con.execute("UPDATE ext_rfqs SET status='sent' WHERE rfq_id=?", (rfq_id,))
        _event(con, rfq_id, by, "sent", note)


def set_status(con, rfq_id, status, by, reason):
    with tx(con):
        con.execute("UPDATE ext_rfqs SET status=? WHERE rfq_id=?", (status, rfq_id))
        _event(con, rfq_id, by, status, reason)


def overdue_replies(con, env_id, today: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT rfq_number, supplier_id, reply_due_date FROM ext_rfqs WHERE environment_id=? AND status='sent' "
        "AND reply_due_date < ?", (env_id, today))]
