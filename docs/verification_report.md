# Verification report: outstanding system issues

Date: 2026-10-19 · Branch: `improved`

The assessment came first and changed no code. The fixes followed. Every
"after" claim below is backed by a test that runs against a real migrated
database (`tests/fixtures_duka.build_world`). The only thing mocked is the
LLM call.

Test results: **265 passed before the changes, 321 passed after** (265
existing + 56 new):
`PYTHONPATH= python -m pytest -p no:cacheprovider tests --ignore=tests/test_live_gemini.py`.
The live Gemini test was not run.

Status key: *implemented* = the code exists; *works* = we watched it behave
correctly; *verified* = an automated test checks it end to end.

---

## 1. LLM user context

**Before: Partially resolved.** `auth/user_context.py` builds a per-business
summary, and `agent/orchestrator.py` puts it into the system prompt. Gaps found:

| Finding | Evidence |
|---|---|
| Chat history leaked between users. The `Orchestrator` lives in `st.session_state`, and logging out did not clear it. | Probe: user A says "ACME", then user B logs in on the same browser. "ACME" appeared in user B's prompt to the LLM. |
| No ownership check. `UserContext(other_user, amina_business)` returned Amina's data. | Probe returned identical revenue |
| Context had no business profile (sector, size, goals). | `ctx["business_summary"]` held only id and name |
| Loaded statements (`parsed_transactions`, `business_profile`) also survived logout. | `render_logout_button` popped only 4 keys |

**After: Resolved (verified).**
- Logout, and every login, wipe the whole session state (`app/auth_ui._reset_session_state`).
- The orchestrator resets itself when the user changes (`Orchestrator._last_user_id`).
- `UserContext.get/refresh` call `check_access()`. A user who is neither owner nor active member gets `ContextAccessDenied`, and the attempt is logged as `UNAUTHORIZED_ACCESS`.
- `Orchestrator.process` refuses a foreign business before any LLM or tool call.
- The context now carries the sector, sub-sector, country, employees, registration and goals, plus recurring-expense instalments with `days_until_due` / `days_overdue`.
- Tests in `tests/unit/test_rbac_and_isolation.py`: `test_context_is_the_users_own_business`, `test_cannot_load_another_users_business`, `test_orchestrator_refuses_foreign_business` (the LLM is never called), and `test_conversation_does_not_leak_to_next_user`.

**Remaining:** User chat prompts are *not* PII-redacted before the LLM call
(`guard_input` is called without `redact_fn`). The Privacy page used to say
"Zero-Leak Verified"; that label is gone. Whether the answers use the data
well can only be checked with a live model (`tests/test_live_gemini.py`, not run).

## 2. Business registration persistence and CRUD

**Before: Partially resolved.** `register_business(owner_user_id=…)` writes
`business.owner_user_id` plus a `business_member` owner row, and
`_complete_login` → `get_business_for_user` finds it. The five tests in
`test_business_persistence.py` passed. Gaps:
- **The real `data/duka.db` holds 4 orphaned businesses (ids 1–4).** They have `owner_user_id = NULL` and no member row, because they were created before the link existed. Users 1–3 are sent to setup again on every login. **This explains the reported symptom.**
- Recurring expenses had create and read only: no update, delete or mark-paid. There was no input validation, and no business scoping on writes.

**After: Partially resolved.** New registrations are verified to persist. Expense CRUD now exists:
- `BusinessSetup.add/update/delete_recurring_expense`, `record_expense_payment`.
- Every write filters `WHERE business_id = ?`, and another business gets `ExpenseNotFound`.
- Validation errors come back as `ExpenseError`.
- Delete is soft (`active = 0`), so payment history stays.
- Tests: `test_another_business_cannot_touch_the_expense`, `test_invalid_input_is_rejected[6 cases]`.

**Remaining:**
- The orphaned businesses can't be relinked safely by code. Nothing records who created them, and matching on names is unreliable (users 3 and 4 share a name). The owner has to decide. Example for business 2 → user 2: `UPDATE business SET owner_user_id=2 WHERE business_id=2;` plus a matching `business_member` row.
- `update_business_profile` and the category and goal methods still don't check the caller's identity. They rely on the page passing the session's business id.
- `set_financial_goals` inserts a new row every time it saves instead of updating.
- The app restart and page refresh paths were not driven in a browser. Persistence is DB-backed, and the AppTest smoke run re-rendered every page from a fresh session.

## 3. Expense tracking and financial forecasting

**Before: Unresolved.**
| Finding | Evidence |
|---|---|
| `forecast_balance` (dashboard SMS alert, AI tool) ignored `recurring_expense` entirely | Adding 2 × KES 500,000 rent left `lowest_low_kes` unchanged |
| `generate_schedule` crashed for any expense on the 29th–31st | `ValueError: day is out of range for month` |
| Quarterly generated 12 instances per 12 months (3 years of payments) | probe |
| `next_due` never advanced; no last-paid date; overdue items vanished from "Upcoming" (`>= today` filter) | real DB rows stuck at creation date |
| Cashflow page used a hardcoded opening balance default and one manual expense; it ignored saved expenses and the owner's buffer | `3_Cashflow_Forecast.py` |
| The LLM context's own forecast dropped any bill dated before today | due-date equality match in `BalanceForecaster.forecast` |
| Auto-detect could produce cadence "other", which crashed on save | `detect_recurring_expenses` |

**After: Resolved (verified), with the recurrence model you asked for:**
- **`core/recurrence.py`** holds the model. Each expense has a frequency (daily / weekly / monthly / annual), an interval of every N units, an optional last-paid date and a next due date. Legacy cadences are kept: biweekly = weekly × 2, quarterly = monthly × 3.
- The next due date is calculated from the last payment. Month-end dates are clamped without drift (31 Jan → 28 Feb → 31 Mar). An optional fixed day of the month is supported.
- Countdowns are computed from today on every read: "Due in N days", "Due today", "Overdue by N days".
- Migration `006` adds the `last_paid_date` and `interval_count` columns. `db/migrate.ensure_006` applies it on first use.
- `record_expense_payment` logs the instalment as paid or late and moves the next due date to the period after the payment. Paying early still skips past the instalment just paid.
- **Variable amounts (per your note):** the amount entered is an approximate **monthly average**, scaled to the payment period, with a ±10% band.
  - The forecast draws each variable payment per simulated path, uniformly within ±10%.
  - Working capital reports a +10% high case (`bills_due_high_minor`, `liquidity_gap_low_minor`).
  - Bill-matching to avoid double counting uses a 10% tolerance for variable bills (2% for fixed ones).
- `forecast_balance` now subtracts recurring-expense instalments in the horizon. Overdue unpaid ones land on day 1. Past payments matching a scheduled bill are removed from the sampled history so they aren't counted twice.
- The Cashflow page includes saved expenses and the owner's buffer.
- The Expense Tracking page lists overdue instalments with countdowns.
- The Business Setup and Expense Setup pages share one editor (`app/expense_ui.py`): add, mark paid, edit, delete. After each change the AI context is refreshed.
- Tests: `tests/unit/test_recurrence.py` (24) and `tests/unit/test_expense_lifecycle.py`. For example, `test_expense_changes_the_forecast` covers add, update and delete, each moving the forecast. Other examples are `test_overdue_expense_hits_day_one`, `test_variable_expense_is_sampled_within_ten_percent` and `test_ai_context_sees_expenses_with_countdown`.

**Remaining:** The Cashflow page still samples history from the statement in
session state, not the ledger, so a rent payment in that history can be counted
twice there. `forecast_balance` has the de-duplication; the page does not.
Bills are not yet matched automatically to ledger payments (payments are recorded by hand).

## 4. Audit logs and audit data

**Before: Partially resolved.** `db/audit.py` is a real, append-only hash
chain, and its integrity tests pass. Gaps:
- **The real DB had 0 rows in `audit_log`, `audit_login` and `security_event`.**
- No login, logout, failed authentication, sign-up or denied-access event was ever written. `session_manager.log_audit` and `persist_session` are never called.
- Failed password logins had no limit.
- Logout did not revoke the token.
- The audit page was open to every user.
- "Zero-Leak Verified" was a hardcoded label.

**After: Resolved (verified).** `auth/rbac.log_security_event` writes into the hash chain (`entity_type='security'`). Each event carries a severity, the user, the resource, how it was detected and how it was handled. Events now recorded:
- `LOGIN_SUCCESS`, `LOGIN_FAILED` (unknown phone, wrong OTP, wrong password), `LOGIN_LOCKED_OUT`
- `ACCOUNT_CREATED`, `LOGOUT`
- `REVOKED_SESSION_USED`, `UNAUTHORIZED_ACCESS`, `PRIVILEGE_ESCALATION_BLOCKED`, `ADMIN_ASSIGNED`
- `INJECTION_DETECTED` (from statement ingestion)
- The existing guard events (`INPUT_BLOCKED`, `FORBIDDEN_TOOL_CALL`, `PIN_REJECTED`, …)

Login now locks after 5 failures in 15 minutes. Logout revokes the token's
`jti` (`revoked_session` table), and a reused token is refused and logged.
Tests: `test_security_events_record_detection_and_handling`,
`test_login_lockout_after_repeated_failures`, `test_logout_revokes_the_token`
and `test_injection_in_a_statement_is_a_security_event`.

**Remaining:**
- The Streamlit login handlers themselves were checked by code reading and AppTest rendering. A full OTP flow was not driven in a browser.
- IP and user-agent are not captured (Streamlit doesn't expose them easily).
- `JWT_SECRET` falls back to a public default. Set it in production. Role checks read the database, so a forged role claim doesn't help an attacker, but a forged `user_id` would.

## 5. Working capital

**Before: Unresolved.** `WorkingCapitalAnalyzer` invented the credit book:
- Receivables were 18% of each top customer's volume, with hardcoded ages and fake phone tokens ("07** *** 200").
- Payables were 22% of each supplier's volume.
- It ignored invoices, cash, stock and expenses.
- Debts 61–90 days old were labelled "90+".
- The page drafted reminder SMSs for debts that don't exist.

**After: Resolved (verified).** `core/working_capital.working_capital_position` uses only database records:
- **Current assets:** cash (latest statement balance) + unpaid invoice balances + stock at cost.
- **Current liabilities:** overdraft owed with fees + overdue recurring bills + open standing-order payments.
- **Next N days:** bills falling due, invoices due, and the liquidity gap, with a +10% high case for variable bills.

`open_invoices` ages the real invoices. The Working Capital page is rebuilt on
these, and reminders come only from real overdue invoices. The legacy analyzer
is kept for its tests, labelled ILLUSTRATIVE, and its bucket bug is fixed.
Test: `test_working_capital_uses_records`. It checks that an overdue bill moves
liabilities and net working capital by exactly its amount, that window
membership is right, and that the ±10% bound and the gap formula hold.
Sample check: Amina's statement ends at balance 0 with KES 37,966 overdraft
owed. Net working capital is −KES 52,966 with the overdue rent added, which matches the forecast's shortfall.

**Remaining:** There is no supplier-credit or payables ledger beyond recurring expenses and standing orders.

## RBAC (new)

- `app_user.account_role` is `'user'` (the default) or `'admin'`.
- A partial unique index allows **at most one admin**. A trigger refuses any account *inserted* as admin, so sign-up can never create one.
- The only way to assign the admin is `scripts/set_admin.py`, run on the server (a `--transfer` flag hands the role over atomically). No UI changes roles.
- Every check re-reads the role from the database. A token claiming `role=admin` is ignored (`test_a_forged_role_in_the_token_does_not_grant_admin`).
- `AdminAuditService` checks admin on **every** read: events, security events, chain verification, summary and accounts. The admin page (`pages/14_Admin_Security.py`) is only a second gate.
- A regular user gets a generic "You don't have permission to view this page." and the attempt is logged.
- The audit trail was removed from page 7, which every user can open.
- AppTest smoke run: a regular user on the admin page sees only the refusal; the admin sees live counts.

**Remaining:** Streamlit's automatic page list still shows "Admin Security" to
everyone (the page refuses non-admins). Hiding it needs a move to `st.navigation`.

## Database state

`data/duka.db` is not modified by these changes. Migrations 005 and 006 are
applied to it on first use or by `python db/migrate.py`. Then run
`python scripts/set_admin.py <phone>` to choose the admin.
