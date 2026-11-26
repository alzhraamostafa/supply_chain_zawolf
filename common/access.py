"""Access control for supplier quotes: a supplier must never see another supplier's quotes.
Quotes are stored in SQLite and cannot be changed or deleted afterwards."""
import sqlite3
import threading
from dataclasses import dataclass

from .audit import AuditLog

BUYER_ROLES = frozenset({"buyer", "procurement_manager", "finance_manager"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    quote_id TEXT PRIMARY KEY,
    supplier_org_id TEXT NOT NULL,
    buyer_org_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    price_egp REAL NOT NULL CHECK (price_egp > 0)
);
CREATE TRIGGER IF NOT EXISTS quotes_no_update BEFORE UPDATE ON quotes
BEGIN SELECT RAISE(ABORT, 'quotes cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS quotes_no_delete BEFORE DELETE ON quotes
BEGIN SELECT RAISE(ABORT, 'quotes cannot be deleted'); END;
"""


class AccessDenied(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: str
    org_id: str
    role: str


@dataclass(frozen=True)
class Quote:
    quote_id: str
    supplier_org_id: str
    buyer_org_id: str
    sku: str
    price_egp: float


def can_view(principal: Principal, quote: Quote) -> bool:
    if principal.role == "supplier":
        return principal.org_id == quote.supplier_org_id
    if principal.role in BUYER_ROLES:
        return principal.org_id == quote.buyer_org_id
    return False


class QuoteStore:
    def __init__(self, audit: AuditLog | None = None, db_path: str = ":memory:"):
        self.audit = audit
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self.con.close()

    def add(self, quote: Quote) -> None:
        try:
            with self._lock:
                self.con.execute("INSERT INTO quotes VALUES (?, ?, ?, ?, ?)",
                                 (quote.quote_id, quote.supplier_org_id, quote.buyer_org_id,
                                  quote.sku, quote.price_egp))
                self.con.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"quote could not be stored: {exc}") from exc

    def _all(self) -> list[Quote]:
        with self._lock:
            rows = self.con.execute(
                "SELECT quote_id, supplier_org_id, buyer_org_id, sku, price_egp FROM quotes ORDER BY rowid"
            ).fetchall()
        return [Quote(*row) for row in rows]

    def get(self, principal: Principal, quote_id: str) -> Quote:
        quote = next((q for q in self._all() if q.quote_id == quote_id), None)
        if quote is None or not can_view(principal, quote):
            if self.audit:
                self.audit.record(principal.user_id, "quote_access_denied", input_ref=quote_id)
            # same error for "missing" and "forbidden", so a caller cannot probe which ids exist
            raise AccessDenied("quote not found or access denied")
        return quote

    def list_for(self, principal: Principal) -> list[Quote]:
        return [q for q in self._all() if can_view(principal, q)]