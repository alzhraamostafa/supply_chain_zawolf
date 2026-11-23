import json, os, shutil, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ops, quotes, rfq, scraper, tracking, workflow as wf
from agent import ReplenishmentAgent
from config import Config
from mailer import Mailer
from notify import Notifier
from test_agent import SOURCE_DB, SEALED, table_hash

LINES_G = [dict(rfq_line_id=1, material="Citric_Acid_Anhydrous", unit="g"),
           dict(rfq_line_id=2, material="PK-PLASTIC-TUBE-125ML", unit="pcs")]


@pytest.fixture()
def ag(tmp_path):
    p = tmp_path / "work.db"
    shutil.copy(SOURCE_DB, p)
    msg = dict(mode="dry_run", outbox_dir=str(tmp_path / "outbox"), inbox_dir=str(tmp_path / "inbox"),
               alerts=dict(email_to=["buyer@x.invalid"], repeat_hours=24))
    contacts = {"SUP-EG-01": dict(email="rfq@sup1.invalid", rfq_channel="email", language="en")}
    a = ReplenishmentAgent(Config(db_path=str(p), messaging=msg, contacts=contacts, sites={}))
    a.seed_demo_stock()
    return a


def _pr_with_rfqs(ag):
    res = ag.run()
    ag.approve_request(res["purchase_request_id"], by="procurement_manager")
    ids = rfq.create_rfqs(ag.con, res["purchase_request_id"], ag.cfg.agent_actor, ag.cfg.contacts, ag.cfg.aliases)
    return res, ids


# ------------------------------------------------------------------ scraper matching
def test_match_accepts_supplier_wording_and_rejects_wrong_size():
    assert scraper.match_score("Glycerin_BP_99.5", "Glycerine BP 99.5%") == 1.0
    assert scraper.match_score("PK-PET-BOTTLE-250ML", "PET Bottle 250 ml clear") == 1.0
    assert scraper.match_score("PK-PET-BOTTLE-250ML", "PET Bottle 500 ml") < 0.6        # same item, wrong size
    mat, _ = scraper.best_match("Plastic Tube 150ml", None, ["PK-PLASTIC-TUBE-125ML", "PK-PLASTIC-TUBE-150ML"])
    assert mat == "PK-PLASTIC-TUBE-150ML"


def test_extract_with_selectors_finds_items_next_page_and_contacts():
    html = ("<div class=p><h3 class=t>Plastic Tube 125 ml</h3><b class=s>PT1</b></div>"
            "<a class=next href='p2.html'>next</a><a href='mailto:sales@s.invalid'>mail</a>"
            "<form action='/quote'><textarea name=message></textarea>Request a quotation</form>")
    out = scraper.extract(html, "https://s.invalid/catalog/p1.html",
                          dict(item_selector="div.p", name_selector=".t", code_selector=".s", next_selector="a.next"))
    assert out["items"] == [dict(name="Plastic Tube 125 ml", code="PT1")]
    assert out["next"] == "https://s.invalid/catalog/p2.html"
    assert ("email", "sales@s.invalid") in out["contacts"] and ("form", "https://s.invalid/quote") in out["contacts"]


def test_scraped_match_needs_confirmation_before_use(ag):
    class Fake:
        def get(self, url, render="static"):
            return "<ul><li>Citric Acid Anhydrous</li></ul>"
    scraper.scrape_supplier(ag.con, "SUP-EG-07", dict(start_urls=["https://x.invalid"]), ["Citric_Acid_Anhydrous"], Fake())
    assert scraper.suppliers_offering(ag.con, "Citric_Acid_Anhydrous") == []           # candidate only
    cid = ag.con.execute("SELECT catalog_item_id FROM ext_catalog_items").fetchone()[0]
    scraper.decide(ag.con, cid, True, "buyer")
    assert scraper.suppliers_offering(ag.con, "Citric_Acid_Anhydrous") == ["SUP-EG-07"]


# ------------------------------------------------------------------ quote parsing
def test_parse_pipe_format_reply():
    text = ("Citric_Acid_Anhydrous | unit price: EGP 310.50 per kg | MOQ: 2 ton | lead time: 6 days | valid until: 2026-08-01\n"
            "PK-PLASTIC-TUBE-125ML | unit price: EGP 1,450 per 1000 pcs | MOQ: 10,000 pcs | lead time: 8 days")
    got = {p["rfq_line_id"]: p for p in quotes.parse_reply(text, LINES_G)}
    assert got[1]["unit_price_piastres"] == 31050 and got[1]["price_basis_base_units"] == 1000
    assert got[1]["moq_base_units"] == 2_000_000 and got[1]["lead_days"] == 6 and got[1]["valid_until"] == "2026-08-01"
    assert got[2]["unit_price_piastres"] == 145000 and got[2]["price_basis_base_units"] == 1000
    assert got[2]["moq_base_units"] == 10000


def test_parse_arabic_free_text_with_arabic_digits():
    text = "Citric_Acid_Anhydrous: سعر ٣١٠ جنيه للطن، مدة التوريد ٧ أيام"
    (p,) = quotes.parse_reply(text, LINES_G)
    assert p["unit_price_piastres"] == 31000 and p["price_basis_base_units"] == 1_000_000 and p["lead_days"] == 7


def test_quoted_original_without_prices_is_ignored():
    text = "> - Citric_Acid_Anhydrous: 1,000 kg - needed by 2026-07-06\n> Citric_Acid_Anhydrous | unit price: EGP ____"
    assert quotes.parse_reply(text, LINES_G) == []


def test_llm_quote_with_invented_number_is_rejected():
    reply = "Citric acid: we can offer a good price, call us."
    bad = lambda prompt: json.dumps([dict(rfq_line_id=1, unit_price_egp=299.0, price_per="kg")])
    with pytest.raises(ValueError):
        quotes._llm_extract(reply, LINES_G, bad)


# ------------------------------------------------------------------ RFQ workflow + messaging
def test_rfq_maker_checker_and_dry_run_never_touches_smtp(ag, monkeypatch):
    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP used")))
    _, ids = _pr_with_rfqs(ag)
    rid = ag.con.execute("SELECT rfq_id FROM ext_rfqs WHERE supplier_id='SUP-EG-01'").fetchone()[0]
    with pytest.raises(rfq.RFQError):
        rfq.send_rfq(ag.con, rid, "buyer", Mailer(ag.cfg.messaging))                    # not approved yet
    with pytest.raises(rfq.RFQError):
        rfq.approve_rfq(ag.con, rid, ag.cfg.agent_actor)                                 # agent cannot self-approve
    rfq.approve_rfq(ag.con, rid, "buyer")
    assert rfq.send_rfq(ag.con, rid, "buyer", Mailer(ag.cfg.messaging)) == "dry_run"
    row = ag.con.execute("SELECT status, file_path FROM ext_outbox WHERE kind='rfq'").fetchone()
    assert row[0] == "dry_run" and os.path.exists(row[1])
    body = ag.con.execute("SELECT body FROM ext_rfqs WHERE rfq_id=?", (rid,)).fetchone()[0]
    assert "EGP ____" in body and "does not commit" in body                              # asks for prices, invents none


def test_rerun_rfq_create_does_not_duplicate(ag):
    res, ids = _pr_with_rfqs(ag)
    again = rfq.create_rfqs(ag.con, res["purchase_request_id"], ag.cfg.agent_actor, ag.cfg.contacts, ag.cfg.aliases)
    assert ids and again == []


def test_po_uses_only_confirmed_quote(ag):
    res, _ = _pr_with_rfqs(ag)
    rid, sup = ag.con.execute("SELECT rfq_id, supplier_id FROM ext_rfqs ORDER BY rfq_id LIMIT 1").fetchone()
    lines = quotes.rfq_lines(ag.con, rid)
    reply = "\n".join(f"{l['material']} | unit price: EGP 1.23 per {'kg' if l['unit'] == 'g' else 'piece'} | "
                      f"lead time: 3 days" for l in lines)
    q = quotes.ingest(ag.con, rid, reply)
    assert q["lines"] == len(lines)
    assert quotes.selection(ag.con, res["purchase_request_id"]) == {}                   # extracted, not confirmed
    with pytest.raises(quotes.QuoteError):
        quotes.decide(ag.con, q["quote_id"], ag.cfg.agent_actor)                          # maker != checker
    quotes.decide(ag.con, q["quote_id"], "buyer")
    pos = ag.make_purchase_orders(res["purchase_request_id"])
    prices = {r[0]: r[1] for r in ag.con.execute(
        "SELECT stock_item_id, quoted_price_piastres FROM purchase_order_lines WHERE purchase_order_id IN (%s)"
        % ",".join(map(str, pos)))}
    for l in lines:
        assert prices[l["stock_item_id"]] == 123
    assert ag.con.execute("SELECT COUNT(*) FROM ext_po_quote_links").fetchone()[0] >= 1


# ------------------------------------------------------------------ delivery tracking
def _sent_po(ag):
    res = ag.run()
    ag.approve_request(res["purchase_request_id"], by="procurement_manager")
    po = ag.make_purchase_orders(res["purchase_request_id"])[0]
    wf.approve_purchase_order(ag.con, po, "finance_checker")
    ag.send_purchase_order(po, "finance_checker", Mailer(ag.cfg.messaging), at="2026-07-01")
    return po


def test_tracking_cannot_start_before_po_is_sent(ag):
    res = ag.run()
    ag.approve_request(res["purchase_request_id"], by="procurement_manager")
    po = ag.make_purchase_orders(res["purchase_request_id"])[0]
    with pytest.raises(tracking.TrackingError):
        tracking.record(ag.con, po, "shipped", "supplier")


def test_partial_shipment_timeline_and_receipt(ag):
    po = _sent_po(ag)
    line = ag.con.execute("SELECT purchase_order_line_id, quantity_base_units, stock_item_id FROM purchase_order_lines "
                          "WHERE purchase_order_id=? ORDER BY line_number LIMIT 1", (po,)).fetchone()
    others = {r[0]: r[1] for r in ag.con.execute("SELECT purchase_order_line_id, quantity_base_units FROM "
                                                 "purchase_order_lines WHERE purchase_order_id=?", (po,))}
    ship = {**others, line[0]: line[1] // 2}
    before = wf.stock_on_hand(ag.con, ag.env_id, line[2], ag.loc_id)
    tracking.record(ag.con, po, "acknowledged", "supplier", at="2026-07-02")
    tracking.record(ag.con, po, "shipped", "supplier", at="2026-07-05", carrier="Aramex", tracking_number="AWB123456",
                    shipped=ship)
    tracking.record(ag.con, po, "delivered", "warehouse", at="2026-07-08", receive_location=ag.loc_id)
    t = tracking.timeline(ag.con, po)
    assert t["days"] == dict(order_by_to_sent=t["days"]["order_by_to_sent"], sent_to_acknowledged=1, sent_to_shipped=4,
                             shipped_to_delivered=3, total_lead_time=7)
    assert wf.stock_on_hand(ag.con, ag.env_id, line[2], ag.loc_id) == before + line[1] // 2     # only what was shipped
    exc = tracking.exceptions(ag.con, ag.env_id, "2026-07-09")
    assert any(e["reason"] == "short shipment" for e in exc)


def test_late_and_unconfirmed_orders_are_flagged(ag):
    po = _sent_po(ag)
    promised = tracking.timeline(ag.con, po)["promised"]
    exc = {e["reason"] for e in tracking.exceptions(ag.con, ag.env_id, "2026-12-31") if e["po_number"].endswith(f"{po:05d}")}
    assert {"late", "not confirmed"} <= exc and promised < "2026-12-31"


def test_status_email_parsing_en_and_ar():
    s = tracking.parse_status_email("Your order PO-3-00010 has been shipped via Aramex. Tracking number: AWB-58812347. "
                                    "Expected arrival 2026-07-08")
    assert (s["status"], s["carrier"], s["tracking_number"], s["eta"]) == ("shipped", "Aramex", "AWB-58812347", "2026-07-08")
    assert tracking.parse_status_email("تم الشحن اليوم، رقم الشحنة: EG99887766")["status"] == "shipped"
    assert tracking.parse_status_email("الشحنة خرجت للتسليم مع المندوب")["status"] == "out_for_delivery"
    assert tracking.parse_status_email("Shipment has been delivered to your warehouse")["status"] == "delivered"


def test_shipped_quantities_read_from_email():
    lines = [dict(purchase_order_line_id=7, material="Citric_Acid_Anhydrous", unit="g")]
    s = tracking.parse_status_email("Shipped today.\nCitric_Acid_Anhydrous: 800 kg", lines)
    assert s["shipped"] == {7: 800_000}


# ------------------------------------------------------------------ alerts
def test_alert_not_repeated_but_escalation_is_sent(ag):
    n = Notifier(ag.con, Mailer(ag.cfg.messaging), ag.cfg.messaging, echo=lambda *_: None)
    assert n.notify("restock", "restock:X", "warning", "s", "b")
    assert not n.notify("restock", "restock:X", "warning", "s", "b")
    assert n.notify("restock", "restock:X", "critical", "s", "b")
    assert ag.con.execute("SELECT COUNT(*) FROM ext_outbox WHERE kind='alert:restock'").fetchone()[0] == 2


def test_history_tables_untouched_by_procurement_flow(ag):
    before = {t: table_hash(ag.con, t) for t in SEALED}
    po = _sent_po(ag)
    tracking.record(ag.con, po, "delivered", "warehouse", at="2026-07-08", receive_location=ag.loc_id)
    ops.poll_inbox(ag, *ops.services(ag))
    assert before == {t: table_hash(ag.con, t) for t in SEALED}


# ------------------------------------------------------------------ one item, two names (ours and the supplier's)
def test_rfq_po_and_replies_use_the_suppliers_own_names(ag):
    res = ag.run()
    pr = res["purchase_request_id"]
    ag.approve_request(pr, by="procurement_manager")
    scraper.add_name(ag.con, "SUP-EG-06", "PK-PLASTIC-TUBE-125ML", "Lamitube White 125 cc", "LT-125W", "buyer")
    rfq.create_rfqs(ag.con, pr, ag.cfg.agent_actor, ag.cfg.contacts, ag.cfg.aliases)
    rid, body = ag.con.execute("SELECT rfq_id, body FROM ext_rfqs WHERE supplier_id='SUP-EG-06'").fetchone()
    assert "Lamitube White 125 cc (your code LT-125W, our ref PK-PLASTIC-TUBE-125ML)" in body
    # the supplier answers with ONLY their code: still matched to our material
    q = quotes.ingest(ag.con, rid, "LT-125W | unit price: EGP 1.10 per piece | lead time: 6 days")
    assert q["lines"] == 1
    line = quotes.rfq_lines(ag.con, rid)[0]
    assert line["supplier_product_code"] == "LT-125W" and line["material"] == "PK-PLASTIC-TUBE-125ML"
    # a shipping notice that uses their name is matched to our PO line
    po_lines = [dict(purchase_order_line_id=9, material="PK-PLASTIC-TUBE-125ML", unit="pcs",
                     supplier_name="Lamitube White 125 cc", supplier_code="LT-125W")]
    s = tracking.parse_status_email("Shipped today.\nLamitube White 125 cc: 20,000 pcs", po_lines)
    assert s["shipped"] == {9: 20000}


def test_without_a_confirmed_name_our_name_is_used(ag):
    import drafter
    assert drafter._label(dict(material="Sodium_Chloride")) == "Sodium_Chloride"
    assert scraper.supplier_name_for(ag.con, "SUP-EG-01", "Sodium_Chloride") == (None, None)
