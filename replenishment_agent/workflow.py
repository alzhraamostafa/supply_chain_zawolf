"""All writes to the simulation tables. History tables are sealed and never touched.

Rules enforced here (the database enforces most of them too, with triggers):
  * every row carries environment_id and an actor
  * stock is a ledger: opening (zero) -> receipts only; no opening = stock UNKNOWN
  * maker != checker for purchase requests and purchase orders
  * a purchase order can only come from an APPROVED purchase request
  * "send" is simulated: status + audit event, nothing leaves the system
"""
from __future__ import annotations
import hashlib, json
from datetime import date, timedelta

from db import now_utc, tx

OPEN_PO_STATUSES = ("draft", "approved", "sent", "partially_received")


class WorkflowError(Exception):
    pass


# ------------------------------------------------------------ environment / master data
def ensure_environment(con, name, created_by, provenance) -> int:
    row = con.execute("SELECT environment_id FROM simulation_environments WHERE name=?", (name,)).fetchone()
    if row:
        return row[0]
    with tx(con):
        cur = con.execute("INSERT INTO simulation_environments(name,created_at_utc,created_by,provenance) "
                          "VALUES (?,?,?,?)", (name, now_utc(), created_by, provenance))
    return cur.lastrowid


def ensure_location(con, env_id, name) -> int:
    row = con.execute("SELECT location_id FROM stock_locations WHERE environment_id=? AND location_name=?",
                      (env_id, name)).fetchone()
    if row:
        return row[0]
    with tx(con):
        cur = con.execute("INSERT INTO stock_locations(location_name,created_at_utc,environment_id) VALUES (?,?,?)",
                          (name, now_utc(), env_id))
    return cur.lastrowid


def ensure_stock_item(con, material, kind, unit) -> int:
    row = con.execute("SELECT stock_item_id FROM stock_items WHERE identity_reference=?", (material,)).fetchone()
    if row:
        return row[0]
    with tx(con):
        cur = con.execute("INSERT INTO stock_items(item_name,base_unit,material_reference,created_at_utc,"
                          "component_type,identity_reference) VALUES (?,?,?,?,?,?)",
                          (material, unit, f"MAT:{material}", now_utc(), kind, material))
    return cur.lastrowid


# ------------------------------------------------------------ ledger
def ensure_opening(con, env_id, stock_item_id, location_id, actor):
    """The ledger only accepts a ZERO opening. Positive stock arrives through goods receipts."""
    exists = con.execute("SELECT 1 FROM inventory_movements WHERE environment_id=? AND stock_item_id=? "
                         "AND location_id=? AND movement_kind='opening'",
                         (env_id, stock_item_id, location_id)).fetchone()
    if exists:
        return
    with tx(con):
        con.execute("INSERT INTO inventory_movements(stock_item_id,location_id,occurred_at_utc,movement_kind,"
                    "quantity_delta_base_units,reason,evidence_reference,actor_reference,idempotency_key,environment_id)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (stock_item_id, location_id, now_utc(), "opening", 0, "explicit zero opening",
                     "sandbox opening", actor, f"open:{env_id}:{stock_item_id}:{location_id}", env_id))


def stock_on_hand(con, env_id, stock_item_id, location_id):
    """None = UNKNOWN (no opening record). Never treat unknown as zero."""
    has_open = con.execute("SELECT 1 FROM inventory_movements WHERE environment_id=? AND stock_item_id=? "
                           "AND location_id=? AND movement_kind='opening'",
                           (env_id, stock_item_id, location_id)).fetchone()
    if not has_open:
        return None
    return con.execute("SELECT COALESCE(SUM(quantity_delta_base_units),0) FROM inventory_movements "
                       "WHERE environment_id=? AND stock_item_id=? AND location_id=?",
                       (env_id, stock_item_id, location_id)).fetchone()[0]


def open_supply(con, env_id, stock_item_id) -> int:
    """Quantity already on its way: open PO lines (minus received) + purchase request lines not yet in a PO."""
    marks = ",".join("?" * len(OPEN_PO_STATUSES))
    po = con.execute(f"""SELECT COALESCE(SUM(pl.quantity_base_units - COALESCE(
                 (SELECT SUM(rl.accepted_quantity_base_units) FROM goods_receipt_lines rl
                  WHERE rl.purchase_order_line_id=pl.purchase_order_line_id),0)),0)
             FROM purchase_order_lines pl JOIN purchase_orders p USING(purchase_order_id)
             WHERE p.environment_id=? AND pl.stock_item_id=? AND p.status IN ({marks})""",
                     (env_id, stock_item_id, *OPEN_PO_STATUSES)).fetchone()[0]
    pr = con.execute("""SELECT COALESCE(SUM(l.requested_quantity_base_units),0)
             FROM purchase_request_lines l JOIN purchase_requests r USING(purchase_request_id)
             WHERE r.environment_id=? AND l.stock_item_id=? AND r.status IN ('draft','approved')
               AND NOT EXISTS (SELECT 1 FROM purchase_order_lines pl
                               WHERE pl.purchase_request_line_id=l.purchase_request_line_id)""",
                     (env_id, stock_item_id)).fetchone()[0]
    return po + pr


# ------------------------------------------------------------ recommendation + purchase request
def create_recommendation(con, env_id, rec_type, method_version, import_batch_id, evidence, proposal, actor):
    with tx(con):
        cur = con.execute("INSERT INTO recommendations(created_at_utc,recommendation_type,status,method_version,"
                          "evidence_import_batch_id,evidence_json,proposal_json,environment_id) VALUES (?,?,?,?,?,?,?,?)",
                          (now_utc(), rec_type, "draft", method_version, import_batch_id,
                           json.dumps(evidence, ensure_ascii=False), json.dumps(proposal, ensure_ascii=False), env_id))
        rec_id = cur.lastrowid
        con.execute("INSERT INTO recommendation_events(recommendation_id,event_at_utc,actor_reference,new_status,reason)"
                    " VALUES (?,?,?,?,?)", (rec_id, now_utc(), actor, "draft", "created by agent"))
    return rec_id


def create_purchase_request(con, env_id, rec_id, lines, actor) -> int:
    """lines: dicts with stock_item_id, qty, note, policy (dict). Created as DRAFT."""
    if not lines:
        raise WorkflowError("no lines")
    with tx(con):
        n = con.execute("SELECT COALESCE(MAX(purchase_request_id),0)+1 FROM purchase_requests").fetchone()[0]
        cur = con.execute("INSERT INTO purchase_requests(request_number,recommendation_id,requested_at_utc,"
                          "requested_by,status,environment_id) VALUES (?,?,?,?,?,?)",
                          (f"PR-{env_id}-{n:05d}", rec_id, now_utc(), actor, "draft", env_id))
        pr_id = cur.lastrowid
        for ln in lines:
            con.execute("INSERT INTO purchase_request_lines(purchase_request_id,stock_item_id,"
                        "requested_quantity_base_units,source_note,quantity_policy_json) VALUES (?,?,?,?,?)",
                        (pr_id, ln["stock_item_id"], int(ln["qty"]), ln.get("note"),
                         json.dumps(ln["policy"], ensure_ascii=False)))
    return pr_id


def decide_purchase_request(con, pr_id, approve: bool, by: str, note: str):
    """Human decision. The checker must be a different person from the maker."""
    pr = con.execute("SELECT * FROM purchase_requests WHERE purchase_request_id=?", (pr_id,)).fetchone()
    if pr is None:
        raise WorkflowError("purchase request not found")
    if pr["status"] != "draft":
        raise WorkflowError(f"request already {pr['status']}")
    if by == pr["requested_by"]:
        raise WorkflowError("maker and checker must be different people")
    status = "approved" if approve else "rejected"
    with tx(con):
        con.execute("UPDATE purchase_requests SET status=?,decision_note=?,decided_by=?,decided_at_utc=? "
                    "WHERE purchase_request_id=?", (status, note, by, now_utc(), pr_id))
        if pr["recommendation_id"]:
            con.execute("UPDATE recommendations SET status=? WHERE recommendation_id=?",
                        (status, pr["recommendation_id"]))
            con.execute("INSERT INTO recommendation_events(recommendation_id,event_at_utc,actor_reference,new_status,reason)"
                        " VALUES (?,?,?,?,?)", (pr["recommendation_id"], now_utc(), by, status, note))
    return status


# ------------------------------------------------------------ purchase orders
def create_purchase_orders(con, pr_id, sourcing_by_stock_item: dict, as_of: str, actor: str):
    """One DRAFT purchase order per supplier from an APPROVED purchase request.
    sourcing_by_stock_item[stock_item_id] = dict(supplier_id, rfq_id, price_piastres, price_basis,
                                                 lead_days, material, unit)"""
    pr = con.execute("SELECT * FROM purchase_requests WHERE purchase_request_id=?", (pr_id,)).fetchone()
    if pr is None or pr["status"] != "approved":
        raise WorkflowError("purchase request must be APPROVED before a purchase order is drafted")
    lines = con.execute("SELECT * FROM purchase_request_lines WHERE purchase_request_id=?", (pr_id,)).fetchall()
    ids = [l["purchase_request_line_id"] for l in lines]
    taken = {r[0] for r in con.execute(
        f"SELECT purchase_request_line_id FROM purchase_order_lines WHERE purchase_request_line_id IN ({','.join('?'*len(ids))})",
        ids)} if ids else set()
    by_supplier: dict[str, list] = {}
    for ln in lines:
        if ln["purchase_request_line_id"] in taken:
            continue
        s = sourcing_by_stock_item[ln["stock_item_id"]]
        by_supplier.setdefault(s["supplier_id"], []).append((ln, s))
    po_ids = []
    with tx(con):
        for supplier_id, items in by_supplier.items():
            n = con.execute("SELECT COALESCE(MAX(purchase_order_id),0)+1 FROM purchase_orders").fetchone()[0]
            cur = con.execute("INSERT INTO purchase_orders(po_number,supplier_id,created_at_utc,status,recommendation_id,"
                              "source_rfq_id,currency_code,environment_id) VALUES (?,?,?,?,?,?,?,?)",
                              (f"PO-{pr['environment_id']}-{n:05d}", supplier_id, now_utc(), "draft",
                               pr["recommendation_id"], items[0][1]["rfq_id"], "EGP", pr["environment_id"]))
            po_id = cur.lastrowid
            for i, (ln, s) in enumerate(items, 1):
                eta = (date.fromisoformat(as_of) + timedelta(days=int(s["lead_days"]))).isoformat()
                con.execute("INSERT INTO purchase_order_lines(purchase_order_id,line_number,material_reference,"
                            "quantity_base_units,base_unit_snapshot,quoted_price_piastres,stock_item_id,"
                            "purchase_request_line_id,price_basis_quantity_base_units,expected_delivery_date)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (po_id, i, f"MAT:{s['material']}", ln["requested_quantity_base_units"], s["unit"],
                             int(s["price_piastres"]), ln["stock_item_id"], ln["purchase_request_line_id"],
                             int(s["price_basis"]), eta))
            con.execute("INSERT INTO purchase_order_events(purchase_order_id,event_at_utc,actor_reference,new_status,reason)"
                        " VALUES (?,?,?,?,?)", (po_id, now_utc(), actor, "draft", f"drafted from {pr['request_number']}"))
            po_ids.append(po_id)
    return po_ids


def _po_status_change(con, po_id, new_status, by, reason, allowed_from, checker_must_differ=False):
    po = con.execute("SELECT * FROM purchase_orders WHERE purchase_order_id=?", (po_id,)).fetchone()
    if po is None:
        raise WorkflowError("purchase order not found")
    if po["status"] not in allowed_from:
        raise WorkflowError(f"purchase order is {po['status']}; expected {allowed_from}")
    if checker_must_differ:
        maker = con.execute("SELECT actor_reference FROM purchase_order_events WHERE purchase_order_id=? "
                            "AND new_status='draft' ORDER BY event_id LIMIT 1", (po_id,)).fetchone()[0]
        if by == maker:
            raise WorkflowError("maker and checker must be different people")
    with tx(con):
        con.execute("UPDATE purchase_orders SET status=? WHERE purchase_order_id=?", (new_status, po_id))
        con.execute("INSERT INTO purchase_order_events(purchase_order_id,event_at_utc,actor_reference,new_status,reason)"
                    " VALUES (?,?,?,?,?)", (po_id, now_utc(), by, new_status, reason))


def approve_purchase_order(con, po_id, by, note="approved"):
    _po_status_change(con, po_id, "approved", by, note, ("draft",), checker_must_differ=True)


def send_purchase_order_simulated(con, po_id, by):
    """SIMULATED send: records the status and an audit event. Nothing is transmitted anywhere."""
    _po_status_change(con, po_id, "sent", by, "SIMULATED SEND - no external transmission", ("approved",))


def receive_purchase_order(con, po_id, location_id, by, accepted: dict | None = None, delivery_ref="SIM-DELIVERY"):
    """Simulated delivery. accepted = {po_line_id: qty}; default = full quantity. Posts ledger receipts."""
    po = con.execute("SELECT * FROM purchase_orders WHERE purchase_order_id=?", (po_id,)).fetchone()
    if po["status"] not in ("sent", "partially_received"):
        raise WorkflowError(f"purchase order is {po['status']}; it must be sent before receiving")
    lines = con.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id=?", (po_id,)).fetchall()
    plan = []
    for ln in lines:
        already = con.execute("SELECT COALESCE(SUM(accepted_quantity_base_units),0) FROM goods_receipt_lines "
                              "WHERE purchase_order_line_id=?", (ln["purchase_order_line_id"],)).fetchone()[0]
        qty = (accepted or {}).get(ln["purchase_order_line_id"], ln["quantity_base_units"] - already)
        if qty > 0:
            plan.append((ln, int(qty), already))
    if not plan:
        raise WorkflowError("nothing to receive")
    payload = json.dumps([(l["purchase_order_line_id"], q) for l, q, _ in plan], sort_keys=True)
    sha = hashlib.sha256(f"{po_id}:{payload}".encode()).hexdigest()
    with tx(con):
        cur = con.execute("INSERT INTO goods_receipts(purchase_order_id,received_at_utc,received_by,status,"
                          "idempotency_key,delivery_reference,environment_id,request_sha256) VALUES (?,?,?,?,?,?,?,?)",
                          (po_id, now_utc(), by, "draft", f"recv:{po_id}:{sha[:16]}", delivery_ref,
                           po["environment_id"], sha))
        gr_id = cur.lastrowid
        for ln, qty, _ in plan:
            c2 = con.execute("INSERT INTO goods_receipt_lines(goods_receipt_id,purchase_order_line_id,"
                             "accepted_quantity_base_units,rejected_quantity_base_units,location_id) VALUES (?,?,?,?,?)",
                             (gr_id, ln["purchase_order_line_id"], qty, 0, location_id))
            con.execute("INSERT INTO inventory_movements(stock_item_id,location_id,occurred_at_utc,movement_kind,"
                        "quantity_delta_base_units,receipt_line_id,reason,evidence_reference,actor_reference,"
                        "idempotency_key,environment_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (ln["stock_item_id"], location_id, now_utc(), "receipt", qty, c2.lastrowid,
                         "simulated goods receipt", f"GR:{gr_id}", by, f"mv:{gr_id}:{c2.lastrowid}",
                         po["environment_id"]))
        con.execute("UPDATE goods_receipts SET status='posted' WHERE goods_receipt_id=?", (gr_id,))
        got = {l["purchase_order_line_id"]: already + q for l, q, already in plan}
        full = True
        for l in lines:
            done = got.get(l["purchase_order_line_id"])
            if done is None:   # line not in this receipt: check what was received earlier
                done = con.execute("SELECT COALESCE(SUM(accepted_quantity_base_units),0) FROM goods_receipt_lines "
                                   "WHERE purchase_order_line_id=?", (l["purchase_order_line_id"],)).fetchone()[0]
            full = full and done >= l["quantity_base_units"]
        new_status = "received" if full else "partially_received"
        con.execute("UPDATE purchase_orders SET status=? WHERE purchase_order_id=?", (new_status, po_id))
        con.execute("INSERT INTO purchase_order_events(purchase_order_id,event_at_utc,actor_reference,new_status,reason)"
                    " VALUES (?,?,?,?,?)", (po_id, now_utc(), by, new_status, f"goods receipt {gr_id}"))
    return gr_id
