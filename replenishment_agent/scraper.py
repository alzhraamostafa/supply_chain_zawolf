"""Supplier website scraper: which supplier offers which of OUR materials (no prices: those come from RFQs).

For each supplier in supplier_sites.json the scraper
  1. checks robots.txt and waits between requests (polite, identifiable User-Agent)
  2. reads the catalog pages (static HTML with requests, or a real browser for JavaScript sites)
  3. extracts product names / codes with the CSS selectors you give, or a generic fallback
  4. matches every product name to our material list (sizes like 250ML must match exactly)
  5. stores matches as 'candidate' in ext_catalog_items. A person confirms or rejects each one.
  6. also stores contact emails (mailto:) and quotation forms it finds, to fill suppliers_contacts.json

Check each website's terms of use before scraping it. If a supplier offers a catalog PDF/Excel or an API,
use that instead: it is more reliable than HTML.
"""
from __future__ import annotations
import os, re, time
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from db import now_utc, tx

USER_AGENT = "ReplenishmentAgentCatalogBot/1.0 (+supplier catalog check)"
SYNONYMS = {"aluminium": "alum", "aluminum": "alum", "polypropylene": "pp", "polyethylene": "pe",
            "demineralised": "demineralized", "glycerine": "glycerin",
            "bottles": "bottle", "tubes": "tube", "caps": "cap", "jars": "jar", "pumps": "pump", "lids": "lid"}
STOP = {"pk", "the", "and", "of", "for", "with", "grade", "type", "new", "high", "quality", "premium"}
UNIT_JOIN = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mm|kg|g|l|ltr|litre|liter)\b")
FORM_HINT = re.compile(r"quot|rfq|inquir|enquir|request|price|تسعير|عرض سعر|استفسار", re.I)


# ------------------------------------------------------------------ name matching
def tokens(text: str) -> list[str]:
    t = text.lower().replace("%", " ")
    t = UNIT_JOIN.sub(lambda m: m.group(1) + m.group(2).replace("ltr", "l").replace("litre", "l").replace("liter", "l"), t)
    out = []
    for tok in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", t):
        tok = SYNONYMS.get(tok, tok)
        if tok not in STOP:
            out.append(tok)
    return out


def match_score(material: str, product: str, code: str | None = None) -> float:
    """0..1. How much of OUR material name appears in the supplier's product name.
    A size / number in our name (250ml, 28mm, 99.5) that is missing from theirs means a different product."""
    if code and code.strip().lower() == material.lower():
        return 1.0
    m, p = tokens(material), set(tokens(product) + (tokens(code) if code else []))
    if not m:
        return 0.0
    hit = 0.0
    for tok in m:
        if tok in p:
            hit += 1
        elif not any(ch.isdigit() for ch in tok):
            best = max((SequenceMatcher(None, tok, q).ratio() for q in p), default=0)
            hit += best if best >= 0.85 else 0
    score = hit / len(m)
    sizes = [tok for tok in m if any(ch.isdigit() for ch in tok)]
    if sizes and not all(s in p for s in sizes):
        score *= 0.3
    return round(score, 3)


def best_match(product: str, code: str | None, materials: list[str], threshold=0.6):
    scored = sorted(((match_score(mat, product, code), mat) for mat in materials), reverse=True)
    if not scored or scored[0][0] < threshold:
        return None, scored[0][0] if scored else 0.0
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None, scored[0][0]                 # ambiguous: leave it for a person
    return scored[0][1], scored[0][0]


# ------------------------------------------------------------------ fetching
class Fetcher:
    def __init__(self, delay_seconds=2.0, timeout=20):
        import requests
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.delay, self.timeout, self._robots, self._last = delay_seconds, timeout, {}, 0.0

    def allowed(self, url: str) -> bool:
        u = urlparse(url)
        if u.scheme not in ("http", "https"):
            return True
        root = f"{u.scheme}://{u.netloc}"
        if root not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.s.get(root + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                rp.parse([])
            self._robots[root] = rp
        return self._robots[root].can_fetch(USER_AGENT, url)

    def get(self, url: str, render: str = "static") -> str:
        u = urlparse(url)
        if u.scheme not in ("http", "https"):                       # local file (demo / saved pages)
            from urllib.request import url2pathname
            path = url2pathname(u.path) if u.scheme == "file" else url
            with open(path, encoding="utf-8") as f:
                return f.read()
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        if render == "browser":
            return self._browser(url)
        r = self.s.get(url, timeout=self.timeout)
        r.raise_for_status()
        r.encoding = r.encoding or r.apparent_encoding
        return r.text

    def _browser(self, url):                         # pragma: no cover (needs: pip install playwright; playwright install chromium)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            html = page.content()
            b.close()
            return html


# ------------------------------------------------------------------ extraction
def extract(html: str, url: str, site: dict) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")
    items = []
    if site.get("item_selector"):
        for el in soup.select(site["item_selector"]):
            n = el.select_one(site["name_selector"]) if site.get("name_selector") else el
            c = el.select_one(site["code_selector"]) if site.get("code_selector") else None
            name = n.get_text(" ", strip=True) if n else ""
            if name:
                items.append(dict(name=name, code=c.get_text(" ", strip=True) if c else None))
    else:                                            # generic fallback: short headings, list items, cells, links
        seen = set()
        for el in soup.select("h1,h2,h3,h4,h5,li,td,a,[class*=product],[class*=item-title]"):
            t = el.get_text(" ", strip=True)
            if 3 <= len(t) <= 120 and len(t.split()) <= 15 and t.lower() not in seen:
                seen.add(t.lower())
                items.append(dict(name=t, code=None))
    nxt = None
    if site.get("next_selector"):
        a = soup.select_one(site["next_selector"])
        if a and a.get("href"):
            nxt = urljoin(url, a["href"])
    contacts = []
    for a in soup.select("a[href^='mailto:']"):
        contacts.append(("email", a["href"][7:].split("?")[0].strip()))
    for a in soup.select("a[href^='tel:']"):
        contacts.append(("phone", a["href"][4:].strip()))
    for f in soup.select("form"):
        if FORM_HINT.search(f.get_text(" ") + " " + " ".join(str(i.get("name", "")) for i in f.select("input,textarea"))):
            contacts.append(("form", urljoin(url, f.get("action") or url)))
    return dict(items=items, next=nxt, contacts=contacts)


def _has_lxml():
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        return False


# ------------------------------------------------------------------ run
def scrape_supplier(con, supplier_id: str, site: dict, materials: list[str], fetcher=None) -> dict:
    fetcher = fetcher or Fetcher(site.get("delay_seconds", 2.0))
    threshold = site.get("match_threshold", 0.6)
    queue, done = list(site.get("start_urls", [])), set()
    stats = dict(pages=0, products=0, matched=0, contacts=0, errors=[])
    while queue and stats["pages"] < site.get("max_pages", 20):
        url = queue.pop(0)
        if url in done:
            continue
        done.add(url)
        try:
            html = fetcher.get(url, site.get("render", "static"))
        except Exception as e:
            stats["errors"].append(f"{url}: {e}")
            continue
        stats["pages"] += 1
        page = extract(html, url, site)
        if page["next"]:
            queue.append(page["next"])
        with tx(con):
            for it in page["items"]:
                mat, score = best_match(it["name"], it["code"], materials, threshold)
                stats["products"] += 1
                if mat is None:
                    continue
                stats["matched"] += 1
                con.execute("INSERT INTO ext_catalog_items(supplier_id,source_url,product_name,product_code,"
                            "matched_material,match_score,status,scraped_at_utc) VALUES (?,?,?,?,?,?,'candidate',?) "
                            "ON CONFLICT(supplier_id,product_name,source_url) DO UPDATE SET "
                            "matched_material=excluded.matched_material, match_score=excluded.match_score, "
                            "scraped_at_utc=excluded.scraped_at_utc WHERE ext_catalog_items.status='candidate'",
                            (supplier_id, url, it["name"], it["code"], mat, score, now_utc()))
            for kind, value in page["contacts"]:
                cur = con.execute("INSERT OR IGNORE INTO ext_supplier_contacts_found(supplier_id,kind,value,source_url,"
                                  "found_at_utc) VALUES (?,?,?,?,?)", (supplier_id, kind, value, url, now_utc()))
                stats["contacts"] += cur.rowcount
    return stats


def decide(con, catalog_item_id: int, confirm: bool, by: str):
    row = con.execute("SELECT status FROM ext_catalog_items WHERE catalog_item_id=?", (catalog_item_id,)).fetchone()
    if row is None:
        raise ValueError("catalog item not found")
    with tx(con):
        con.execute("UPDATE ext_catalog_items SET status=?, decided_by=?, decided_at_utc=? WHERE catalog_item_id=?",
                    ("confirmed" if confirm else "rejected", by, now_utc(), catalog_item_id))


def add_name(con, supplier_id, material, product_name, product_code, by, source="manual entry"):
    """Record a supplier's own name/code for one of our materials without scraping (price list, phone, email).
    Entered by a person, so it is confirmed at once."""
    with tx(con):
        con.execute("INSERT INTO ext_catalog_items(supplier_id,source_url,product_name,product_code,matched_material,"
                    "match_score,status,scraped_at_utc,decided_by,decided_at_utc) VALUES (?,?,?,?,?,1.0,'confirmed',?,?,?) "
                    "ON CONFLICT(supplier_id,product_name,source_url) DO UPDATE SET matched_material=excluded.matched_material,"
                    " product_code=excluded.product_code, status='confirmed', decided_by=excluded.decided_by,"
                    " decided_at_utc=excluded.decided_at_utc",
                    (supplier_id, source, product_name, product_code, material, now_utc(), by, now_utc()))


def supplier_name_for(con, supplier_id: str, material: str):
    """The supplier's own (product name, product code) for our material, from a CONFIRMED match. (None, None) if unknown."""
    r = con.execute("SELECT product_name, product_code FROM ext_catalog_items WHERE supplier_id=? AND matched_material=? "
                    "AND status='confirmed' ORDER BY match_score DESC, decided_at_utc DESC LIMIT 1",
                    (supplier_id, material)).fetchone()
    return (r[0], r[1]) if r else (None, None)


def name_score(text: str, material: str, supplier_name: str | None = None, supplier_code: str | None = None) -> float:
    """How clearly a line of text names this item, under OUR name, the supplier's name, or the supplier's code."""
    best = match_score(material, text)
    if supplier_name:
        best = max(best, match_score(supplier_name, text))
    if supplier_code and re.search(r"(?<![A-Za-z0-9])" + re.escape(supplier_code) + r"(?![A-Za-z0-9])", text, re.I):
        best = 1.0
    return best


def suppliers_offering(con, material: str) -> list[str]:
    """Suppliers whose website match for this material a person has CONFIRMED."""
    return [r[0] for r in con.execute("SELECT DISTINCT supplier_id FROM ext_catalog_items "
                                      "WHERE matched_material=? AND status='confirmed'", (material,))]
