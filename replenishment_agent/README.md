# Replenishment agent (alert -> purchase list -> draft supplier message)

Autonomy level 1: the agent PREPARES. A human approves. "Send" is simulated. Numbers never come from an LLM.

## Files
| File | Job |
|---|---|
| `planning.py` | BOM explosion, weekly demand, safety stock, reorder point, order quantity (pure math) |
| `workflow.py` | All writes to the simulation tables, maker != checker, audit events, ledger rules |
| `drafter.py` | Supplier messages (Arabic / English). An LLM may only rephrase; invented numbers are rejected |
| `agent.py` | Orchestrator, demo stock seeding, command line |
| `policy.json` | Service level, review days, approval bands (ASSUMPTIONS, replace with real policy) |
| `material_aliases.json` | Name matching result (a human must confirm each line) |
| `run_demo.py` | One-command demo of the whole flow on a temporary copy |
| `HANDOVER.md` | Status, assumptions to confirm, open questions, next steps |
| `tests/test_agent.py` | 20 tests: math, workflow gates, sealed history, drafter guardrails |

## Quick start
```
python -m venv .venv && .venv\Scripts\activate        (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python run_demo.py --db smart_supply_chain_simulation_v5_recovered_review1.db     # whole flow, 8 steps
```
`sample_output.txt` is the output of that demo. `HANDOVER.md` lists what is done, what to confirm and what is next.

## Run step by step (always on a COPY of the database)
```
cp smart_supply_chain_simulation_v5_recovered_review1.db work.db
python agent.py --db work.db seed                       # demo stock (sandbox only)
python agent.py --db work.db run                        # alerts + draft purchase request + drafts
python agent.py --db work.db approve --pr 2 --by procurement_manager
python agent.py --db work.db po --pr 2                  # draft purchase orders, one per supplier
python agent.py --db work.db po-approve --po 10 --by finance_checker
python agent.py --db work.db po-send --po 10 --by finance_checker    # SIMULATED
pytest tests -q
```
Optional LLM rephrasing: set `ANTHROPIC_API_KEY` (and `CLAUDE_MODEL`). Without it the template is used.

## The logic
```
need/week  = weekly recorded orders x BOM (grams or pieces) x (1 + scrap allowance)
safety     = z * sqrt(lead * sigma_day^2 + (mu_day * sigma_lead)^2)
ROP        = mu_day * lead + safety
alert when   on_hand + open orders <= ROP        (critical if cover days < lead time)
order qty  = (mu_day * (lead + review days) + safety - position), rounded UP to a MOQ multiple
```

## Sourcing, quotations and delivery tracking (v2)
```
alert ──> purchase request ──> RFQ to each supplier who has the item ──> supplier replies with prices
  │                                   ▲                                      │
  │ email/Slack/Telegram       website scraping finds                 quote read from inbox,
  ▼                            who sells what (+ contacts)            checked by a person
buyer                                                                         │
                     purchase order (best confirmed quote) <──────────────────┘
                          │ emailed to supplier
                          ▼
   sent -> acknowledged -> shipped (what + how much) -> out_for_delivery -> delivered -> goods receipt
          time to confirm, time to ship, transit days, total lead time, days late, short shipments
```
| File | Job |
|---|---|
| `scraper.py` | Reads supplier catalog pages (robots.txt respected), matches product names to our materials, stores contacts / quote forms found |
| `rfq.py` | One request for quotation per supplier, maker-checker approval, email or prepared text for a web form |
| `quotes.py` | Reads replies (EN/AR), extracts price, MOQ, lead time, validity; a person confirms; compares offers |
| `tracking.py` | Delivery events, shipped quantities, timeline and durations, late / short / unconfirmed detection, supplier scorecard |
| `notify.py` | Alerts by console, email, Slack/Teams webhook, Telegram; no repeats unless worse |
| `mailer.py` | SMTP out, IMAP in. **Dry run by default**: messages go to `outbox/`, replies are read from `inbox/*.eml` |
| `ops.py` | The new commands and the `watch` cycle |
| `store.py` | The new `ext_*` tables (history tables are not touched) |
| `messaging.json`, `suppliers_contacts.json`, `supplier_sites.json` | Settings to fill in (emails, sites, selectors) |
| `run_procurement_demo.py` | Offline demo of the whole v2 flow (invented sites in `demo/sites`, generated replies) |

```
python run_procurement_demo.py --db smart_supply_chain_simulation_v5_recovered_review1.db

python agent.py --db work.db scrape                       # read supplier sites in supplier_sites.json
python agent.py --db work.db catalog                      # matches waiting for review
python agent.py --db work.db catalog-confirm --id 3 --by buyer
python agent.py --db work.db contacts-found               # emails / quote forms seen on the sites
python agent.py --db work.db names                        # our material <-> each supplier's name and code
python agent.py --db work.db name-add --supplier SUP-EG-06 --material PK-PLASTIC-TUBE-125ML --name "Lamitube 125 cc" --code LT-125 --by buyer
python agent.py --db work.db rfq-create --pr 2
python agent.py --db work.db rfq-approve --rfq 1 --by buyer
python agent.py --db work.db rfq-send --rfq 1 --by buyer      # email, or text to paste in a web form
python agent.py --db work.db rfq-mark-sent --rfq 1 --by buyer # after submitting a web form by hand
python agent.py --db work.db inbox                        # reads replies: quotes and shipping notices
python agent.py --db work.db quote-ingest --rfq 1 --file reply.txt   # or paste a reply by hand
python agent.py --db work.db quote-new --rfq 1 --by buyer            # phone/PDF quote, then:
python agent.py --db work.db quote-add-line --quote 4 --line 2 --price 310 --per kg --moq 500 --lead 7
python agent.py --db work.db quote-show --quote 1
python agent.py --db work.db quote-confirm --quote 1 --by buyer
python agent.py --db work.db quote-compare --pr 2
python agent.py --db work.db po --pr 2                    # uses the best CONFIRMED quote per line
python agent.py --db work.db po-send --po 10 --by finance_checker    # emails the PO, starts the clock
python agent.py --db work.db track --po 10 --status shipped --by supplier --carrier Aramex --tracking AWB123 --ship 30=800000
python agent.py --db work.db track --po 10 --status delivered --by warehouse --receive
python agent.py --db work.db track-show --po 10
python agent.py --db work.db track-check                  # late / unconfirmed / short / ETA moved -> alerts
python agent.py --db work.db scorecard
python agent.py --db work.db watch                        # one full cycle; schedule it every hour
```
Going live: fill `suppliers_contacts.json`, set SMTP/IMAP hosts in `messaging.json`, put passwords in the
environment (`AGENT_SMTP_PASSWORD`, `AGENT_IMAP_PASSWORD`, optional `AGENT_ALERT_WEBHOOK`, `AGENT_TELEGRAM_TOKEN`),
then set `"mode": "live"` (or `AGENT_SEND_MODE=live`). Schedule `watch` with Windows Task Scheduler.

## Rules it enforces
- Stock with no opening record is UNKNOWN, never zero.
- Materials with no RFQ history are listed as "needs sourcing", never ordered.
- Open purchase requests and orders count as supply, so a rerun does not duplicate requests.
- A purchase order needs an APPROVED request. Maker and checker must be different people.
- Every row carries environment_id and an actor. History tables are never modified.
- A website match, an RFQ and a supplier quote each need a person's confirmation; the agent cannot approve its own work.
- Prices only come from supplier replies. An LLM may help read a reply, but any number it returns that is not in the reply rejects its answer.
- Nothing is emailed or posted unless messaging mode is `live`.
- Stock rises only by what the warehouse receives, which defaults to what the supplier says it shipped.

## Known limits (be honest about these in the meeting)
- Baseline forecast (recent weekly average), not a trained model. Recorded orders are not true demand.
- Product size and density are unverified in the source, so quantities are scenario estimates.
- RFQ quotes for the same material vary by more than 100%; cost uses the median and shows the range.
- RFQ price and MOQ are read as per kg (chemicals) / per piece (packaging): confirm with the team.
- No raw-material stock exists in the history: the demo seed is invented. 39 materials have no supplier history.
- Approval bands are invented for the simulation.
- The optional LLM call is untested here (no API key); the guardrail around it is tested.
