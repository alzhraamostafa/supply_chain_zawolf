"""Demo of the sourcing -> RFQ -> quote -> PO -> delivery tracking flow, on a TEMPORARY COPY of the database.

  python run_procurement_demo.py --db smart_supply_chain_simulation_v5_recovered_review1.db

Everything is offline: supplier websites are the invented pages in demo/sites, supplier replies and shipping
notices are generated .eml files, messaging is in dry-run mode (outgoing mail is written to a temp outbox).
"""
import argparse, hashlib, os, shutil, sys, tempfile
from datetime import date, timedelta
from email.message import EmailMessage
from pathlib import Path

import ops
import quotes
import rfq
import tracking
import workflow as wf
from agent import ReplenishmentAgent
from config import Config

HERE = Path(__file__).resolve().parent


def step(n, text):
    print(f"\n{'=' * 78}\nSTEP {n}: {text}\n{'=' * 78}")


def h(s, mod):
    return int(hashlib.md5(s.encode()).hexdigest(), 16) % mod


def drop_mail(inbox, name, subject, body, sender, when):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "procurement@demo.invalid", subject
    m["Date"] = when.strftime("%a, %d %b %Y 10:00:00 +0000")
    m.set_content(body)
    os.makedirs(inbox, exist_ok=True)
    (Path(inbox) / f"{name}.eml").write_bytes(bytes(m))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    tmp = tempfile.mkdtemp()
    work = os.path.join(tmp, "work.db")
    shutil.copy(a.db, work)
    sites = {
        "SUP-EG-07": dict(start_urls=[(HERE / "demo/sites/sup-eg-07.html").as_uri()], item_selector="div.product",
                          name_selector=".title", code_selector=".sku", next_selector="a.next", max_pages=5),
        "SUP-EG-01": dict(start_urls=[(HERE / "demo/sites/sup-eg-01.html").as_uri()]),     # generic extractor
    }
    contacts = {
        "SUP-EG-01": dict(email="rfq@demo-supplier-01.invalid", rfq_channel="email", language="ar"),
        "SUP-EG-07": dict(email="sales@demo-supplier-07.invalid", rfq_channel="email", language="en"),
        "SUP-EG-03": dict(form_url="https://demo-supplier-03.invalid/quote", rfq_channel="web_form", language="en"),
    }
    messaging = dict(mode="dry_run", outbox_dir=os.path.join(tmp, "outbox"), inbox_dir=os.path.join(tmp, "inbox"),
                     alerts=dict(email_to=["buyer@demo.invalid"], repeat_hours=24), rfq_reply_days=3,
                     ack_expected_days=2)
    ag = ReplenishmentAgent(Config(db_path=work, sites=sites, contacts=contacts, messaging=messaging))
    mailer, notifier = ops.services(ag)
    as_of = date.fromisoformat(ag.as_of)

    step(1, "Demo stock, then the agent run: restock ALERTS go out (dry run: console + outbox)")
    ag.seed_demo_stock()
    res = ag.run()
    print(f"{len(res['alerts'])} materials need ordering; purchase request {res['purchase_request_number']}")
    print(f"alerts sent: {notifier.restock(res)}")
    print(f"same run again -> alerts sent: {notifier.restock(res)}   (no repeat within 24 h)")
    pr_id = res["purchase_request_id"]

    step(2, "Scrape supplier websites: which supplier offers which of OUR materials")
    for sup, site in sites.items():
        print(sup, ops.scraper.scrape_supplier(ag.con, sup, site, ops.materials(ag)))
    rows = ag.con.execute("SELECT catalog_item_id, supplier_id, product_name, matched_material, match_score "
                          "FROM ext_catalog_items ORDER BY supplier_id, match_score DESC").fetchall()
    for r in rows:
        print(f"  #{r[0]:<3} {r[1]} {r[2][:34]:34} -> {r[3]:28} score {r[4]:.2f}")
    print("contacts found:", [tuple(r) for r in ag.con.execute("SELECT supplier_id, kind, value FROM ext_supplier_contacts_found")])
    for r in rows:                                   # a buyer reviews and confirms the matches
        ops.scraper.decide(ag.con, r[0], True, "buyer")

    step(3, "Approve the purchase request, then draft one RFQ per supplier (history + confirmed web matches)")
    ag.approve_request(pr_id, by="procurement_manager")
    ids = rfq.create_rfqs(ag.con, pr_id, ag.cfg.agent_actor, contacts, ag.cfg.aliases, max_suppliers=3)
    try:
        rfq.approve_rfq(ag.con, ids[0], ag.cfg.agent_actor)
    except rfq.RFQError as e:
        print("REFUSED:", e)
    for rid in ids:
        rfq.approve_rfq(ag.con, rid, "buyer")
        out = rfq.send_rfq(ag.con, rid, "buyer", mailer)
        if out.startswith("manual"):
            rfq.mark_sent(ag.con, rid, "buyer")
    for r in ag.con.execute("SELECT rfq_number, supplier_id, channel, status, (SELECT COUNT(*) FROM ext_rfq_lines l "
                            "WHERE l.rfq_id=r.rfq_id) FROM ext_rfqs r"):
        print(f"  {r[0]} {r[1]} via {r[2]:8} {r[3]:6} {r[4]} line(s)")
    first = ag.con.execute("SELECT rfq_id FROM ext_rfqs WHERE supplier_id='SUP-EG-07'").fetchone()
    sample = ag.con.execute("SELECT subject, body FROM ext_rfqs WHERE rfq_id=?", ((first or [ids[0]])[0],)).fetchone()
    print(f"\n--- sample RFQ ---\nSubject: {sample[0]}\n{sample[1]}")

    step(4, "Suppliers reply with prices (generated emails); the agent reads the inbox and extracts them")
    src = ag._context()["src"]
    for r in ag.con.execute("SELECT * FROM ext_rfqs").fetchall():
        lines = quotes.rfq_lines(ag.con, r["rfq_id"])
        for l in lines:                              # suppliers answer with THEIR product names
            l["say"] = l["supplier_product_name"] or l["material"]
        if h(r["supplier_id"], 7) == 0:
            body = "Dear team,\nWe regret that we are unable to quote these items this month.\nRegards"
        elif r["language"] == "ar":
            body = "السادة الكرام،\nبالإشارة إلى طلبكم، أسعارنا كالتالي:\n" + "\n".join(
                f"{l['say']}: سعر {src.loc[l['material'], 'price_piastres'] / 100 * (0.85 + h(r['supplier_id'] + l['material'], 30) / 100):.2f} "
                f"جنيه للكيلو، مدة التوريد {int(src.loc[l['material'], 'lead_mean']) + h(r['supplier_id'], 3)} أيام"
                for l in lines if l["material"] in src.index) + "\nمع خالص التحية"
        else:
            body = "Hello,\nPlease find our offer below.\n" + "\n".join(
                f"{l['say']} | unit price: EGP {src.loc[l['material'], 'price_piastres'] / 100 * (0.85 + h(r['supplier_id'] + l['material'], 30) / 100):.2f} "
                f"per {'kg' if l['unit'] == 'g' else 'piece'} | MOQ: {src.loc[l['material'], 'moq_rfq_units']:,.0f} "
                f"{'kg' if l['unit'] == 'g' else 'pcs'} | lead time: {int(src.loc[l['material'], 'lead_mean']) + h(r['supplier_id'], 4)} days"
                f" | valid until: {(as_of + timedelta(days=30)).isoformat()}"
                for l in lines if l["material"] in src.index) + "\nBest regards"
        drop_mail(messaging["inbox_dir"], r["rfq_number"], f"RE: {r['subject']}", body,
                  f"sales@{r['supplier_id'].lower()}.invalid", as_of + timedelta(days=1))
    for line in ops.poll_inbox(ag, mailer, notifier):
        print("  inbox:", line)
    print("  reading the inbox again ->", ops.poll_inbox(ag, mailer, notifier) or "nothing new (each email handled once)")

    step(5, "A buyer checks and confirms each quote; compare offers per material")
    for (qid,) in ag.con.execute("SELECT quote_id FROM ext_quotes q WHERE EXISTS (SELECT 1 FROM ext_quote_lines l "
                                 "WHERE l.quote_id=q.quote_id)").fetchall():
        quotes.decide(ag.con, qid, "buyer")
    seen = set()
    for o in quotes.offers(ag.con, pr_id):
        tag = "BEST" if o["purchase_request_line_id"] not in seen else "    "
        seen.add(o["purchase_request_line_id"])
        print(f"  {tag} {o['material'][:28]:28} {o['supplier_id']} EGP {o['total_egp']:>13,.2f} lead "
              f"{o['lead_days']} d{'' if o['meets_date'] else ' LATE'}{'' if o['meets_moq'] else ' BELOW-MOQ'}")

    step(6, "Purchase orders use the best confirmed quotes; approved by a second person; emailed (dry run)")
    pos = ag.make_purchase_orders(pr_id)
    for po in pos:
        wf.approve_purchase_order(ag.con, po, "finance_checker")
        ag.send_purchase_order(po, "finance_checker", mailer, at=as_of.isoformat())
    for r in ag.con.execute("SELECT p.purchase_order_id, po_number, supplier_id, COUNT(*), "
                            "EXISTS(SELECT 1 FROM ext_po_quote_links k WHERE k.purchase_order_id=p.purchase_order_id) "
                            "FROM purchase_orders p JOIN purchase_order_lines USING(purchase_order_id) "
                            "WHERE p.purchase_order_id IN (%s) GROUP BY 1" % ",".join(map(str, pos))):
        print(f"  {r[1]} {r[2]} {r[3]} line(s)  price from {'supplier quote' if r[4] else 'purchase history'}")

    step(7, "Delivery tracking: the supplier confirms, ships PART of the order, carrier delivers")
    po = pos[0]
    po_no = ag.con.execute("SELECT po_number FROM purchase_orders WHERE purchase_order_id=?", (po,)).fetchone()[0]
    pl = ag.con.execute("SELECT purchase_order_line_id, material_reference, quantity_base_units, base_unit_snapshot "
                        "FROM purchase_order_lines WHERE purchase_order_id=?", (po,)).fetchall()
    ship_lines = "\n".join(f"{r[1][4:]}: {r[2] * 0.8 / (1000 if r[3] == 'g' else 1):,.0f} {'kg' if r[3] == 'g' else 'pcs'}"
                           for r in pl)
    msgs = [(1, "Order confirmation", f"Dear team, we confirm receipt of your order {po_no}. Regards"),
            (4, "Shipping notice", f"Your order {po_no} has been shipped today with Aramex.\nTracking number: "
                                   f"AWB-58812347\nShipped quantities:\n{ship_lines}\n"
                                   f"Expected arrival: {(as_of + timedelta(days=7)).isoformat()}"),
            (6, "Out for delivery", f"Aramex: shipment AWB-58812347 for {po_no} is out for delivery."),
            (7, "Delivered", f"Aramex: shipment AWB-58812347 ({po_no}) has been delivered to your warehouse.")]
    for d, subj, body in msgs:
        drop_mail(messaging["inbox_dir"], f"{po_no}-{d}", f"[{po_no}] {subj}", body, "logistics@supplier.invalid",
                  as_of + timedelta(days=d))
    for line in ops.poll_inbox(ag, mailer, notifier):
        print("  inbox:", line)
    tracking.record(ag.con, po, "delivered", "warehouse_user", at=(as_of + timedelta(days=7)).isoformat(),
                    receive_location=ag.loc_id, note="goods counted at the gate")
    ops.print_timeline(tracking.timeline(ag.con, po, (as_of + timedelta(days=15)).isoformat()))

    step(8, "Two weeks later: what needs chasing (late, unconfirmed, short shipments) -> alerts")
    today = (as_of + timedelta(days=15)).isoformat()
    exc = tracking.exceptions(ag.con, ag.env_id, today, 2)
    for e in exc[:8]:
        print(f"  {e['po_number']} {e['supplier_id']}: {e['reason']} - {e['detail'][:90]}")
    print(f"  ... {len(exc)} issue(s); alerts sent: {notifier.late(exc)}")

    step(9, "Supplier scorecard from tracked deliveries")
    for s in tracking.scorecard(ag.con, ag.env_id):
        print("  ", s)
    n_out = len(os.listdir(messaging["outbox_dir"]))
    print(f"\n{n_out} outgoing messages were written to the dry-run outbox (nothing was sent).")
    ag.con.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
