# Decision Log

Date logged: 2026-11-17. Owner of this file: Integration, MLOps & QA.

## Decisions

| # | Decision | Why |
|---|---|---|
| 1 | No direct pushes to `main`. Work happens on branches and reaches `main` through a Pull Request. | Protects `main` from accidental deletion or overwriting. |
| 2 | Forecasting stays on branch `alzhraa/forecasting` until it is ready. When it is, it goes to `main` from a new branch cut from `main`. | The first PR was merged and reverted, so merging the old branch would not bring the files back. |
| 3 | Forecasting reads only whitelisted columns. `ai_predicted_demand_pcs`, `demand_forecast_variance_pcs`, `ai_forecast_accuracy_rate` and `demand_anomaly_flag` are never used. | They are derived from actual demand (correlation 0.996 for the first), so using them would fake the accuracy. |
| 4 | A forecast model is kept only if it beats the best baseline (naive or moving average) in the rolling backtest. | Avoids complexity that does not improve results. |
| 5 | Every component output is wrapped in the shared envelope (`contracts/envelope.py`): source, confidence, autonomy level and human-approval flag. | The project plan requires every output to show its source, confidence and review status. |
| 6 | Autonomy levels 0 and 1 must always require human approval. | In the MVP every purchase decision goes through a human. |
| 7 | Approval is Maker-Checker: the maker cannot decide their own request, the checker needs a high enough role, decisions are final, and a rejection needs a reason. | Four-eyes control on financial commitments. |
| 8 | The audit log is append-only, enforced by database triggers. Every component writes to it. | Traceability of every action and approval. |
| 9 | Sandbox mode is ON by default and turns off only when `SANDBOX_MODE` is exactly `false`. Tests run with the network blocked where needed. | No real emails, RFQs or purchase orders in the MVP. |
| 10 | Suppliers see only their own quotes. Buyer staff see quotes addressed to their organization. A missing quote and a forbidden quote return the same error, and every denial is audited. | The plan requires no supplier-to-supplier data leakage. |
| 11 | The shared Postgres is published on `127.0.0.1` only, and real credentials live in `.env`, which is never committed. | Nothing is reachable from outside the machine, and no secrets in a public repository. |
| 12 | Data-quality checks run as a report command (`python -m data_quality.report`), not as failing tests. The tests only check the checks themselves. | The findings are about the dataset and would otherwise block CI. |

## Open questions

| Question | Who decides |
|---|---|
| Real approval thresholds and role names (current values in `common/approval.py` are placeholders) | Business Analyst |
| How forecast `confidence` is calculated (candidate: derive it from the backtest WAPE) | Integration with the forecasting owner |
| Maximum forecast horizon (the contract allows 12 weeks, the model forecasts 1 week ahead) | Integration with the forecasting owner |
| BOM to RFQ SKU mapping (41 materials and 28 packaging items in the BOM, only 13 and 14 of them appear in the RFQs) | Data Engineer with the Business Analyst |
| 24 months of data, competing supplier quotes, realistic prices and planted delay scenarios | Data Engineer |
| Where the product, BOM and inventory backend lives, and who owns it | Whole team |
