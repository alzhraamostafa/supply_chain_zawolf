"""Agent-owned tables for sourcing, RFQs, quotes, notifications and delivery tracking.

They live next to the simulation tables (prefix ext_) and never modify the sealed history tables.
Created with CREATE TABLE IF NOT EXISTS, so calling ensure_schema() on every start is safe.
"""

SCHEMA = """
-- products found on supplier websites, matched to our materials (a human confirms each match)
CREATE TABLE IF NOT EXISTS ext_catalog_items(
    catalog_item_id   INTEGER PRIMARY KEY,
    supplier_id       TEXT NOT NULL REFERENCES suppliers(supplier_id),
    source_url        TEXT NOT NULL,
    product_name      TEXT NOT NULL,
    product_code      TEXT,
    matched_material  TEXT,
    match_score       REAL,
    status            TEXT NOT NULL DEFAULT 'candidate' CHECK(status IN ('candidate','confirmed','rejected')),
    scraped_at_utc    TEXT NOT NULL,
    decided_by        TEXT,
    decided_at_utc    TEXT,
    UNIQUE(supplier_id, product_name, source_url)
);
-- contact details found while scraping (mailto links, quotation forms)
CREATE TABLE IF NOT EXISTS ext_supplier_contacts_found(
    supplier_id     TEXT NOT NULL REFERENCES suppliers(supplier_id),
    kind            TEXT NOT NULL CHECK(kind IN ('email','form','phone')),
    value           TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    found_at_utc    TEXT NOT NULL,
    UNIQUE(supplier_id, kind, value)
);

-- request for quotation sent to one supplier for some lines of a purchase request
CREATE TABLE IF NOT EXISTS ext_rfqs(
    rfq_id              INTEGER PRIMARY KEY,
    rfq_number          TEXT NOT NULL UNIQUE,
    environment_id      INTEGER NOT NULL,
    purchase_request_id INTEGER NOT NULL REFERENCES purchase_requests(purchase_request_id),
    supplier_id         TEXT NOT NULL REFERENCES suppliers(supplier_id),
    channel             TEXT NOT NULL CHECK(channel IN ('email','web_form','manual')),
    recipient           TEXT,
    language            TEXT NOT NULL,
    subject             TEXT NOT NULL,
    body                TEXT NOT NULL,
    body_source         TEXT NOT NULL,
    status              TEXT NOT NULL CHECK(status IN ('draft','approved','sent','quoted','declined','cancelled')),
    created_by          TEXT NOT NULL,
    created_at_utc      TEXT NOT NULL,
    reply_due_date      TEXT
);
CREATE TABLE IF NOT EXISTS ext_rfq_lines(
    rfq_line_id         INTEGER PRIMARY KEY,
    rfq_id              INTEGER NOT NULL REFERENCES ext_rfqs(rfq_id),
    purchase_request_line_id INTEGER NOT NULL REFERENCES purchase_request_lines(purchase_request_line_id),
    stock_item_id       INTEGER NOT NULL REFERENCES stock_items(stock_item_id),
    material            TEXT NOT NULL,
    unit                TEXT NOT NULL,
    qty_base_units      INTEGER NOT NULL,
    needed_by           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ext_rfq_events(
    event_id        INTEGER PRIMARY KEY,
    rfq_id          INTEGER NOT NULL REFERENCES ext_rfqs(rfq_id),
    event_at_utc    TEXT NOT NULL,
    actor           TEXT NOT NULL,
    new_status      TEXT NOT NULL,
    reason          TEXT NOT NULL
);

-- supplier replies with prices
CREATE TABLE IF NOT EXISTS ext_quotes(
    quote_id          INTEGER PRIMARY KEY,
    rfq_id            INTEGER NOT NULL REFERENCES ext_rfqs(rfq_id),
    received_at_utc   TEXT NOT NULL,
    source            TEXT NOT NULL,
    raw_text          TEXT NOT NULL,
    extracted_by      TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    status            TEXT NOT NULL CHECK(status IN ('extracted','confirmed','rejected')),
    decided_by        TEXT,
    decided_at_utc    TEXT
);
CREATE TABLE IF NOT EXISTS ext_quote_lines(
    quote_line_id           INTEGER PRIMARY KEY,
    quote_id                INTEGER NOT NULL REFERENCES ext_quotes(quote_id),
    rfq_line_id             INTEGER NOT NULL REFERENCES ext_rfq_lines(rfq_line_id),
    unit_price_piastres     INTEGER NOT NULL CHECK(unit_price_piastres > 0),
    price_basis_base_units  INTEGER NOT NULL CHECK(price_basis_base_units > 0),
    moq_base_units          INTEGER,
    lead_days               INTEGER,
    valid_until             TEXT,
    evidence                TEXT
);
CREATE TABLE IF NOT EXISTS ext_po_quote_links(
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(purchase_order_id),
    quote_id          INTEGER NOT NULL REFERENCES ext_quotes(quote_id),
    PRIMARY KEY(purchase_order_id, quote_id)
);

-- delivery tracking: one row per status update the supplier / carrier / warehouse reports
CREATE TABLE IF NOT EXISTS ext_shipment_events(
    event_id          INTEGER PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(purchase_order_id),
    status            TEXT NOT NULL CHECK(status IN ('sent','acknowledged','in_production','shipped','in_transit',
                                                     'out_for_delivery','delivered','delayed','exception')),
    event_at_utc      TEXT NOT NULL,
    recorded_at_utc   TEXT NOT NULL,
    actor             TEXT NOT NULL,
    source            TEXT NOT NULL,
    carrier           TEXT,
    tracking_number   TEXT,
    eta_date          TEXT,
    note              TEXT
);
-- what was physically put on the truck (can differ from what was ordered)
CREATE TABLE IF NOT EXISTS ext_shipment_lines(
    shipment_line_id      INTEGER PRIMARY KEY,
    event_id              INTEGER NOT NULL REFERENCES ext_shipment_events(event_id),
    purchase_order_line_id INTEGER NOT NULL REFERENCES purchase_order_lines(purchase_order_line_id),
    qty_base_units        INTEGER NOT NULL CHECK(qty_base_units >= 0)
);

-- every alert raised and every message prepared (sent or dry run)
CREATE TABLE IF NOT EXISTS ext_notifications(
    notification_id INTEGER PRIMARY KEY,
    dedupe_key      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    channels        TEXT NOT NULL,
    created_at_utc  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ext_outbox(
    message_id      INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    ref             TEXT,
    channel         TEXT NOT NULL,
    recipient       TEXT,
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('dry_run','sent','failed','manual')),
    file_path       TEXT,
    error           TEXT,
    created_at_utc  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ext_inbox_seen(
    message_key     TEXT PRIMARY KEY,
    handled_as      TEXT NOT NULL,
    seen_at_utc     TEXT NOT NULL
);
"""


ADDED_COLUMNS = {   # columns added after the first release: added to existing databases on start
    "ext_rfq_lines": {"supplier_product_name": "TEXT", "supplier_product_code": "TEXT"},
}


def ensure_schema(con):
    con.executescript(SCHEMA)
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
