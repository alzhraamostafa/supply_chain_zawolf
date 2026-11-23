"""Replenishment agent: alert when a material is needed, prepare the purchase list, draft supplier messages.

Autonomy level 1: the agent PREPARES (recommendation, draft purchase request, draft messages).
Humans approve. "Sending" is simulated. All numbers come from code and the database, never from an LLM.

Usage (always on a COPY of the database):
  python agent.py --db work.db seed
  python agent.py --db work.db run
  python agent.py --db work.db approve --pr 1 --by procurement_manager
  python agent.py --db work.db po --pr 1
  python agent.py --db work.db po-approve --po 1 --by finance_checker
  python agent.py --db work.db po-send --po 1 --by finance_checker
"""
from __future__ import annotations
import argparse, hashlib, json, sys

import numpy as np
import pandas as pd

import planning as pl
import workflow as wf
import drafter
import quotes
import store
import tracking
import ops
import rfq
import scraper
from config import Config
from db import connect, now_utc, tx as store_tx

METHOD = "reorder_point_v1"
CAVEATS = [
    "Recorded orders are not true demand (lost sales are not recorded).",
    "Product size and density are unverified in the source; quantities are scenario estimates.",
    "Weekly average of recent complete weeks is a baseline forecast, not a trained model.",
    "RFQ price and MOQ are read as per kg (chemicals) or per piece (packaging); confirm the unit basis.",
    "Quotes for the same material vary a lot between RFQs; the estimate uses the median, the range is shown.",
]


class ReplenishmentAgent:
    def __init__(self, cfg: Config, llm=None):
        self.cfg, self.llm = cfg, llm
        self.con = connect(cfg.db_path)
        store.ensure_schema(self.con)
        self.env_id = wf.ensure_environment(self.con, cfg.environment, cfg.agent_actor,
                                            "replenishment agent sandbox")
        self.loc_id = wf.ensure_location(self.con, self.env_id, "RAW_MATERIAL_WH")
        self.as_of = cfg.as_of or self.con.execute("SELECT MAX(order_date) FROM commercial_order_history").fetchone()[0]

    # ---------------------------------------------------------------- analysis
    def _context(self):
        bom, warns = pl.build_bom(self.con, self.cfg.aliases)
        weekly = pl.weekly_units(self.con, self.as_of)
        mat_w = pl.material_weekly(weekly, bom, pl.scrap_rates(self.con),
                                   self.cfg.policy["apply_scrap_allowance"])
        src = pl.sourcing(self.con, self.cfg.aliases)
        if self.cfg.policy.get("use_observed_lead_times"):
            src = self._observed_leads(src)
        kinds = bom.drop_duplicates("material").set_index("material")["kind"].to_dict()
        return dict(bom=bom, warnings=warns, weekly=weekly, mat_w=mat_w, src=src, kinds=kinds)

    def _observed_leads(self, src):
        """Replace RFQ-history lead times with lead times measured by delivery tracking, once there are enough."""
        obs, n_min = tracking.observed_lead_times(self.con, self.env_id), self.cfg.policy.get("observed_lead_min_orders", 3)
        src = src.copy()
        for material, row in src.iterrows():
            days = obs.get((row["supplier_id"], material), [])
            if len(days) >= n_min:
                src.loc[material, "lead_mean"] = float(np.mean(days))
                src.loc[material, "lead_sd"] = float(np.std(days))
        return src

    def _stock_item(self, material):
        r = self.con.execute("SELECT stock_item_id FROM stock_items WHERE identity_reference=?", (material,)).fetchone()
        return r[0] if r else None

    def analyze(self, ctx=None):
        ctx = ctx or self._context()
        out = []
        for material, kind in sorted(ctx["kinds"].items()):
            sid = self._stock_item(material)
            stock = wf.stock_on_hand(self.con, self.env_id, sid, self.loc_id) if sid else None
            supply = wf.open_supply(self.con, self.env_id, sid) if sid else 0
            src = ctx["src"].loc[material] if material in ctx["src"].index else None
            out.append(pl.assess_material(material, kind, ctx["mat_w"][material], src, stock, supply,
                                          self.cfg.policy, self.as_of))
        return out, ctx

    # ---------------------------------------------------------------- the agent run
    def run(self, persist: bool = True) -> dict:
        assessments, ctx = self.analyze()
        alerts = [a for a in assessments if a.status == "ALERT" and a.order_qty > 0]
        alerts.sort(key=lambda a: (a.severity != "critical", a.order_by or ""))
        result = dict(as_of=self.as_of, environment=self.cfg.environment, alerts=alerts,
                      unknown_stock=[a.material for a in assessments if a.status == "STOCK_UNKNOWN"],
                      no_supplier=[a.material for a in assessments if a.status == "NO_SUPPLIER"],
                      ok=[a.material for a in assessments if a.status == "OK"],
                      warnings=ctx["warnings"], recommendation_id=None, purchase_request_id=None, drafts={})
        if not alerts or not persist:
            return result

        total = round(sum(a.est_cost_egp for a in alerts), 2)
        total_low = round(sum(a.est_cost_low_egp for a in alerts), 2)
        total_high = round(sum(a.est_cost_high_egp for a in alerts), 2)
        role = self.cfg.approval_role(total)
        lines, proposal_lines = [], []
        for a in alerts:
            sid = wf.ensure_stock_item(self.con, a.material, a.kind, a.unit)
            policy = dict(method=METHOD, as_of=self.as_of, mu_day=round(a.mu_day, 3), sigma_day=round(a.sigma_day, 3),
                          lead_days=a.lead_days, lead_sd=round(a.lead_sd, 3), service_z=self.cfg.policy["service_level_z"],
                          review_days=self.cfg.policy["review_days"], safety_stock=round(a.safety_stock, 1),
                          reorder_point=round(a.rop, 1), position=round(a.position, 1),
                          shortfall=round(a.shortfall, 1), moq_base_units=a.moq_base,
                          rounding="ceil_to_moq_multiple", caveats=CAVEATS)
            lines.append(dict(stock_item_id=sid, qty=a.order_qty, policy=policy,
                              note=f"{a.severity}: stock-out expected {a.stockout_date}"))
            proposal_lines.append(dict(stock_item_id=sid, material=a.material, unit=a.unit, qty=a.order_qty,
                                       severity=a.severity, stockout_date=a.stockout_date, order_by=a.order_by,
                                       supplier_id=a.supplier_id, supplier_name=a.supplier_name, rfq_id=a.rfq_id,
                                       price_piastres=a.price_piastres, price_basis=a.price_basis,
                                       lead_days=a.lead_days, est_cost_egp=a.est_cost_egp,
                                       est_cost_low_egp=a.est_cost_low_egp, est_cost_high_egp=a.est_cost_high_egp))
        batch = self.con.execute("SELECT MAX(import_batch_id) FROM procurement_rfq_history").fetchone()[0]
        evidence = dict(as_of=self.as_of, tables=["commercial_order_history", "product_bom_snapshots", "products",
                        "production_shift_history", "procurement_rfq_history", "suppliers", "inventory_movements"],
                        window_weeks=self.cfg.policy["window_weeks"], caveats=CAVEATS)
        proposal = dict(lines=proposal_lines, total_est_cost_egp=total, total_cost_range_egp=[total_low, total_high], approval_required=role,
                        autonomy_level=self.cfg.policy["autonomy_level"], as_of=self.as_of)
        rec_id = wf.create_recommendation(self.con, self.env_id, "replenishment_alert", METHOD, batch,
                                          evidence, proposal, self.cfg.agent_actor)
        pr_id = wf.create_purchase_request(self.con, self.env_id, rec_id, lines, self.cfg.agent_actor)
        pr_no = self.con.execute("SELECT request_number FROM purchase_requests WHERE purchase_request_id=?",
                                 (pr_id,)).fetchone()[0]
        proposal["purchase_request_number"] = pr_no
        proposal["supplier_drafts"] = self._drafts(pr_no, proposal_lines)
        self.con.execute("UPDATE recommendations SET proposal_json=? WHERE recommendation_id=?",
                         (json.dumps(proposal, ensure_ascii=False), rec_id))
        result.update(recommendation_id=rec_id, purchase_request_id=pr_id, purchase_request_number=pr_no,
                      drafts=proposal["supplier_drafts"], total_est_cost_egp=total, total_cost_range_egp=[total_low, total_high], approval_required=role)
        return result

    def _drafts(self, pr_no, proposal_lines):
        by = {}
        for l in proposal_lines:
            by.setdefault((l["supplier_id"], l["supplier_name"]), []).append(l)
        drafts = {}
        for (sid, name), ls in by.items():
            msg_lines = [dict(material=l["material"], qty=l["qty"], unit=l["unit"],
                              needed_by=(pd.Timestamp(self.as_of) + pd.Timedelta(days=l["lead_days"])).date().isoformat())
                         for l in ls]
            drafts[sid] = {}
            for lang in ("en", "ar"):
                text, source = drafter.draft_message(name, pr_no, msg_lines, lang, self.llm)
                drafts[sid][lang] = dict(text=text, source=source)
        return drafts

    # ---------------------------------------------------------------- human steps
    def approve_request(self, pr_id, by, note="approved", approve=True):
        return wf.decide_purchase_request(self.con, pr_id, approve, by, note)

    def make_purchase_orders(self, pr_id, use_quotes=True):
        """One draft PO per supplier. Where a person has confirmed a supplier quote for a line, the best confirmed
        quote sets supplier, price and lead time; other lines keep the estimate from purchase history."""
        rec = self.con.execute("SELECT r.proposal_json FROM purchase_requests p JOIN recommendations r "
                               "USING(recommendation_id) WHERE p.purchase_request_id=?", (pr_id,)).fetchone()
        if rec is None:
            raise wf.WorkflowError("purchase request has no recommendation to source prices from")
        prop = json.loads(rec[0])
        sourcing = {l["stock_item_id"]: dict(l, price_piastres=l["price_piastres"], price_basis=l["price_basis"])
                    for l in prop["lines"]}
        chosen = quotes.selection(self.con, pr_id) if use_quotes else {}
        sourcing.update(chosen)
        po_ids = wf.create_purchase_orders(self.con, pr_id, sourcing, prop["as_of"], self.cfg.agent_actor)
        with store_tx(self.con):
            for po_id in po_ids:
                for (sid,) in self.con.execute("SELECT stock_item_id FROM purchase_order_lines WHERE purchase_order_id=?",
                                               (po_id,)).fetchall():
                    if sid in chosen:
                        self.con.execute("INSERT OR IGNORE INTO ext_po_quote_links(purchase_order_id,quote_id) VALUES (?,?)",
                                         (po_id, chosen[sid]["quote_id"]))
        return po_ids

    def send_purchase_order(self, po_id, by, mailer, at=None):
        """Email the approved PO to the supplier (dry run unless messaging mode is live) and start tracking it."""
        po = self.con.execute("SELECT * FROM purchase_orders WHERE purchase_order_id=?", (po_id,)).fetchone()
        if po is None:
            raise wf.WorkflowError("purchase order not found")
        if po["status"] != "approved":
            raise wf.WorkflowError(f"purchase order is {po['status']}; expected ('approved',)")
        name = self.con.execute("SELECT supplier_name FROM suppliers WHERE supplier_id=?", (po["supplier_id"],)).fetchone()[0]
        c = self.cfg.contacts.get(po["supplier_id"], {})
        lines = [dict(material=r["material_reference"].removeprefix("MAT:"), qty=r["quantity_base_units"],
                      unit=r["base_unit_snapshot"], delivery_date=r["expected_delivery_date"],
                      price_egp=r["quoted_price_piastres"] / 100 * (1000 / r["price_basis_quantity_base_units"]
                                                                    if r["base_unit_snapshot"] == "g" else
                                                                    1 / r["price_basis_quantity_base_units"]))
                 for r in self.con.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id=? "
                                           "ORDER BY line_number", (po_id,))]
        for l in lines:      # the supplier's own name/code, as in the RFQ
            l["supplier_name"], l["supplier_code"] = scraper.supplier_name_for(self.con, po["supplier_id"], l["material"])
        subject, body = drafter.po_message(name.split(" (")[0], po["po_number"], lines, c.get("language", "en"))
        if c.get("email"):
            st = mailer.send_email(self.con, "purchase_order", po["po_number"], c["email"], subject, body)
            if st == "failed":
                raise wf.WorkflowError("email failed; see ext_outbox.error")
            reason = "emailed to supplier" if st == "sent" else "DRY RUN: PO email written to outbox only"
        else:
            path = mailer.save_manual(self.con, "purchase_order", po["po_number"], c.get("website"), subject, body)
            reason = f"no supplier email configured: PO text saved for manual sending ({path})"
        wf.mark_purchase_order_sent(self.con, po_id, by, reason)
        tracking.record(self.con, po_id, "sent", by, at=at, source="agent", note=reason)
        return reason

    # ---------------------------------------------------------------- demo stock (sandbox only)
    def seed_demo_stock(self, maker="sandbox_seed", checker="sandbox_seed_approver"):
        """Gives the sandbox warehouse a starting stock of 0.4-3.0 weeks per material.
        Goes through the real chain (request -> approval -> PO -> send -> receipt) because the ledger only
        accepts a zero opening and positive stock arrives through goods receipts. DEMO DATA, not real stock."""
        assessments, ctx = self.analyze()
        lines, sourcing = [], {}
        for a in assessments:
            if a.status in ("NO_SUPPLIER", "NO_DEMAND"):
                continue
            sid = wf.ensure_stock_item(self.con, a.material, a.kind, a.unit)
            wf.ensure_opening(self.con, self.env_id, sid, self.loc_id, maker)
            h = int(hashlib.md5(a.material.encode()).hexdigest(), 16) % 260
            qty = int(a.mu_week * (0.4 + h / 100.0))
            if qty <= 0:
                continue
            src = ctx["src"].loc[a.material]
            lines.append(dict(stock_item_id=sid, qty=qty, note="DEMO SEED", policy=dict(method="demo_seed")))
            sourcing[sid] = dict(supplier_id=src["supplier_id"], rfq_id=int(src["rfq_id"]), material=a.material,
                                 unit=a.unit, price_piastres=int(src["price_piastres"]),
                                 price_basis=pl.KIND_UNIT[a.kind][1], lead_days=0)
        pr_id = wf.create_purchase_request(self.con, self.env_id, None, lines, maker)
        wf.decide_purchase_request(self.con, pr_id, True, checker, "demo seed")
        for po_id in wf.create_purchase_orders(self.con, pr_id, sourcing, self.as_of, maker):
            wf.approve_purchase_order(self.con, po_id, checker)
            wf.send_purchase_order_simulated(self.con, po_id, checker)
            wf.receive_purchase_order(self.con, po_id, self.loc_id, checker, delivery_ref="DEMO-SEED")
        return pr_id, len(lines)


# -------------------------------------------------------------------- report
def format_report(res: dict) -> str:
    out = [f"REPLENISHMENT REPORT  (data as of {res['as_of']}, environment {res['environment']})", ""]
    if res["alerts"]:
        out.append(f"{len(res['alerts'])} material(s) need ordering. Estimated cost {res.get('total_est_cost_egp', 0):,.0f} EGP (range {res['total_cost_range_egp'][0]:,.0f} - {res['total_cost_range_egp'][1]:,.0f}); "
                   f"approval: {res.get('approval_required', '-')}")
        out.append(f"{'severity':9} {'material':30} {'cover d':>7} {'lead d':>6} {'order qty':>14} {'supplier':10} {'order by':10} {'EGP':>11}")
        for a in res["alerts"]:
            q = f"{a.order_qty / 1000:,.0f} kg" if a.unit == "g" else f"{a.order_qty:,} pcs"
            out.append(f"{a.severity:9} {a.material[:30]:30} {a.cover_days:7.1f} {a.lead_days:6d} {q:>14} "
                       f"{a.supplier_id:10} {a.order_by:10} {a.est_cost_egp:11,.0f}")
    else:
        out.append("No material needs ordering.")
    if res.get("purchase_request_number"):
        out += ["", f"Draft purchase request {res['purchase_request_number']} created (waiting for a human decision)."]
    if res["unknown_stock"]:
        out += ["", f"Stock UNKNOWN (no opening balance, not assumed zero): {len(res['unknown_stock'])} materials"]
    if res["no_supplier"]:
        out += [f"No purchasing history, needs sourcing: {', '.join(res['no_supplier'][:6])}"
                f"{' ...' if len(res['no_supplier']) > 6 else ''} ({len(res['no_supplier'])} materials)"]
    out += ["", "Caveats: " + " | ".join(CAVEATS[:2])]
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True)
    p.add_argument("--env", default="replenishment_demo")
    p.add_argument("--as-of")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed"); sub.add_parser("run")
    for name in ("approve", "reject"):
        s = sub.add_parser(name); s.add_argument("--pr", type=int, required=True); s.add_argument("--by", required=True)
    s = sub.add_parser("po"); s.add_argument("--pr", type=int, required=True)
    s = sub.add_parser("po-approve"); s.add_argument("--po", type=int, required=True); s.add_argument("--by", required=True)
    s = sub.add_parser("po-send"); s.add_argument("--po", type=int, required=True); s.add_argument("--by", required=True)
    s.add_argument("--at", help="send date for the tracking clock (default: now)")
    s.add_argument("--simulated", action="store_true", help="old behaviour: status change only, no message")
    ops.register(sub)
    a = p.parse_args(argv)
    ag = ReplenishmentAgent(Config(db_path=a.db, environment=a.env, as_of=a.as_of))
    if a.cmd == "seed":
        pr, n = ag.seed_demo_stock(); print(f"demo stock created for {n} materials (request {pr})")
    elif a.cmd == "run":
        res = ag.run(); print(format_report(res))
        for sid, d in res["drafts"].items():
            print(f"\n--- draft message for {sid} (en, source={d['en']['source']}) ---\n{d['en']['text']}")
        print(f"\nrestock alerts sent: {ops.services(ag)[1].restock(res)}")
    elif a.cmd in ("approve", "reject"):
        print(ag.approve_request(a.pr, a.by, approve=a.cmd == "approve"))
    elif a.cmd == "po":
        print("draft purchase orders:", ag.make_purchase_orders(a.pr))
    elif a.cmd == "po-approve":
        wf.approve_purchase_order(ag.con, a.po, a.by); print("approved")
    elif a.cmd == "po-send" and a.simulated:
        wf.send_purchase_order_simulated(ag.con, a.po, a.by); print("sent (SIMULATED, nothing transmitted)")
    elif a.cmd == "po-send":
        print(ag.send_purchase_order(a.po, a.by, ops.services(ag)[0], at=a.at))
    else:
        ops.handle(a, ag)


if __name__ == "__main__":
    try:
        main()
    except (wf.WorkflowError, rfq.RFQError, quotes.QuoteError, tracking.TrackingError) as e:   # a rule refused
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(1)
