import hashlib, json, math, os, shutil, sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import planning as pl, workflow as wf, drafter
from agent import ReplenishmentAgent
from config import Config

SOURCE_DB = os.environ.get("SOURCE_DB",
                           "/mnt/user-data/uploads/smart_supply_chain_simulation_v5_recovered_review1.db")
SEALED = ["commercial_order_history", "product_bom_snapshots", "products", "procurement_rfq_history",
          "suppliers", "production_shift_history", "inventory_snapshot_history"]


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "work.db"
    shutil.copy(SOURCE_DB, p)
    return str(p)


@pytest.fixture()
def agent(db):
    return ReplenishmentAgent(Config(db_path=db))


def table_hash(con, table):
    h = hashlib.sha256()
    for row in con.execute(f"SELECT * FROM {table} ORDER BY 1"):
        h.update(repr(tuple(row)).encode())
    return h.hexdigest()


# ------------------------------------------------------------------ math (no database writes)
def test_bom_grams_match_hand_calculation(agent):
    bom, _ = pl.build_bom(agent.con, agent.cfg.aliases)
    r = agent.con.execute("""SELECT b.item_code, b.chemical_gradients_json, p.nominal_size_value_unverified s,
                                    p.size_unit u, p.specific_gravity_observed sg
                             FROM product_bom_snapshots b JOIN products p USING(item_code)
                             WHERE p.size_unit IS NOT NULL LIMIT 1""").fetchone()
    mass = r["s"] * (r["sg"] if r["u"] == "ml" else 1.0)
    shares = json.loads(r["chemical_gradients_json"])
    got = bom[(bom.item_code == r["item_code"]) & (bom.kind == "chemical")]
    assert math.isclose(got.qty_per_unit.sum(), sum(shares.values()) * mass, rel_tol=1e-9)
    assert math.isclose(sum(shares.values()), 1.0, abs_tol=1e-6)      # shares add up to 100%


def test_alias_merges_two_names_into_one_material(agent):
    bom, _ = pl.build_bom(agent.con, agent.cfg.aliases)
    assert "Sodium_Chloride_Pure" not in set(bom.material)
    assert "Sodium_Chloride" in set(bom.material)


def test_weekly_uses_only_complete_weeks(agent):
    w = pl.weekly_units(agent.con, agent.as_of)
    assert all(d.weekday() == 0 for d in w.index)                      # all Mondays
    assert w.index.max() + pd.Timedelta(days=6) <= pd.Timestamp(agent.as_of)


def _series(vals):
    return pd.Series(vals, index=pd.date_range("2026-01-05", periods=len(vals), freq="7D"))


def _src(**kw):
    base = dict(supplier_id="S1", supplier_name="Test Co", payment_terms="30", rfq_id=1,
                price_piastres=10000, price_min=8000, price_max=12000, moq_rfq_units=100.0,
                lead_mean=7.0, lead_sd=0.0)
    base.update(kw)
    return base


POLICY = dict(window_weeks=4, sigma_weeks=4, service_level_z=1.645, review_days=7)


def test_reorder_point_and_order_quantity():
    # constant 7000 g/week -> 1000 g/day, no variability -> safety stock 0
    a = pl.assess_material("X", "chemical", _series([7000] * 8), _src(), stock=5000, open_supply=0,
                           policy=POLICY, as_of="2026-06-30")
    assert math.isclose(a.mu_day, 1000.0) and a.safety_stock == 0 and a.lead_days == 7
    assert math.isclose(a.rop, 7000.0)
    assert a.status == "ALERT" and a.severity == "critical"            # 5 days of cover < 7 days lead time
    # target = 1000*(7+7) = 14000; shortfall = 9000; MOQ = 100 kg = 100000 g -> one MOQ
    assert a.moq_base == 100000 and a.order_qty == 100000
    assert a.est_cost_egp == round(100000 / 1000 * 10000 / 100, 2)     # 100 kg * 100 EGP/kg = 10,000 EGP


def test_safety_stock_formula():
    s = _series([6000, 8000] * 4)
    a = pl.assess_material("X", "chemical", s, _src(lead_mean=9.0, lead_sd=1.0), stock=1e9, open_supply=0,
                           policy=POLICY, as_of="2026-06-30")
    sig_d = s.tail(4).std(ddof=1) / math.sqrt(7)
    expect = 1.645 * math.sqrt(9 * sig_d ** 2 + (a.mu_day * 1.0) ** 2)
    assert math.isclose(a.safety_stock, expect, rel_tol=1e-9)
    assert a.status == "OK"


def test_enough_stock_means_no_alert():
    a = pl.assess_material("X", "chemical", _series([7000] * 8), _src(), stock=50000, open_supply=0,
                           policy=POLICY, as_of="2026-06-30")
    assert a.status == "OK" and a.order_qty == 0


def test_open_supply_prevents_double_ordering():
    kw = dict(policy=POLICY, as_of="2026-06-30")
    low = pl.assess_material("X", "chemical", _series([7000] * 8), _src(), stock=5000, open_supply=0, **kw)
    cov = pl.assess_material("X", "chemical", _series([7000] * 8), _src(), stock=5000, open_supply=100000, **kw)
    assert low.status == "ALERT" and cov.status == "OK"


def test_unknown_stock_is_not_treated_as_zero():
    a = pl.assess_material("X", "chemical", _series([7000] * 8), _src(), stock=None, open_supply=0,
                           policy=POLICY, as_of="2026-06-30")
    assert a.status == "STOCK_UNKNOWN" and a.order_qty == 0


def test_material_without_supplier_history_is_flagged_not_ordered():
    a = pl.assess_material("X", "chemical", _series([7000] * 8), None, stock=0, open_supply=0,
                           policy=POLICY, as_of="2026-06-30")
    assert a.status == "NO_SUPPLIER" and a.order_qty == 0


# ------------------------------------------------------------------ workflow and guardrails
def test_run_before_stock_exists_creates_nothing(agent):
    res = agent.run()
    assert not res["alerts"] and res["purchase_request_id"] is None
    assert len(res["unknown_stock"]) > 0
    assert agent.con.execute("SELECT COUNT(*) FROM purchase_requests WHERE environment_id=?",
                             (agent.env_id,)).fetchone()[0] == 0


def test_full_flow_with_human_gates(agent):
    agent.seed_demo_stock()
    res = agent.run()
    assert res["alerts"] and res["purchase_request_id"]
    pr = res["purchase_request_id"]
    row = agent.con.execute("SELECT status, requested_by FROM purchase_requests WHERE purchase_request_id=?",
                            (pr,)).fetchone()
    assert row["status"] == "draft" and row["requested_by"] == agent.cfg.agent_actor
    n_lines = agent.con.execute("SELECT COUNT(*) FROM purchase_request_lines WHERE purchase_request_id=?",
                                (pr,)).fetchone()[0]
    assert n_lines == len(res["alerts"])

    with pytest.raises(wf.WorkflowError):                       # no PO before approval
        agent.make_purchase_orders(pr)
    with pytest.raises(wf.WorkflowError):                       # maker cannot approve own request
        agent.approve_request(pr, by=agent.cfg.agent_actor)
    assert agent.approve_request(pr, by="procurement_manager") == "approved"
    with pytest.raises(wf.WorkflowError):                       # cannot decide twice
        agent.approve_request(pr, by="someone_else")

    pos = agent.make_purchase_orders(pr)
    assert len(pos) == len({a.supplier_id for a in res["alerts"]})      # one PO per supplier
    assert agent.make_purchase_orders(pr) == []                         # no duplicate POs
    po = pos[0]
    with pytest.raises(wf.WorkflowError):                       # not sent before approved
        wf.send_purchase_order_simulated(agent.con, po, "finance_checker")
    with pytest.raises(wf.WorkflowError):                       # maker cannot approve own PO
        wf.approve_purchase_order(agent.con, po, agent.cfg.agent_actor)
    wf.approve_purchase_order(agent.con, po, "finance_checker")
    wf.send_purchase_order_simulated(agent.con, po, "finance_checker")
    st = agent.con.execute("SELECT status FROM purchase_orders WHERE purchase_order_id=?", (po,)).fetchone()[0]
    assert st == "sent"
    reason = agent.con.execute("SELECT reason FROM purchase_order_events WHERE purchase_order_id=? "
                               "ORDER BY event_id DESC LIMIT 1", (po,)).fetchone()[0]
    assert "SIMULATED" in reason


def test_rerun_does_not_duplicate_requests(agent):
    agent.seed_demo_stock()
    first = agent.run()
    second = agent.run()
    assert first["alerts"] and not second["alerts"] and second["purchase_request_id"] is None
    assert agent.con.execute("SELECT COUNT(*) FROM recommendations WHERE environment_id=? AND "
                             "recommendation_type='replenishment_alert'", (agent.env_id,)).fetchone()[0] == 1


def test_receipt_raises_stock_and_clears_alert(agent):
    agent.seed_demo_stock()
    res = agent.run()
    pr = res["purchase_request_id"]
    agent.approve_request(pr, by="procurement_manager")
    pos = agent.make_purchase_orders(pr)
    for po in pos:
        wf.approve_purchase_order(agent.con, po, "finance_checker")
        wf.send_purchase_order_simulated(agent.con, po, "finance_checker")
    first = res["alerts"][0]
    sid = agent._stock_item(first.material)
    before = wf.stock_on_hand(agent.con, agent.env_id, sid, agent.loc_id)
    for po in pos:
        wf.receive_purchase_order(agent.con, po, agent.loc_id, "warehouse_user")
    after = wf.stock_on_hand(agent.con, agent.env_id, sid, agent.loc_id)
    assert after == before + first.order_qty
    states = {p: agent.con.execute("SELECT status FROM purchase_orders WHERE purchase_order_id=?", (p,)).fetchone()[0]
              for p in pos}
    assert set(states.values()) == {"received"}
    assert not agent.run()["alerts"]


def test_database_refuses_negative_stock_and_nonzero_opening(agent):
    sid = wf.ensure_stock_item(agent.con, "TEST_MAT", "chemical", "g")
    wf.ensure_opening(agent.con, agent.env_id, sid, agent.loc_id, "tester")
    assert wf.stock_on_hand(agent.con, agent.env_id, sid, agent.loc_id) == 0
    with pytest.raises(Exception):
        agent.con.execute("INSERT INTO inventory_movements(stock_item_id,location_id,occurred_at_utc,movement_kind,"
                          "quantity_delta_base_units,reason,evidence_reference,actor_reference,idempotency_key,environment_id)"
                          " VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (sid, agent.loc_id, "2099-01-01T00:00:00Z", "issue", -5, "x", "x", "t", "k1", agent.env_id))


def test_history_tables_are_never_modified(db):
    import sqlite3
    con = sqlite3.connect(db)
    before = {t: table_hash(con, t) for t in SEALED}
    con.close()
    ag = ReplenishmentAgent(Config(db_path=db))
    ag.seed_demo_stock()
    res = ag.run()
    ag.approve_request(res["purchase_request_id"], by="procurement_manager")
    ag.make_purchase_orders(res["purchase_request_id"])
    con = sqlite3.connect(db)
    assert {t: table_hash(con, t) for t in SEALED} == before


def test_every_agent_row_is_in_its_own_environment(agent):
    agent.seed_demo_stock()
    agent.run()
    for table in ("recommendations", "purchase_requests", "purchase_orders", "inventory_movements", "goods_receipts"):
        bad = agent.con.execute(f"SELECT COUNT(*) FROM {table} WHERE environment_id IS NOT ? "
                                "AND environment_id IN (SELECT environment_id FROM simulation_environments WHERE name IN ('exp1','exp2'))",
                                (agent.env_id,)).fetchone()[0]
        assert bad == 0       # nothing leaked into the team's test environments


# ------------------------------------------------------------------ drafter guardrails
LINES = [dict(material="Glycerin_BP_99.5", qty=500000, unit="g", needed_by="2026-07-08")]


def test_template_has_no_price_and_states_no_commitment():
    t = drafter.template_message("Supplier A", "PR-3-00002", LINES, "en")
    assert "500 kg" in t and "does not commit" in t and "EGP" not in t
    ar = drafter.template_message("Supplier A", "PR-3-00002", LINES, "ar")
    assert "500 كجم" in ar and "التزامًا" in ar


def test_llm_text_with_invented_number_is_rejected():
    base = drafter.template_message("Supplier A", "PR-3-00002", LINES, "en")
    text, src = drafter.draft_message("Supplier A", "PR-3-00002", LINES, "en",
                                      llm=lambda p: base + "\nWe can offer a 15% discount if you ship 900 kg.")
    assert src == "template" and "15%" not in text


def test_faithful_llm_rewrite_is_accepted():
    ok = ("Hello Supplier A, for request PR-3-00002 please send your price, lead time and MOQ for "
          "Glycerin_BP_99.5, 500 kg, needed by 2026-07-08. This is only a draft quote request.")
    text, src = drafter.draft_message("Supplier A", "PR-3-00002", LINES, "en", llm=lambda p: ok)
    assert src == "llm" and text == ok


def test_llm_failure_falls_back_to_template():
    def boom(prompt):
        raise RuntimeError("network down")
    text, src = drafter.draft_message("Supplier A", "PR-3-00002", LINES, "en", llm=boom)
    assert src == "template" and "500 kg" in text
