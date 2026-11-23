# Update: Replenishment Agent v2 (2026-11-23)

What is done, what is written but not tested for real, and what is not done yet.

Everything runs in **dry-run mode**: messages are written to the `outbox/` folder and nothing is actually sent.
39 automated tests pass (20 from v1, 19 new), and both demos run:

```
python run_demo.py --db smart_supply_chain_simulation_v5_recovered_review1.db               # v1 flow
python run_procurement_demo.py --db smart_supply_chain_simulation_v5_recovered_review1.db   # v2 flow
```

## Done and tested

| Area | What works |
|---|---|
| Restock alerts | Detects which material needs ordering and how urgently. Sends one alert per material (console, email, Slack/Teams, Telegram) and does not repeat it within 24 hours unless it gets worse. |
| Purchase request | Order quantity, estimated cost and approval level are prepared for a person to approve. |
| Website scraping | Reads supplier catalog pages (robots.txt respected), matches their product names to our materials (sizes must agree), saves emails and quote forms found on the site. A person confirms each match. Tested on demo pages only. |
| Name alignment | Each of our materials is linked to each supplier's own product name and code. RFQ and purchase-order emails show both names; replies and shipping notices are matched by either. `name-add` records a supplier name by hand. |
| Request for quotation (RFQ) | One RFQ per supplier who can supply the item (purchase history + confirmed website matches). A person must approve before sending. Sent by email, or prepared as text to paste into the supplier's website form. |
| Reading price replies | Extracts price, MOQ, lead time and validity from English or Arabic replies. Recognises declines. A person confirms each quote. `quote-compare` picks the best offer. Phone or PDF quotes can be typed in by hand. |
| Purchase order | Uses the best confirmed quote, needs a second person to approve, is emailed to the supplier, and starts the delivery clock. |
| Delivery tracking | Status chain sent → acknowledged → in production → shipped → in transit → out for delivery → delivered, with what was actually shipped per line. Stock rises only by what the warehouse receives. Timeline: days to confirm, to ship, in transit, total lead time, days late or early. |
| Delivery alerts | Late, not confirmed by the supplier, delivery date moved, short shipment, delivered but not received. |
| Supplier scorecard | Average lead time, on-time %, fill rate. After 3 delivered orders, the measured lead time replaces the history value in the reorder calculation. |
| Inbox | Supplier emails are routed by the `[RFQ-…]` / `[PO-…]` tag in the subject; each email is handled once. |
| `watch` command | One full cycle: alerts, inbox, delivery chasing. Meant to run every hour. |

## Written but not tested for real

- **Real email sending and inbox reading (SMTP/IMAP):** needs the company mailbox details and password.
- **Carrier tracking APIs** (Aramex, Bosta, …): a general connector exists; no real carrier is connected.
- **AI help reading messy replies:** needs an Anthropic API key. Any number it returns that is not in the reply makes its answer rejected.
- **Websites that need JavaScript:** needs Playwright installed.

## Not done yet

- **Automatic status updates (like Amazon).** Plan: a private supplier portal link in each purchase order email (the supplier clicks Confirmed / Shipped and enters quantities and tracking number), plus carrier status updates pushed to our system automatically. Needs an internet-reachable address (a tunnel for testing, a small cloud server for real use). Waiting on: test locally or on a server, and which delivery companies the suppliers use.
- Filling in supplier website forms automatically (a person pastes the prepared text for now).
- Reading prices from PDF or Excel attachments.
- Negotiation agent, buyer chat assistant, search over company policies.

## Needed before real use

1. Supplier emails and quote-form links in `suppliers_contacts.json` (the database has none; every supplier is "manual" for now).
2. Catalog page links in `supplier_sites.json`, after checking each site's terms of use.
3. The mailbox to use (SMTP/IMAP) in `messaging.json`, passwords in environment variables, then `"mode": "live"`.
4. The open questions in `HANDOVER.md`: price units, real approval limits, real opening stock.
5. A schedule for `python agent.py --db work.db watch`, for example hourly in Windows Task Scheduler.

## New files in v2

| File | Job |
|---|---|
| `scraper.py` | Supplier website scraping, name matching, supplier names and codes |
| `rfq.py` | Requests for quotation with maker-checker approval |
| `quotes.py` | Reading replies, confirming quotes, comparing offers |
| `tracking.py` | Delivery events, timelines, late/short detection, scorecard |
| `notify.py` | Alerts by console, email, webhook, Telegram |
| `mailer.py` | Email out/in; dry run by default |
| `ops.py` | New commands and the `watch` cycle |
| `store.py` | New `ext_*` tables (history tables untouched) |
| `messaging.json`, `suppliers_contacts.json`, `supplier_sites.json` | Settings to fill in |
| `run_procurement_demo.py`, `demo/sites/` | Offline demo with made-up supplier pages and replies |
| `tests/test_procurement.py` | 19 tests for the new parts |

The full command list is in `README.md`.
