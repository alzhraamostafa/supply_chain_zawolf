# Handover: Replenishment Agent (v1)

## What it is
An agent that raises an alert when a raw material or packaging item will run short, prepares a draft purchase
request and Arabic/English supplier messages, and follows human approval to a draft purchase order and a
SIMULATED send. Level 1 autonomy: the agent prepares, humans decide, nothing leaves the system.

## Status
| Item | State |
|---|---|
| Demand to material need (orders x BOM x scrap) | Done, tested |
| Reorder point, safety stock, order quantity (MOQ rounding), cost range | Done, tested |
| Draft purchase request, recommendation, audit events | Done, tested |
| Maker-checker approvals, PO drafts, simulated send, simulated receipt | Done, tested |
| Arabic / English supplier message templates + number guardrail | Done, tested |
| LLM rewriting of messages (needs ANTHROPIC_API_KEY) | Written, NOT tested live |
| 20 automated tests (4 rule-breaking mutations caught) | Passing |
| Full explanation of every calculation and line | Document "Replenishment Agent: Calculations and Code Explained" |

## Confirm before trusting the numbers
1. RFQ price and MOQ are per kg (chemicals) and per piece (packaging)?
2. Name matches in material_aliases.json: Sodium_Chloride_Pure = Sodium_Chloride; PK-ALUM-TUBE-10ML = 10G; 25ML = 25G.
3. May the agent write to the simulation tables directly, or must it call the teammate's APIs? (Only workflow.py changes.)
4. Real approval limits (policy.json has invented ones: 100,000 and 1,000,000 EGP).
5. Who creates real opening stock for raw materials? (None exists in the history; the demo stock is invented.)

## Known limits
- Forecast = average of the last 8 complete weeks (not a trained model). Recorded orders are not true demand.
- Product size and density are unverified in the source: quantities are scenario estimates.
- RFQ quotes for one material vary by more than 100%: cost uses the median and shows the range.
- 39 materials have no supplier history and cannot be ordered.
- Safety stock assumes roughly normal demand and independent weeks, from 25 weekly points.

## Not in this version
Negotiation agent, delivery and exception agent, Copilot, RAG over policies, quote document extraction, real emails.

## Next steps
1. Send the confirmation questions above and agree the API endpoints.
2. Replace the baseline forecast with the Data team's model (one function in planning.py).
3. Test the LLM rewrite with an API key.
4. Add the negotiation and delivery agents, then the Copilot and RAG.
