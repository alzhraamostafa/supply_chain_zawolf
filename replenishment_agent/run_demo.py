"""One-command demo of the whole flow on a TEMPORARY COPY of the database.

  python run_demo.py --db smart_supply_chain_simulation_v5_recovered_review1.db
  python run_demo.py --db <file>.db --keep work.db      # also keep the working copy to inspect
"""
import argparse, os, shutil, sys, tempfile

import workflow as wf
from agent import ReplenishmentAgent, format_report
from config import Config


def step(n, text):
    print(f"\n{'=' * 78}\nSTEP {n}: {text}\n{'=' * 78}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="original database (it is never modified)")
    ap.add_argument("--keep", help="save the working copy here instead of deleting it")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp()
    work = os.path.join(tmp, "work.db")
    shutil.copy(a.db, work)
    ag = ReplenishmentAgent(Config(db_path=work))

    step(1, "Before any stock exists, the agent must NOT order (stock is unknown, not zero)")
    r0 = ag.run()
    print(f"alerts: {len(r0['alerts'])}   materials with unknown stock: {len(r0['unknown_stock'])}")

    step(2, "Give the sandbox warehouse a demo starting stock (invented data)")
    pr, n = ag.seed_demo_stock()
    print(f"demo stock created for {n} materials")

    step(3, "Agent run: alerts, draft purchase request, draft supplier messages")
    res = ag.run()
    print(format_report(res))
    sid = next(iter(res["drafts"]))
    for lang in ("en", "ar"):
        d = res["drafts"][sid][lang]
        print(f"\n--- draft message to {sid} ({lang}, source={d['source']}) ---\n{d['text']}")
    pr_id = res["purchase_request_id"]

    step(4, "Rules: the agent cannot approve its own request")
    try:
        ag.approve_request(pr_id, by=ag.cfg.agent_actor)
    except wf.WorkflowError as e:
        print(f"REFUSED: {e}")

    step(5, "Human 1 approves the purchase request; the agent drafts one PO per supplier")
    print("decision:", ag.approve_request(pr_id, by="procurement_manager"))
    pos = ag.make_purchase_orders(pr_id)
    print("draft purchase orders:", pos)

    step(6, "Human 2 approves the PO; the send is SIMULATED")
    po = pos[0]
    try:
        wf.approve_purchase_order(ag.con, po, ag.cfg.agent_actor)
    except wf.WorkflowError as e:
        print(f"REFUSED: {e}")
    wf.approve_purchase_order(ag.con, po, "finance_checker")
    wf.send_purchase_order_simulated(ag.con, po, "finance_checker")
    for row in ag.con.execute("SELECT actor_reference, new_status, reason FROM purchase_order_events "
                              "WHERE purchase_order_id=? ORDER BY event_id", (po,)):
        print(f"  {row[0]:22} -> {row[1]:10} {row[2]}")

    step(7, "Run again: open requests and orders count as supply, so nothing is duplicated")
    r2 = ag.run()
    print(f"new alerts: {len(r2['alerts'])}   new request created: {r2['purchase_request_id']}")

    step(8, "Goods arrive (simulated): stock rises through the ledger")
    for p in pos:
        if p != po:
            wf.approve_purchase_order(ag.con, p, "finance_checker")
            wf.send_purchase_order_simulated(ag.con, p, "finance_checker")
    for p in pos:
        wf.receive_purchase_order(ag.con, p, ag.loc_id, "warehouse_user")
    r3 = ag.run()
    print(f"alerts after receipt: {len(r3['alerts'])}")

    if a.keep:
        ag.con.close()
        shutil.copy(work, a.keep)
        print(f"\nworking copy saved to {a.keep}")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
 