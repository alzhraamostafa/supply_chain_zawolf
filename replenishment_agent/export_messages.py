"""Writes the draft supplier messages from a demo database to supplier_messages.html (and .txt).
The Windows terminal cannot draw Arabic correctly (letters come out reversed and separated).
A browser can, so open the .html file instead.

  python export_messages.py --db work.db
"""
import argparse, html, json, sqlite3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="supplier_messages")
    a = ap.parse_args()
    con = sqlite3.connect(a.db)
    row = con.execute("SELECT recommendation_id, proposal_json FROM recommendations "
                      "WHERE recommendation_type='replenishment_alert' ORDER BY recommendation_id DESC LIMIT 1").fetchone()
    if row is None:
        raise SystemExit("No recommendation found. Run the demo first (python run_demo.py --db ... --keep work.db).")
    rec_id, proposal = row[0], json.loads(row[1])
    drafts = proposal.get("supplier_drafts", {})
    names = {r[0]: r[1] for r in con.execute("SELECT supplier_id, supplier_name FROM suppliers")}

    parts, txt = [], []
    for sid, d in drafts.items():
        parts.append(f"<section><h2>{html.escape(sid)} &mdash; {html.escape(names.get(sid, ''))}</h2>"
                     f"<h3>English <small>(source: {d['en']['source']})</small></h3>"
                     f"<pre dir='ltr'>{html.escape(d['en']['text'])}</pre>"
                     f"<h3>العربية <small>(source: {d['ar']['source']})</small></h3>"
                     f"<pre dir='rtl' lang='ar'>{html.escape(d['ar']['text'])}</pre></section>")
        txt += [f"=== {sid} ===", d["en"]["text"], "", d["ar"]["text"], ""]
    page = ("<!doctype html><html><head><meta charset='utf-8'><title>Draft supplier messages</title><style>"
            "body{font-family:Segoe UI,Tahoma,Arial,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#222}"
            "pre{white-space:pre-wrap;font:inherit;background:#f4f4f6;padding:1rem;border-radius:8px;line-height:1.7}"
            "section{border-top:2px solid #ddd;margin-top:2rem}small{color:#777;font-weight:normal}"
            ".note{background:#fff7e0;padding:.8rem 1rem;border-radius:8px}"
            "@media(prefers-color-scheme:dark){body{background:#1b1b1f;color:#eee}pre{background:#2a2a30}.note{background:#3a3220}}"
            "</style></head><body><h1>Draft supplier messages</h1>"
            f"<p class='note'>Recommendation {rec_id}. These are DRAFTS for a human to review. Nothing was sent. "
            f"Purchase request: {html.escape(str(proposal.get('purchase_request_number', '-')))}.</p>"
            + "".join(parts) + "</body></html>")
    open(a.out + ".html", "w", encoding="utf-8").write(page)
    open(a.out + ".txt", "w", encoding="utf-8").write("\n".join(txt))
    print(f"{len(drafts)} suppliers written to {a.out}.html and {a.out}.txt (open the .html in a browser)")


if __name__ == "__main__":
    main()
