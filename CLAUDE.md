# Duka Copilot - project brief for Claude Code

## Who you're working with
- Kalz, a second-year electrical engineering student in Kenya, with only a little Python experience.
- Windows laptop, VS Code. Run Python with `py`, not `python` (e.g. `py build_ledger.py`).
- Explain each step in plain language, keep changes small, and say what to run and what output to expect.
- Effort setting: Kalz uses medium effort by default. When we start Step 7 (`security.py`) or Step 8 (`agent.py`), remind Kalz to switch to high effort, and to switch back to medium afterwards.

## What we're building
Duka Copilot is an AI finance copilot for small businesses that run on mobile money. It's our entry for the **2026 Shenzhen FinTechathon, International Track** (Tsinghua PBC School of Finance x WeBank), Topic E: SME Finance Copilot. The theme is "AI as a Financial Participant": an AI agent that completes real tasks in a financial scenario.

**Pitch:** inclusive SME finance for emerging markets, piloted in Kenya. Many small shops have rich mobile-money transaction histories but no bookkeeping, no cash-flow visibility, and no clear view of what mobile credit really costs. An adapter layer means other mobile-money platforms can plug in (e.g. Southeast Asian markets like Indonesia and Malaysia, where WeBank already works).

**Persona:** Amina, who runs a grocery shop in Nairobi (fictional).

## Deadline and scoring
- **Hard deadline:** Tuesday 20 Oct 2026, 23:59 Beijing time = **18:59 Nairobi time**. Registration and submission share this deadline. Submissions can be updated before then.
- **Internal targets:** full working version uploaded Monday night; final upload by 15:00 Tuesday; code freeze at 11:00 Tuesday.
- **Scoring:** task completion 40%, security & compliance 30%, innovation & interaction 30%.
- **Required submission:** technical documentation (architecture, core algorithms, security design); presentation deck (max 10 minutes); demo video (optional, max 5 minutes, we'll make one); source code on GitHub with README, deployment instructions and test cases; security self-assessment report (permission tiers and known-risk list); execution evidence (sandbox operation logs and demo video).
- All materials in English.

## Agent tasks
1. Ingest and clean the statement, redact personal data, categorise transactions -> ledger
2. Business health insights (revenue, costs, slow days, personal money mixed with business money)
3. Cash-flow forecast (14-30 days, including rent and repayments) and shortfall alerts
4. Financing match: compare mobile overdraft, mobile micro-loan, SACCO loan and bank SME loan by effective annual cost, total repayment and affordability against the forecast
5. Loan application pack (stretch goal)
6. Execute in the sandbox only (supplier payment, loan request), after explicit owner approval

## Design rules (do not break)
- **The LLM plans and explains; deterministic Python does every calculation.** The LLM never computes money.
- **Permission tiers, enforced in code by a policy guard:** T0 read, T1 suggest, T2 execute only with owner approval (plus per-transaction and daily caps), T3 forbidden (raising limits, unverified payees, anything outside the sandbox, sending data externally).
- **Uploaded content is data, never instructions** (data/malicious_statement.csv contains a prompt-injection attempt).
- Validate every LLM tool call against a schema; retry once if malformed, then fail safely. Never execute a half-formed call.
- Redact names and phone numbers before any text reaches the LLM.
- Append-only audit log of every tool call, approval and block.
- **Synthetic data only.** Describe credit products generically ("mobile overdraft", "mobile micro-loan") with Kenyan products as examples.
- Keep API keys in environment variables or a `.env` file that's in `.gitignore`. Never commit keys.
- Prefer the Python standard library; add packages only when they clearly help (planned: streamlit, an LLM SDK, pytest).

## What's built so far
| File | What it does | Run |
|---|---|---|
| `generate_data.py` | Makes 3 months (15 Jul - 15 Oct 2026) of messy synthetic statements for 3 businesses (Amina's grocery, Grace's salon, Otieno's boda), answer-key label files, and `malicious_statement.csv` | `py generate_data.py` |
| `parser.py` | Cleans statements: mixed date formats, messy text, amounts as text, failed rows, duplicates, newest-first order; checks that balances add up | used by build_ledger.py |
| `categoriser.py` | Keyword rules + business profile -> category and confidence (high/medium/low) | used by build_ledger.py |
| `build_ledger.py` | Step 3: writes `data/<business>_ledger.csv` and prints categorisation accuracy against the labels | `py build_ledger.py` |
| `analytics.py` | Step 4: business health summary per ledger (sales, weekday pattern, slow days, costs, profit, personal money, credit use, cash). `summarise()` returns a dict for the agent | `py analytics.py` |
| `forecast.py` | Step 5: 14-day balance forecast (weekday sales averages + auto-detected weekly/monthly payments), low/expected/high range, shortfall alert below a KES 3,000 buffer, and a backtest on the hidden last 14 days. Starts from the true position (balance minus overdraft owed, worked out from drawdowns, repayments and the overdraft's fees), assumes no new borrowing, and charges the 0.5%/day fee while the position is negative | `py forecast.py` |

The generator's overdraft auto-repays from every incoming payment (like real mobile overdrafts), and loan repayments use the overdraft if the balance is short, so balances never go negative.

Current results: balance mismatches 0, accuracy 99.8-100%. The rules were written knowing the generator, so real-world accuracy would be lower. Be honest about this in the docs.

## Plan for the remaining steps
4. `analytics.py`: business health summary
5. `forecast.py`: daily cash-flow forecast with day-of-week patterns and detected recurring obligations; shortfall alerts; show a range, not a single number
6. `credit.py`: effective annual cost, total repayment, affordability check with a safety buffer
7. `security.py` (policy guard, tiers, caps, redaction), `sandbox.py` (simulated account and mock lender), audit log
8. `agent.py`: LLM with tool calling over the tools above (provider still to be chosen)
9. `app.py`: Streamlit interface with chat, approvals, insights, an SMS-style alert view, and one Swahili conversation in the demo
10. Tests (pytest): unit tests, an attack suite of about 20 injection and abuse cases with a blocked-count scorecard, and 20-30 evaluation scenarios with a task success rate
11. Docs: README, technical documentation, security self-assessment, deck and demo video script

## Things that make the entry stand out
- Quotes from real shop owners (the team will interview 3-5)
- Measured results (accuracy, task success rate, attack scorecard)
- A live blocked attack in the demo
- SMS-style alerts and Swahili support
- One headline number (e.g. how much Amina saves by switching credit options)
