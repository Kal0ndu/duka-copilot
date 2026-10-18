# Duka Copilot - key numbers

Generated from the code on 2026-10-18 15:59 with the **default settings**. Quote only these figures in the deck, docs and demo. Regenerate with `py run_tests.py`.

All data is synthetic (fixed seed). SACCO and bank rates are illustrative, not real quotes. Categorisation rules were written knowing the data generator, so real-world accuracy would be lower.

## Headline: Amina's credit

| Figure | Value | Source |
|---|---|---|
| Money needed to stay above the buffer (14 days) | KES 42,290 | `forecast.shortfall_alert` |
| Loan cap | KES 60,000 | `settings.defaults` |
| Recommended loan (within the cap) | SACCO loan* of KES 45,000 over 180 days | `credit.recommend` |
| Need above the loan cap? | no | `credit.headline` |
| Effective annual cost: Mobile overdraft | 275% | `credit.effective_annual_cost` |
| Effective annual cost: Mobile micro-loan | 141% | `credit.effective_annual_cost` |
| Effective annual cost: SACCO loan* | 17% | `credit.effective_annual_cost` |
| Effective annual cost: Bank SME loan* | 32% | `credit.effective_annual_cost` |
| Overdraft fees per year (habit) | KES 35,770 | `credit.headline` |
| SACCO loan* cost per year | KES 4,133 | `credit.headline` |
| **Yearly saving** | **KES 31,637** | `credit.headline` |
| Personal money now (per week) | KES 10,110 | `credit.weekly_personal` |
| **Weekly withdrawal cap** | **KES 7,346** (down KES 2,764, 27%) | `credit.personal_cap` |

## Tests and evidence

| Figure | Value | Source |
|---|---|---|
| Unit tests | 179 passed, 0 failed | `pytest` |
| Attack scorecard | 26 of 26 blocked | `attacks.py` |
| Task success, scripted mock AI | 28/28 = 100% | `evaluation.py` |
| Task success, offline keyword planner | 22/23 = 96% | `evaluation.py` |
| Number verification | 3/3 invented numbers caught; 24/24 genuine answers passed | `agent.unverified_numbers` |

## Amina's Grocery (Nairobi)

| Figure | Value | Source |
|---|---|---|
| Statement period | 2026-07-15 to 2026-10-15 (93 days) | `analytics.summarise` |
| Transactions (clean) | 3,573 | `parser.parse_statement` |
| Balance mismatches | 0 | `parser.parse_statement` |
| Categorisation accuracy | 100.0% | `build_ledger.check_accuracy` |
| Sales | KES 1,008,340 | `analytics.summarise` |
| Cash profit (sales minus business costs) | KES 125,767 | `analytics.summarise` |
| Personal money taken out | KES 156,870 (125% of cash profit) | `analytics.summarise` |
| Mobile-money balance (15 Oct) | KES 0 | `analytics.summarise` |
| Overdraft owed | KES 37,967 | `analytics.overdraft_owed_by_day` |
| True position (balance minus overdraft owed) | KES -37,967 | `analytics.true_positions` |
| Overdraft fees in the period | KES 9,114 | `analytics.summarise` |
| Overdraft used | 56 times | `analytics.summarise` |
| Safety buffer (default) | KES 1,000 | `settings.safety_buffer` |
| Caps: per payment / per day / loan | KES 35,000 / KES 60,000 / KES 60,000 | `settings.defaults` |
| 14-day forecast | ALERT on 14 of 14 days; worst Thu 22 Oct at KES -41,290; needs KES 42,290 | `forecast.forecast + shortfall_alert` |
| Forecast backtest (last 14 days hidden) | sales -3.7%; last day KES 5,880 too low; 5/14 days inside range | `forecast.backtest` |

## Grace Beauty Salon (Kisumu)

| Figure | Value | Source |
|---|---|---|
| Statement period | 2026-07-15 to 2026-10-15 (93 days) | `analytics.summarise` |
| Transactions (clean) | 956 | `parser.parse_statement` |
| Balance mismatches | 0 | `parser.parse_statement` |
| Categorisation accuracy | 99.8% | `build_ledger.check_accuracy` |
| Sales | KES 659,820 | `analytics.summarise` |
| Cash profit (sales minus business costs) | KES 193,194 | `analytics.summarise` |
| Personal money taken out | KES 155,120 (80% of cash profit) | `analytics.summarise` |
| Mobile-money balance (15 Oct) | KES 43,074 | `analytics.summarise` |
| Overdraft owed | KES 0 | `analytics.overdraft_owed_by_day` |
| True position (balance minus overdraft owed) | KES 43,074 | `analytics.true_positions` |
| Overdraft fees in the period | KES 0 | `analytics.summarise` |
| Overdraft used | 0 times | `analytics.summarise` |
| Safety buffer (default) | KES 1,000 | `settings.safety_buffer` |
| Caps: per payment / per day / loan | KES 25,000 / KES 40,000 / KES 50,000 | `settings.defaults` |
| 14-day forecast | OK: low estimate stays above the buffer | `forecast.forecast + shortfall_alert` |
| Forecast backtest (last 14 days hidden) | sales +0.5%; last day KES 3,442 too high; 11/14 days inside range | `forecast.backtest` |

## Otieno Boda Services (Nakuru)

| Figure | Value | Source |
|---|---|---|
| Statement period | 2026-07-15 to 2026-10-15 (93 days) | `analytics.summarise` |
| Transactions (clean) | 2,364 | `parser.parse_statement` |
| Balance mismatches | 0 | `parser.parse_statement` |
| Categorisation accuracy | 100.0% | `build_ledger.check_accuracy` |
| Sales | KES 304,280 | `analytics.summarise` |
| Cash profit (sales minus business costs) | KES 217,736 | `analytics.summarise` |
| Personal money taken out | KES 148,880 (68% of cash profit) | `analytics.summarise` |
| Mobile-money balance (15 Oct) | KES 28,188 | `analytics.summarise` |
| Overdraft owed | KES 0 | `analytics.overdraft_owed_by_day` |
| True position (balance minus overdraft owed) | KES 28,188 | `analytics.true_positions` |
| Overdraft fees in the period | KES 138 | `analytics.summarise` |
| Overdraft used | 10 times | `analytics.summarise` |
| Safety buffer (default) | KES 1,000 | `settings.safety_buffer` |
| Caps: per payment / per day / loan | KES 10,000 / KES 15,000 / KES 30,000 | `settings.defaults` |
| 14-day forecast | OK: low estimate stays above the buffer | `forecast.forecast + shortfall_alert` |
| Forecast backtest (last 14 days hidden) | sales -0.7%; last day KES 1,258 too low; 14/14 days inside range | `forecast.backtest` |
