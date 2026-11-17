"""Access control for supplier quotes: a supplier must never see another supplier's quotes."""
from dataclasses import dataclass

from .audit import AuditLog

BUYER_ROLES = frozenset({"buyer", "procurement_manager", "finance_manager"})


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
    def __init__(self, audit: AuditLog | None = None):
        self._quotes: dict[str, Quote] = {}
        self.audit = audit

    def add(self, quote: Quote) -> None:
        self._quotes[quote.quote_id] = quote

    def get(self, principal: Principal, quote_id: str) -> Quote:
        quote = self._quotes.get(quote_id)
        if quote is None or not can_view(principal, quote):
            if self.audit:
                self.audit.record(principal.user_id, "quote_access_denied", input_ref=quote_id)
            # same error for "missing" and "forbidden", so a caller cannot probe which ids exist
            raise AccessDenied("quote not found or access denied")
        return quote

    def list_for(self, principal: Principal) -> list[Quote]:
        return [q for q in self._quotes.values() if can_view(principal, q)]
