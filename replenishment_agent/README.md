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

## Rules it enforces
- Stock with no opening record is UNKNOWN, never zero.
- Materials with no RFQ history are listed as "needs sourcing", never ordered.
- Open purchase requests and orders count as supply, so a rerun does not duplicate requests.
- A purchase order needs an APPROVED request. Maker and checker must be different people.
- Every row carries environment_id and an actor. History tables are never modified.

## Known limits (be honest about these in the meeting)
- Baseline forecast (recent weekly average), not a trained model. Recorded orders are not true demand.
- Product size and density are unverified in the source, so quantities are scenario estimates.
- RFQ quotes for the same material vary by more than 100%; cost uses the median and shows the range.
- RFQ price and MOQ are read as per kg (chemicals) / per piece (packaging): confirm with the team.
- No raw-material stock exists in the history: the demo seed is invented. 39 materials have no supplier history.
- Approval bands are invented for the simulation.
- The optional LLM call is untested here (no API key); the guardrail around it is tested.
