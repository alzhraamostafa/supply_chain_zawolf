import pytest
from common.access import AccessDenied, Principal, Quote, QuoteStore
from common.audit import AuditLog

BUYER_ORG = "factory-1"
SUP_A = Principal("sa", "supplier-A", "supplier")
SUP_B = Principal("sb", "supplier-B", "supplier")
BUYER = Principal("b1", BUYER_ORG, "buyer")
OTHER_BUYER = Principal("b2", "factory-2", "buyer")


def make_store():
    audit = AuditLog()
    store = QuoteStore(audit)
    store.add(Quote("q-a", "supplier-A", BUYER_ORG, "Glycerin", 100.0))
    store.add(Quote("q-b", "supplier-B", BUYER_ORG, "Glycerin", 95.0))
    return store, audit


def test_supplier_sees_own_quote():
    store, _ = make_store()
    assert store.get(SUP_A, "q-a").price_egp == 100.0


def test_supplier_cannot_read_another_suppliers_quote():
    store, _ = make_store()
    with pytest.raises(AccessDenied):
        store.get(SUP_A, "q-b")
    with pytest.raises(AccessDenied):
        store.get(SUP_B, "q-a")


def test_supplier_list_contains_only_own_quotes():
    store, _ = make_store()
    assert [q.quote_id for q in store.list_for(SUP_A)] == ["q-a"]
    assert [q.quote_id for q in store.list_for(SUP_B)] == ["q-b"]


def test_buyer_sees_all_quotes_of_their_organization():
    store, _ = make_store()
    assert {q.quote_id for q in store.list_for(BUYER)} == {"q-a", "q-b"}


def test_buyer_of_another_organization_sees_nothing():
    store, _ = make_store()
    assert store.list_for(OTHER_BUYER) == []
    with pytest.raises(AccessDenied):
        store.get(OTHER_BUYER, "q-a")


def test_unknown_role_is_denied():
    store, _ = make_store()
    with pytest.raises(AccessDenied):
        store.get(Principal("x", BUYER_ORG, "intern"), "q-a")


def test_missing_and_forbidden_look_identical():
    store, _ = make_store()
    messages = []
    for quote_id in ("q-b", "does-not-exist"):
        with pytest.raises(AccessDenied) as exc:
            store.get(SUP_A, quote_id)
        messages.append(str(exc.value))
    assert messages[0] == messages[1]


def test_denied_access_is_audited():
    store, audit = make_store()
    with pytest.raises(AccessDenied):
        store.get(SUP_A, "q-b")
    rows = audit.entries("sa")
    assert rows[0]["action"] == "quote_access_denied" and rows[0]["input_ref"] == "q-b"
