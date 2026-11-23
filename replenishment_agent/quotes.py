"""Supplier replies -> prices.

1. ingest(): the reply text (email, pasted text, or typed from a phone call) is stored as it is.
2. Prices, MOQ, lead time and validity are extracted per RFQ line:
     - deterministic parser (works best when the supplier keeps our "item | price | MOQ | lead | valid" format)
     - optional LLM extractor; its output is REJECTED if it holds any number not present in the reply
3. A person checks and confirms the quote (maker != checker). Only confirmed quotes are used.
4. compare() ranks the confirmed offers per material; selection() feeds the best ones into the purchase order.
"""
from __future__ import annotations
import json, os, re

import scraper
from db import now_utc, tx

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")
NUM = r"(\d[\d,]*(?:\.\d+)?)"
CUR = r"(?:EGP|LE|L\.E\.?|جنيه|ج\.م)(?![a-z])"
PRICE = re.compile(CUR + r"\s*" + NUM + r"|" + NUM + r"\s*" + CUR, re.I)
PRICE_LABEL = re.compile(r"(?:unit price|price|سعر(?: الوحدة)?)\s*[:=]?\s*(?:EGP|LE|جنيه)?\s*" + NUM, re.I)
LEAD = re.compile(NUM + r"\s*(?:working\s+)?(?:days?|يوم|أيام|ايام)", re.I)
MOQ = re.compile(r"(?:MOQ|minimum(?: order)?(?: quantity)?|أقل كمية|اقل كمية|الحد الأدنى)\s*[:=]?\s*" + NUM
                 + r"\s*(kg|kgs|ton|tons|طن|كجم|كيلو|pcs|pieces|piece|قطعة)?", re.I)
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})|(\d{1,2})/(\d{1,2})/(\d{4})")
DECLINE = re.compile(r"regret|unable to (?:quote|supply)|not available|out of stock|نعتذر|غير متوفر|لا يتوفر", re.I)


class QuoteError(Exception):
    pass


def _num(s):
    return float(s.replace(",", ""))


def _basis(text: str, unit: str) -> int:
    t = text.lower()
    if unit == "g":
        if re.search(r"per\s*(?:metric\s*)?ton|/\s*ton|للطن|لكل طن|/\s*طن", t):
            return 1_000_000
        if re.search(r"per\s*g(?:ram)?\b|/\s*g\b", t):
            return 1
        return 1000                                  # default per kg
    m = re.search(r"per\s*(1,?000|thousand)|/\s*1,?000|لكل\s*(?:1000|ألف|الف)", t)
    return 1000 if m else 1


def _moq_base(value: float, unit_word: str | None, unit: str) -> int:
    w = (unit_word or "").lower()
    if unit == "g":
        return int(value * (1_000_000 if w in ("ton", "tons", "طن") else 1000))
    return int(value)


def _date(text):
    m = DATE.search(text)
    if not m:
        return None
    if m.group(1):
        return m.group(1)
    d, mo, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_reply(text: str, rfq_lines: list) -> list[dict]:
    """Deterministic extraction. One result per RFQ line whose material is clearly named next to a price."""
    text = text.translate(AR_DIGITS)
    out, used = [], set()
    for raw in text.splitlines():
        line = raw.strip(" -*\t>")
        if not line or not re.search(r"\d", line):
            continue
        head = line.split("|")[0] if "|" in line else line
        scored = sorted(((scraper.name_score(head, l["material"], l.get("supplier_product_name"),
                                             l.get("supplier_product_code")), l) for l in rfq_lines
                         if l["rfq_line_id"] not in used), key=lambda x: -x[0])
        if not scored or scored[0][0] < 0.6:
            continue
        rl = scored[0][1]
        rest = line[len(head):] if "|" in line else line
        m = PRICE_LABEL.search(rest) or PRICE.search(rest)
        if not m:
            continue
        price = _num(next(g for g in m.groups() if g))
        if price <= 0:
            continue
        lead = LEAD.search(rest)
        moq = MOQ.search(rest)
        out.append(dict(rfq_line_id=rl["rfq_line_id"], unit_price_piastres=int(round(price * 100)),
                        price_basis_base_units=_basis(rest, rl["unit"]),
                        moq_base_units=_moq_base(_num(moq.group(1)), moq.group(2), rl["unit"]) if moq else None,
                        lead_days=int(_num(lead.group(1))) if lead else None,
                        valid_until=_date(rest.split("valid")[-1] if "valid" in rest.lower() else rest),
                        evidence=raw.strip()[:300]))
        used.add(rl["rfq_line_id"])
    return out


def _llm_extract(text, rfq_lines, llm):
    """LLM proposes the same structure; rejected if it contains a number that is not in the reply."""
    items = [dict(rfq_line_id=l["rfq_line_id"], material=l["material"],
                  price_unit=("kg" if l["unit"] == "g" else "piece")) for l in rfq_lines]
    prompt = ("Extract the supplier's offer from this email. Return ONLY a JSON list, one object per item that has a "
              "price: {\"rfq_line_id\": int, \"unit_price_egp\": number, \"price_per\": \"kg\"|\"ton\"|\"piece\"|"
              "\"1000 pieces\", \"moq\": number|null, \"moq_unit\": \"kg\"|\"ton\"|\"pcs\"|null, "
              "\"lead_days\": int|null, \"valid_until\": \"YYYY-MM-DD\"|null}. Copy numbers exactly as written. "
              "Skip items without a price.\n\nItems: " + json.dumps(items) + "\n\nEmail:\n" + text)
    raw = llm(prompt)
    data = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
    src_nums = {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", text.translate(AR_DIGITS))}
    by_id = {l["rfq_line_id"]: l for l in rfq_lines}
    out = []
    for d in data:
        for k in ("unit_price_egp", "moq", "lead_days"):
            v = d.get(k)
            if v is not None and f"{v:g}" not in src_nums and str(v) not in src_nums:
                raise ValueError(f"LLM produced a number not in the reply: {v}")
        rl = by_id[int(d["rfq_line_id"])]
        per = d.get("price_per") or ""
        basis = {"ton": 1_000_000, "kg": 1000, "1000 pieces": 1000}.get(per, 1000 if rl["unit"] == "g" else 1)
        out.append(dict(rfq_line_id=rl["rfq_line_id"], unit_price_piastres=int(round(float(d["unit_price_egp"]) * 100)),
                        price_basis_base_units=basis,
                        moq_base_units=_moq_base(float(d["moq"]), d.get("moq_unit"), rl["unit"]) if d.get("moq") else None,
                        lead_days=d.get("lead_days"), valid_until=d.get("valid_until"), evidence="llm"))
    return out


def _call_claude(prompt):                          # pragma: no cover (needs an API key)
    import anthropic
    msg = anthropic.Anthropic().messages.create(model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5"),
                                                max_tokens=1500, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "text", None))


def rfq_lines(con, rfq_id):
    return [dict(r) for r in con.execute("SELECT * FROM ext_rfq_lines WHERE rfq_id=?", (rfq_id,))]


def ingest(con, rfq_id, text, source="email", received_at=None, actor="replenishment_agent", llm=None) -> dict:
    rfq = con.execute("SELECT * FROM ext_rfqs WHERE rfq_id=?", (rfq_id,)).fetchone()
    if rfq is None:
        raise QuoteError("RFQ not found")
    lines = rfq_lines(con, rfq_id)
    parsed, method = parse_reply(text, lines), "parser"
    if llm is None and os.environ.get("ANTHROPIC_API_KEY"):
        llm = _call_claude
    if llm is not None and len(parsed) < len(lines):
        try:
            got = _llm_extract(text, lines, llm)
            if len(got) > len(parsed):
                parsed, method = got, "llm_checked"
        except Exception:
            pass                                    # guardrail or error: keep the deterministic result
    declined = not parsed and bool(DECLINE.search(text))
    with tx(con):
        cur = con.execute("INSERT INTO ext_quotes(rfq_id,received_at_utc,source,raw_text,extracted_by,extraction_method,"
                          "status) VALUES (?,?,?,?,?,?,'extracted')",
                          (rfq_id, received_at or now_utc(), source, text, actor, method))
        qid = cur.lastrowid
        for p in parsed:
            con.execute("INSERT INTO ext_quote_lines(quote_id,rfq_line_id,unit_price_piastres,price_basis_base_units,"
                        "moq_base_units,lead_days,valid_until,evidence) VALUES (?,?,?,?,?,?,?,?)",
                        (qid, p["rfq_line_id"], p["unit_price_piastres"], p["price_basis_base_units"],
                         p["moq_base_units"], p["lead_days"], p["valid_until"], p["evidence"]))
        new = "declined" if declined else "quoted"
        if rfq["status"] in ("sent", "approved", "quoted"):
            con.execute("UPDATE ext_rfqs SET status=? WHERE rfq_id=?", (new, rfq_id))
            con.execute("INSERT INTO ext_rfq_events(rfq_id,event_at_utc,actor,new_status,reason) VALUES (?,?,?,?,?)",
                        (rfq_id, now_utc(), actor, new, f"reply received ({source}), {len(parsed)} priced line(s)"))
    return dict(quote_id=qid, lines=len(parsed), of=len(lines), method=method, declined=declined)


def add_line(con, quote_id, rfq_line_id, price_egp, per, moq=None, lead_days=None, valid_until=None):
    """Manual entry (phone call, PDF quote). per: kg | ton | piece | 1000"""
    q = con.execute("SELECT status FROM ext_quotes WHERE quote_id=?", (quote_id,)).fetchone()
    if q is None or q[0] != "extracted":
        raise QuoteError("quote must exist and not be decided yet")
    unit = con.execute("SELECT unit FROM ext_rfq_lines WHERE rfq_line_id=?", (rfq_line_id,)).fetchone()[0]
    basis = {"kg": 1000, "ton": 1_000_000, "piece": 1, "1000": 1000}[per]
    with tx(con):
        con.execute("DELETE FROM ext_quote_lines WHERE quote_id=? AND rfq_line_id=?", (quote_id, rfq_line_id))
        con.execute("INSERT INTO ext_quote_lines(quote_id,rfq_line_id,unit_price_piastres,price_basis_base_units,"
                    "moq_base_units,lead_days,valid_until,evidence) VALUES (?,?,?,?,?,?,?,?)",
                    (quote_id, rfq_line_id, int(round(price_egp * 100)), basis,
                     _moq_base(moq, "kg" if unit == "g" else "pcs", unit) if moq else None, lead_days, valid_until,
                     "manual entry"))


def decide(con, quote_id, by, confirm=True, note=""):
    q = con.execute("SELECT * FROM ext_quotes WHERE quote_id=?", (quote_id,)).fetchone()
    if q is None:
        raise QuoteError("quote not found")
    if q["status"] != "extracted":
        raise QuoteError(f"quote already {q['status']}")
    if by == q["extracted_by"]:
        raise QuoteError("maker and checker must be different people")
    if confirm and not con.execute("SELECT 1 FROM ext_quote_lines WHERE quote_id=?", (quote_id,)).fetchone():
        raise QuoteError("quote has no priced lines; add them first (quote add-line)")
    with tx(con):
        con.execute("UPDATE ext_quotes SET status=?, decided_by=?, decided_at_utc=? WHERE quote_id=?",
                    ("confirmed" if confirm else "rejected", by, now_utc(), quote_id))


# ------------------------------------------------------------------ comparison
def offers(con, pr_id) -> list[dict]:
    rows = con.execute("""
        SELECT rl.purchase_request_line_id, rl.stock_item_id, rl.material, rl.unit, rl.qty_base_units qty, rl.needed_by,
               r.rfq_id, r.rfq_number, r.supplier_id, r.created_at_utc, q.quote_id, q.received_at_utc,
               ql.unit_price_piastres, ql.price_basis_base_units, ql.moq_base_units, ql.lead_days, ql.valid_until,
               l.quantity_policy_json
        FROM ext_quote_lines ql JOIN ext_quotes q USING(quote_id) JOIN ext_rfq_lines rl USING(rfq_line_id)
        JOIN ext_rfqs r ON r.rfq_id=rl.rfq_id
        JOIN purchase_request_lines l ON l.purchase_request_line_id=rl.purchase_request_line_id
        WHERE r.purchase_request_id=? AND q.status='confirmed'
        ORDER BY q.quote_id""", (pr_id,)).fetchall()
    latest = {}
    for r in rows:                                   # newest confirmed quote per (line, supplier)
        latest[(r["purchase_request_line_id"], r["supplier_id"])] = dict(r)
    out = []
    for o in latest.values():
        o["total_egp"] = round(o["qty"] / o["price_basis_base_units"] * o["unit_price_piastres"] / 100, 2)
        need_days = o["need_days"] = json.loads(o.pop("quantity_policy_json")).get("lead_days")
        o["meets_date"] = o["lead_days"] is None or need_days is None or o["lead_days"] <= need_days
        o["meets_moq"] = o["moq_base_units"] is None or o["qty"] >= o["moq_base_units"]
        out.append(o)
    out.sort(key=lambda o: (o["material"], not (o["meets_date"] and o["meets_moq"]), o["total_egp"]))
    return out


def selection(con, pr_id) -> dict:
    """Best confirmed offer per purchase-request line: on time and above MOQ first, then cheapest."""
    best = {}
    for o in offers(con, pr_id):
        best.setdefault(o["purchase_request_line_id"], o)
    return {o["stock_item_id"]: dict(supplier_id=o["supplier_id"], rfq_id=None, quote_id=o["quote_id"],
                                     price_piastres=o["unit_price_piastres"], price_basis=o["price_basis_base_units"],
                                     lead_days=o["lead_days"] if o["lead_days"] is not None else (o["need_days"] or 0),
                                     material=o["material"], unit=o["unit"])
            for o in best.values()}
