# Duka Copilot - key numbers

Generated from the code on 2026-10-19 02:22 with the **default owner settings**. Quote only these figures in the deck, docs and demo. Regenerate with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python scripts/key_numbers.py`.

All data is synthetic. SACCO and bank rates are illustrative, not real quotes. The offline planner's questions were written alongside it, so real-world accuracy would be lower.

## Tests and evidence

| Figure | Value | Source |
|---|---|---|
| Automated tests | 265 passed, 3 skipped in 54.83s | `pytest` |
| Attack scorecard | 38 of 38 blocked | `tests/security/attack_suite.py` |
| Task success, scripted AI | 23/23 = 100% | `tests/eval/task_eval.py` |
| Task success, offline keyword planner (EN + SW) | 24/24 = 100% | `tests/eval/task_eval.py` |

## Amina's Grocery (Nairobi)

| Figure | Value | Source |
|---|---|---|
| Statement period | 2026-07-15 to 2026-10-15 | `transaction_ledger` |
| Transactions loaded | 3,573 | `core.ingestion.StatementIngestor` |
| Rows the owner should review (teach once) | 122 (3%) | `needs_review` |
| Rows flagged as prompt injection | 0 | `injection_finding` |
| Money in, last 30 days | KES 318,660 | `compute_business_health` |
| Business costs, last 30 days | KES 296,636 | `compute_business_health` |
| Margin, last 30 days | 6.9% | `compute_business_health` |
| Personal spending share of money out | 6.8% | `compute_business_health` |
| Mobile-money balance (last day) | KES 0 | `forecaster.true_position` |
| Overdraft owed, with fees | KES 37,966 | `forecaster.overdraft_owed_by_day` |
| **True position** (balance minus overdraft owed) | **KES -37,966** | `forecaster.true_position` |
| Safety buffer / caps (per payment / day / loan) | KES 5,000 / KES 25,000 / KES 50,000 / KES 50,000 | `owner_settings.defaults` |
| 14-day forecast | ALERT on 14 of 14 days from 2026-10-16; needs about KES 68,177 | `forecast_balance + detect_shortfalls` |
| Forecast backtest (last 14 days hidden) | sales -3.7%; last day off by KES 357; 12/14 days inside range | `forecast_backtest` |
| KES 45,000 / 180 days: Bank SME loan | cost KES 2,809, 24.1% a year | `compare_financing` |
| KES 45,000 / 180 days: SACCO loan | cost KES 2,892, 24.7% a year | `compare_financing` |
| Loan fit check (default settings) | SACCO loan of KES 50,000, if personal money stays under KES 161 a week (now KES 11,807) | `recommend_loan` |

## Grace Beauty Salon (Kisumu)

| Figure | Value | Source |
|---|---|---|
| Statement period | 2026-07-15 to 2026-10-15 | `transaction_ledger` |
| Transactions loaded | 956 | `core.ingestion.StatementIngestor` |
| Rows the owner should review (teach once) | 88 (9%) | `needs_review` |
| Rows flagged as prompt injection | 0 | `injection_finding` |
| Money in, last 30 days | KES 209,130 | `compute_business_health` |
| Business costs, last 30 days | KES 88,081 | `compute_business_health` |
| Margin, last 30 days | 57.9% | `compute_business_health` |
| Personal spending share of money out | 54.6% | `compute_business_health` |
| Mobile-money balance (last day) | KES 43,074 | `forecaster.true_position` |
| Overdraft owed, with fees | KES 0 | `forecaster.overdraft_owed_by_day` |
| **True position** (balance minus overdraft owed) | **KES 43,074** | `forecaster.true_position` |
| Safety buffer / caps (per payment / day / loan) | KES 5,000 / KES 25,000 / KES 50,000 / KES 50,000 | `owner_settings.defaults` |
| 14-day forecast | stays above the buffer | `forecast_balance + detect_shortfalls` |
| Forecast backtest (last 14 days hidden) | sales +0.5%; last day off by KES 8,754; 14/14 days inside range | `forecast_backtest` |
| KES 45,000 / 180 days: Bank SME loan | cost KES 2,809, 24.1% a year | `compare_financing` |
| KES 45,000 / 180 days: SACCO loan | cost KES 2,892, 24.7% a year | `compare_financing` |
| Loan fit check (default settings) | no loan needed | `recommend_loan` |

## Otieno Boda Services (Nakuru)

| Figure | Value | Source |
|---|---|---|
| Statement period | 2026-07-15 to 2026-10-15 | `transaction_ledger` |
| Transactions loaded | 2,364 | `core.ingestion.StatementIngestor` |
| Rows the owner should review (teach once) | 156 (7%) | `needs_review` |
| Rows flagged as prompt injection | 0 | `injection_finding` |
| Money in, last 30 days | KES 101,920 | `compute_business_health` |
| Business costs, last 30 days | KES 29,055 | `compute_business_health` |
| Margin, last 30 days | 71.5% | `compute_business_health` |
| Personal spending share of money out | 54.5% | `compute_business_health` |
| Mobile-money balance (last day) | KES 28,188 | `forecaster.true_position` |
| Overdraft owed, with fees | KES 1 | `forecaster.overdraft_owed_by_day` |
| **True position** (balance minus overdraft owed) | **KES 28,187** | `forecaster.true_position` |
| Safety buffer / caps (per payment / day / loan) | KES 5,000 / KES 25,000 / KES 50,000 / KES 50,000 | `owner_settings.defaults` |
| 14-day forecast | stays above the buffer | `forecast_balance + detect_shortfalls` |
| Forecast backtest (last 14 days hidden) | sales -0.7%; last day off by KES 706; 13/14 days inside range | `forecast_backtest` |
| KES 45,000 / 180 days: Bank SME loan | cost KES 2,809, 24.1% a year | `compare_financing` |
| KES 45,000 / 180 days: SACCO loan | cost KES 2,892, 24.7% a year | `compare_financing` |
| Loan fit check (default settings) | no loan needed | `recommend_loan` |
