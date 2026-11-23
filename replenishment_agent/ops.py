"""New agent commands: supplier catalog scraping, RFQs, quotes, inbox, delivery tracking, alerts, watch loop.

Registered into agent.py's command line; see README.md for the full list.
"""
from __future__ import annotations
import re
from datetime import date

import quotes
import rfq
import scraper
import tracking
from db import now_utc, tx
from mailer import Mailer
from notify import Notifier

RFQ_TAG = re.compile(r"\bRFQ-\d+-\d{5}\b")
PO_TAG = re.compile(r"\bPO-\d+-\d{5}\b")


def services(ag):
    mailer = Mailer(ag.cfg.messaging)
    return mailer, Notifier(ag.con, mailer, ag.cfg.messaging)


def materials(ag):
    return sorted(ag._context()["kinds"])


# ------------------------------------------------------------------ inbox: replies to RFQs and POs
def poll_inbox(ag, mailer, notifier, llm=None) -> list[str]:
    log = []
    for m in mailer.fetch():
        if ag.con.execute("SELECT 1 FROM ext_inbox_seen WHERE message_key=?", (m["key"],)).fetchone():
            continue
        handled = "ignored"
        hay = m["subject"] + "\n" + m["text"]
        r_tag, p_tag = RFQ_TAG.search(hay), PO_TAG.search(hay)
        if r_tag:
            row = ag.con.execute("SELECT rfq_id, supplier_id FROM ext_rfqs WHERE rfq_number=?", (r_tag.group(0),)).fetchone()
            if row:
                res = quotes.ingest(ag.con, row[0], m["text"], f"email:{m['sender']}", m["date"], llm=llm)
                notifier.quote(r_tag.group(0), row[1], res["lines"])
                handled = (f"{r_tag.group(0)}: supplier DECLINED" if res["declined"] else
                           f"quote {res['quote_id']} for {r_tag.group(0)} ({res['lines']}/{res['of']} lines, {res['method']})")
        elif p_tag:
            row = ag.con.execute("SELECT purchase_order_id FROM purchase_orders WHERE po_number=?", (p_tag.group(0),)).fetchone()
            if row:
                sup = ag.con.execute("SELECT supplier_id FROM purchase_orders WHERE purchase_order_id=?", (row[0],)).fetchone()[0]
                lines = []
                for r in ag.con.execute("SELECT purchase_order_line_id, material_reference, base_unit_snapshot "
                                        "FROM purchase_order_lines WHERE purchase_order_id=?", (row[0],)).fetchall():
                    mat = r[1].removeprefix("MAT:")
                    s_name, s_code = scraper.supplier_name_for(ag.con, sup, mat)
                    lines.append(dict(purchase_order_line_id=r[0], material=mat, unit=r[2],
                                      supplier_name=s_name, supplier_code=s_code))
                st = tracking.parse_status_email(m["text"], lines)
                if st["status"]:
                    tracking.record(ag.con, row[0], st["status"], "supplier_email", at=m["date"],
                                    source=f"email:{m['sender']}", carrier=st["carrier"],
                                    tracking_number=st["tracking_number"], eta=st["eta"], shipped=st["shipped"],
                                    note=m["subject"][:200])
                    handled = f"{p_tag.group(0)} -> {st['status']}"
                else:
                    handled = f"{p_tag.group(0)}: no status recognised, left for a person"
        with tx(ag.con):
            ag.con.execute("INSERT INTO ext_inbox_seen(message_key,handled_as,seen_at_utc) VALUES (?,?,?)",
                           (m["key"], handled, now_utc()))
        log.append(f"{m['subject'][:60]!r}: {handled}")
    return log


def watch(ag, today=None, scrape=False) -> dict:
    """One cycle. Schedule it (Windows Task Scheduler / cron) e.g. every hour:
    restock alerts -> new purchase request; read the inbox; chase late / unconfirmed deliveries and RFQ replies."""
    from agent import format_report
    mailer, notifier = services(ag)
    today = today or date.today().isoformat()
    out = {}
    if scrape:
        out["scrape"] = {s: scraper.scrape_supplier(ag.con, s, cfg, materials(ag))
                         for s, cfg in ag.cfg.sites.items() if cfg.get("start_urls")}
    res = ag.run()
    out["report"] = format_report(res)
    out["restock_alerts_sent"] = notifier.restock(res)
    out["inbox"] = poll_inbox(ag, mailer, notifier)
    exc = tracking.exceptions(ag.con, ag.env_id, today, ag.cfg.messaging.get("ack_expected_days", 2))
    out["delivery_alerts_sent"] = notifier.late(exc)
    late_rfq = rfq.overdue_replies(ag.con, ag.env_id, today)
    for r in late_rfq:
        notifier.notify("rfq", f"rfq_late:{r['rfq_number']}", "warning", f"No reply to {r['rfq_number']} from "
                        f"{r['supplier_id']}", f"Reply was due {r['reply_due_date']}. Chase the supplier.")
    out["exceptions"], out["rfq_overdue"] = exc, late_rfq
    return out


# ------------------------------------------------------------------ command line
def register(sub):
    def add(name, *args):
        s = sub.add_parser(name)
        for a in args:
            flag, kw = a if isinstance(a, tuple) else (a, {})
            s.add_argument(flag, **kw)
        return s
    INT, REQ = dict(type=int, required=True), dict(required=True)
    add("scrape", ("--supplier", {}))
    add("catalog", ("--status", dict(default="candidate")))
    add("catalog-confirm", ("--id", INT), ("--by", REQ))
    add("catalog-reject", ("--id", INT), ("--by", REQ))
    add("contacts-found")
    add("names", ("--supplier", {}), ("--material", {}))
    add("name-add", ("--supplier", REQ), ("--material", REQ), ("--name", REQ), ("--code", {}), ("--by", REQ))
    add("rfq-create", ("--pr", INT))
    add("rfq-list", ("--pr", dict(type=int)))
    add("rfq-show", ("--rfq", INT))
    for n in ("rfq-approve", "rfq-send", "rfq-mark-sent"):
        add(n, ("--rfq", INT), ("--by", REQ))
    add("quote-ingest", ("--rfq", INT), ("--file", {}), ("--text", {}))
    add("quote-new", ("--rfq", INT), ("--by", REQ))
    add("quote-add-line", ("--quote", INT), ("--line", INT), ("--price", dict(type=float, required=True)),
        ("--per", dict(choices=["kg", "ton", "piece", "1000"], required=True)), ("--moq", dict(type=float)),
        ("--lead", dict(type=int)), ("--valid", {}))
    add("quote-show", ("--quote", INT))
    add("quote-confirm", ("--quote", INT), ("--by", REQ))
    add("quote-reject", ("--quote", INT), ("--by", REQ))
    add("quote-compare", ("--pr", INT))
    add("inbox")
    s = add("track", ("--po", INT), ("--status", dict(required=True, choices=tracking.CHAIN + tracking.SIDE)),
            ("--by", REQ), ("--at", {}), ("--carrier", {}), ("--tracking", {}), ("--eta", {}), ("--note", {}),
            ("--ship", dict(nargs="*", help="LINE_ID=QTY in base units (g or pcs)")))
    s.add_argument("--receive", action="store_true", help="with --status delivered: post the goods receipt")
    add("track-show", ("--po", INT), ("--today", {}))
    add("track-check", ("--today", {}))
    add("scorecard")
    s = add("watch", ("--today", {}))
    s.add_argument("--scrape", action="store_true")


def _qty(q, unit):
    return f"{q / 1000:,.1f} kg" if unit == "g" else f"{q:,} pcs"


def handle(a, ag) -> bool:
    c, cmd = ag.con, a.cmd
    actor = ag.cfg.agent_actor
    if cmd == "scrape":
        mats = materials(ag)
        for sup, site in ag.cfg.sites.items():
            if (a.supplier and sup != a.supplier) or not site.get("start_urls"):
                continue
            print(sup, scraper.scrape_supplier(c, sup, site, mats))
        if not any(s.get("start_urls") for s in ag.cfg.sites.values()):
            print("No supplier website configured: add start_urls in supplier_sites.json")
    elif cmd == "catalog":
        for r in c.execute("SELECT catalog_item_id,supplier_id,matched_material,match_score,product_name,source_url "
                           "FROM ext_catalog_items WHERE status=? ORDER BY matched_material,match_score DESC", (a.status,)):
            print(f"#{r[0]:<4} {r[1]:10} {r[2]:30} {r[3]:.2f}  {r[4][:50]:50} {r[5][:50]}")
    elif cmd in ("catalog-confirm", "catalog-reject"):
        scraper.decide(c, a.id, cmd == "catalog-confirm", a.by); print("ok")
    elif cmd == "names":
        q = ("SELECT matched_material, supplier_id, product_name, product_code, source_url FROM ext_catalog_items "
             "WHERE status='confirmed'" + (" AND supplier_id=?" if a.supplier else "") +
             (" AND matched_material=?" if a.material else "") + " ORDER BY 1, 2")
        rows = c.execute(q, tuple(v for v in (a.supplier, a.material) if v)).fetchall()
        print(f"{'our material':30} {'supplier':10} {'supplier name':36} {'their code':12} source")
        for r in rows:
            print(f"{r[0]:30} {r[1]:10} {r[2][:36]:36} {(r[3] or '-'):12} {r[4][:40]}")
        if not rows:
            print("no confirmed names yet: scrape + catalog-confirm, or name-add")
    elif cmd == "name-add":
        if a.material not in materials(ag):
            raise SystemExit(f"unknown material {a.material}")
        scraper.add_name(c, a.supplier, a.material, a.name, a.code, a.by); print("ok")
    elif cmd == "contacts-found":
        for r in c.execute("SELECT supplier_id, kind, value, source_url FROM ext_supplier_contacts_found ORDER BY 1,2"):
            print(f"{r[0]:10} {r[1]:6} {r[2]:40} (from {r[3]})")
    elif cmd == "rfq-create":
        ids = rfq.create_rfqs(c, a.pr, actor, ag.cfg.contacts, ag.cfg.aliases,
                              max_suppliers=ag.cfg.policy.get("rfq_max_suppliers_per_material", 3),
                              reply_days=ag.cfg.messaging.get("rfq_reply_days", 3), llm=ag.llm)
        print(f"draft RFQs: {ids}  (a person must approve each: rfq-approve --rfq N --by NAME)")
    elif cmd == "rfq-list":
        q = "SELECT rfq_id,rfq_number,supplier_id,channel,status,reply_due_date,(SELECT COUNT(*) FROM ext_rfq_lines l " \
            "WHERE l.rfq_id=r.rfq_id) FROM ext_rfqs r" + (" WHERE purchase_request_id=?" if a.pr else "") + " ORDER BY 1"
        for r in c.execute(q, (a.pr,) if a.pr else ()):
            print(f"#{r[0]:<3} {r[1]:16} {r[2]:10} {r[3]:8} {r[4]:9} reply by {r[5]}  {r[6]} line(s)")
    elif cmd == "rfq-show":
        r = c.execute("SELECT * FROM ext_rfqs WHERE rfq_id=?", (a.rfq,)).fetchone()
        print(f"{r['rfq_number']} to {r['supplier_id']} via {r['channel']} ({r['recipient'] or '-'}), {r['status']}\n"
              f"Subject: {r['subject']}\n\n{r['body']}\n\nLines:")
        for l in c.execute("SELECT * FROM ext_rfq_lines WHERE rfq_id=?", (a.rfq,)):
            print(f"  line {l['rfq_line_id']}: {l['material']} {_qty(l['qty_base_units'], l['unit'])} by {l['needed_by']}")
    elif cmd == "rfq-approve":
        rfq.approve_rfq(c, a.rfq, a.by); print("approved")
    elif cmd == "rfq-send":
        print(rfq.send_rfq(c, a.rfq, a.by, services(ag)[0]))
    elif cmd == "rfq-mark-sent":
        rfq.mark_sent(c, a.rfq, a.by); print("marked sent")
    elif cmd == "quote-ingest":
        text = open(a.file, encoding="utf-8").read() if a.file else a.text
        if not text:
            raise SystemExit("give --file or --text")
        print(quotes.ingest(c, a.rfq, text, "pasted", llm=ag.llm))
    elif cmd == "quote-new":
        print(quotes.ingest(c, a.rfq, "(manual entry: phone call / PDF)", "manual", actor=a.by))
    elif cmd == "quote-add-line":
        quotes.add_line(c, a.quote, a.line, a.price, a.per, a.moq, a.lead, a.valid); print("ok")
    elif cmd == "quote-show":
        q = c.execute("SELECT * FROM ext_quotes WHERE quote_id=?", (a.quote,)).fetchone()
        print(f"quote {a.quote} ({q['status']}, {q['extraction_method']}) for RFQ {q['rfq_id']}\n--- reply ---\n"
              f"{q['raw_text']}\n--- extracted ---")
        for l in c.execute("SELECT ql.*, rl.material, rl.unit FROM ext_quote_lines ql JOIN ext_rfq_lines rl "
                           "USING(rfq_line_id) WHERE quote_id=?", (a.quote,)):
            per = "kg" if l["unit"] == "g" and l["price_basis_base_units"] == 1000 else \
                  "ton" if l["price_basis_base_units"] == 1_000_000 else \
                  "1000 pcs" if l["price_basis_base_units"] == 1000 else "piece"
            print(f"  {l['material']}: EGP {l['unit_price_piastres'] / 100:,.2f} per {per}; MOQ "
                  f"{_qty(l['moq_base_units'], l['unit']) if l['moq_base_units'] else '-'}; lead {l['lead_days'] or '-'} d;"
                  f" valid {l['valid_until'] or '-'}   [{l['evidence']}]")
    elif cmd in ("quote-confirm", "quote-reject"):
        quotes.decide(c, a.quote, a.by, cmd == "quote-confirm"); print("ok")
    elif cmd == "quote-compare":
        rows = quotes.offers(c, a.pr)
        if not rows:
            print("no confirmed quotes yet")
        best = set()
        for o in rows:
            mark = "BEST" if o["purchase_request_line_id"] not in best else "    "
            best.add(o["purchase_request_line_id"])
            flags = ("" if o["meets_date"] else " LATE") + ("" if o["meets_moq"] else " BELOW-MOQ")
            print(f"{mark} {o['material'][:28]:28} {o['supplier_id']:10} {_qty(o['qty'], o['unit']):>14} "
                  f"EGP {o['total_egp']:>13,.2f}  lead {o['lead_days'] if o['lead_days'] is not None else '-':>3} d{flags}")
    elif cmd == "inbox":
        mailer, notifier = services(ag)
        for line in poll_inbox(ag, mailer, notifier, ag.llm) or ["no new messages"]:
            print(line)
    elif cmd == "track":
        ship = {int(k): int(v) for k, v in (x.split("=") for x in a.ship)} if a.ship else None
        tracking.record(c, a.po, a.status, a.by, at=a.at, carrier=a.carrier, tracking_number=a.tracking, eta=a.eta,
                        note=a.note, shipped=ship, receive_location=ag.loc_id if a.receive else None)
        print("recorded")
    elif cmd == "track-show":
        print_timeline(tracking.timeline(c, a.po, a.today))
    elif cmd == "track-check":
        today = a.today or date.today().isoformat()
        exc = tracking.exceptions(c, ag.env_id, today, ag.cfg.messaging.get("ack_expected_days", 2))
        for e in exc:
            print(f"{e['po_number']} {e['supplier_id']}: {e['reason']} - {e['detail']}")
        print(f"{len(exc)} issue(s); alerts sent: {services(ag)[1].late(exc)}")
    elif cmd == "scorecard":
        print(f"{'supplier':10} {'orders':>6} {'deliv':>5} {'confirm d':>9} {'lead d':>6} {'sd':>4} {'on time':>7} {'fill':>5}")
        for s in tracking.scorecard(c, ag.env_id):
            f = lambda v, suf="": "-" if v is None else f"{v}{suf}"
            print(f"{s['supplier_id']:10} {s['orders']:6} {s['delivered']:5} {f(s['avg_confirm_days']):>9} "
                  f"{f(s['avg_lead_days']):>6} {f(s['lead_sd']):>4} {f(s['on_time_pct'], '%'):>7} {f(s['fill_rate_pct'], '%'):>5}")
    elif cmd == "watch":
        out = watch(ag, a.today, a.scrape)
        print(out["report"])
        print(f"\nrestock alerts sent: {out['restock_alerts_sent']}   delivery alerts sent: {out['delivery_alerts_sent']}")
        for line in out["inbox"]:
            print("inbox:", line)
    else:
        return False
    return True


def print_timeline(t):
    print(f"{t['po_number']}  supplier {t['supplier_id']}  status {t['current']}  (PO {t['po_status']})")
    print(f"order by {t['order_by'] or '-'} | sent {(t['sent_at'] or '-')[:10]} | promised {t['promised'] or '-'} | "
          f"latest ETA {t['latest_eta'] or '-'} | " + ("on time" if t["days_late"] is None else
          f"{t['days_late']} day(s) late" if t["days_late"] > 0 else f"{-t['days_late']} day(s) early" if t["days_late"] < 0 else "on time"))
    print(f"carrier {t['carrier'] or '-'}  tracking {t['tracking_number'] or '-'}")
    for s in tracking.CHAIN + tracking.SIDE:
        if s in t["reached"]:
            print(f"   {s:17} {t['reached'][s][:16]}")
    d = t["days"]
    print("days: " + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in d.items() if v is not None))
    for l in t["lines"]:
        print(f"   line {l['purchase_order_line_id']}: {l['material'][:30]:30} ordered {_qty(l['ordered'], l['base_unit_snapshot']):>13}"
              f"  shipped {_qty(l['shipped'], l['base_unit_snapshot']):>13}  received {_qty(l['received'], l['base_unit_snapshot']):>13}")
