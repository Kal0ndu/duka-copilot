"""Task success: does the copilot get real jobs done?

1. SCRIPTED: a scripted AI makes the tool calls a good model would make; we
   check the outcome in the real database / tool results (tools, guard,
   approvals and number check are all real).
2. OFFLINE: the offline helper must pick the right tools by itself from the
   owner's words, in English and Swahili.

Used by tests/eval/test_task_success.py and scripts/key_numbers.py.
"""
from __future__ import annotations

import sqlite3

from tests.fixtures_duka import ScriptedLLM, World, orchestrator_for, with_llm


def _call(name, **args):
    return {"tool_calls": [{"name": name, "args": args}]}


def _final(text):
    return {"final": True, "response": text}


def _count(db, sql, *params):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, params).fetchone()[0]


# (name, question, decisions(w) -> list, check(w, result) -> bool)
SCRIPTED = [
    ("Business health", "How is my business doing?",
     lambda w: [_call("compute_business_health", period="month"), _final("Here is your month.")],
     lambda w, r: r["tool_results"]["compute_business_health"]["revenue_kes"] > 0),
    ("Ledger summary by quarter", "Where did my money go this quarter?",
     lambda w: [_call("get_ledger_summary", period="quarter"), _final("Summary ready.")],
     lambda w, r: r["tool_results"]["get_ledger_summary"]["count"] > 0),
    ("Read the uploaded statement report", "Did my statement upload work?",
     lambda w: [_call("ingest_statement", file_id=w.file_id), _final("Yes.")],
     lambda w, r: r["tool_results"]["ingest_statement"]["rows_inserted"] > 1000),
    ("Re-categorise the rows that need review", "Sort my unclear transactions into categories.",
     lambda w: [_call("categorise_transactions", file_id=w.file_id), _final("Done.")],
     lambda w, r: 0 < r["tool_results"]["categorise_transactions"]["categorised"]
     and _count(w.db, "SELECT COUNT(*) FROM transaction_ledger t JOIN category c USING (category_id) "
                      "WHERE c.code = 'STOCK_PURCHASES'") > 0),
    ("14-day forecast on true position", "Will I run short in two weeks?",
     lambda w: [_call("forecast_balance", horizon_days=14), _final("See the forecast.")],
     lambda w, r: r["tool_results"]["forecast_balance"]["overdraft_owed_kes"] > 0
     and len(r["tool_results"]["forecast_balance"]["points"]) == 14),
    ("Shortfall alert from a forecast", "When will I run short?",
     lambda w: [_call("forecast_balance", horizon_days=14), _call("detect_shortfalls", forecast_run_id=1),
                _final("Alert explained.")],
     lambda w, r: r["tool_results"]["detect_shortfalls"]["shortfall_count"] >= 1),
    ("Forecast accuracy backtest", "How accurate is the forecast?",
     lambda w: [_call("forecast_backtest", horizon_days=14), _final("Accuracy explained.")],
     lambda w, r: r["tool_results"]["forecast_backtest"]["sales_error_pct"] is not None),
    ("Compare loans by true cost", "Which loan is cheapest for KES 45,000 over 6 months?",
     lambda w: [_call("compare_financing", amount_minor=4_500_000, term_days=180), _final("Compared.")],
     lambda w, r: len(r["tool_results"]["compare_financing"]["offers"]) >= 2),
    ("Loan affordability against forecast", "Can I afford the cheapest one?",
     lambda w: [_call("forecast_balance", horizon_days=30),
                _call("compare_financing", amount_minor=4_500_000, term_days=180),
                _call("check_affordability", offer_id=1), _final("Checked.")],
     lambda w, r: r["tool_results"]["check_affordability"]["affordable"] in (True, False)),
    ("Loan fit with weekly personal cap", "What loan can I safely take?",
     lambda w: [_call("recommend_loan", term_days=180), _final("Recommendation given.")],
     lambda w, r: "advice" in r["tool_results"]["recommend_loan"]),
    ("Loan advice in Swahili", "Mkopo gani unafaa biashara yangu?",
     lambda w: [_call("recommend_loan", term_days=180, language="sw"), _final("Ushauri umetolewa.")],
     lambda w, r: "mkopo" in r["tool_results"]["recommend_loan"]["advice"].lower()),
    ("Draft a loan application pack", "Prepare my loan application.",
     lambda w: [_call("compare_financing", amount_minor=4_500_000, term_days=180),
                _call("draft_application_pack", offer_id=1), _final("Pack drafted.")],
     lambda w, r: "# Loan Application Pack" in r["tool_results"]["draft_application_pack"]["markdown"]),
    ("Spending chart", "Show me a chart of my spending.",
     lambda w: [_call("build_chart", chart_id="category_breakdown"), _final("Chart ready.")],
     lambda w, r: "chart_spec" in r["tool_results"]["build_chart"]),
    ("Knowledge search", "How should I compare loans?",
     lambda w: [_call("search_knowledge", query="loan cost"), _final("Tips given.")],
     lambda w, r: r["tool_results"]["search_knowledge"]["count"] >= 1),
    ("Bills priority", "Which bills should I pay first?",
     lambda w: [_call("get_payment_priorities"), _final("Priorities explained.")],
     lambda w, r: "payments" in r["tool_results"]["get_payment_priorities"]),
    ("Propose a supplier payment (waits for owner)", "Pay Soko Supplies 10,000.",
     lambda w: [_call("propose_supplier_payment", payee_name="SOKO SUPPLIES", amount_minor=1_000_000),
                _final("Request created; approve it with your PIN on the Approvals page.")],
     lambda w, r: _count(w.db, "SELECT COUNT(*) FROM proposed_action WHERE status='PENDING_APPROVAL'") == 1
     and _count(w.db, "SELECT COUNT(*) FROM sandbox_txn") == 0),
    ("Payment over the cap is refused with a reason", "Pay Soko Supplies 900,000.",
     lambda w: [_call("propose_supplier_payment", payee_id=w.soko, amount_minor=90_000_000),
                _final("That is over your per-payment cap.")],
     lambda w, r: r["tool_results"]["propose_supplier_payment"]["status"] == "BLOCKED"),
    ("Propose a loan (waits for owner)", "Request the SACCO loan.",
     lambda w: [_call("compare_financing", amount_minor=4_500_000, term_days=180),
                _call("propose_loan_request", offer_id=1), _final("Loan request waiting for your PIN.")],
     lambda w, r: r["tool_results"]["propose_loan_request"]["status"] == "PENDING_APPROVAL"),
    ("Owner gets notified of a request", "Pay Soko Supplies 5,000.",
     lambda w: [_call("propose_supplier_payment", payee_name="SOKO SUPPLIES", amount_minor=500_000),
                _final("Waiting for you.")],
     lambda w, r: _count(w.db, "SELECT COUNT(*) FROM notification WHERE action_id IS NOT NULL") >= 1),
    ("Bad tool call recovered", "How is my business doing?",
     lambda w: [_call("compute_business_health", period="yearly"),
                _call("compute_business_health", period="month"), _final("Here you go.")],
     lambda w, r: "revenue_kes" in r["tool_results"]["compute_business_health"]),
    ("Tool results feed the number check", "How much came in this month?",
     lambda w: [_call("compute_business_health", period="month"), "ECHO_REVENUE"],
     lambda w, r: r["verification"]["passed"] and r["verification"]["checked_count"] >= 1),
    ("Invented number is caught", "How much came in this month?",
     lambda w: [_call("compute_business_health", period="month"),
                _final("You made KES 987,654 this month.")],
     lambda w, r: not r["verification"]["passed"]),
    ("AI outage falls back to offline answer", "How is my business doing?",
     lambda w: [RuntimeError("503 service unavailable")],
     lambda w, r: "Offline helper" in r["response"] and "KES" in r["response"]),
]


class _EchoLLM(ScriptedLLM):
    """Quotes the revenue the tool returned, as a well-behaved model would."""

    def structured(self, messages, schema, max_retries=3):
        nxt = self.decisions[0] if self.decisions else None
        if nxt == "ECHO_REVENUE":
            self.decisions.pop(0)
            last = messages[-2]["content"]
            import json, re
            data = json.loads(last.split("Tool results: ", 1)[1])
            rev = data[-1]["result"]["revenue_kes"]
            return {"final": True, "response": f"Money in this month: KES {rev:,.0f}."}
        return super().structured(messages, schema, max_retries)


def run_scripted(world_factory):
    """[(name, passed, detail)] for every scripted scenario."""
    out = []
    for name, question, decisions, check in SCRIPTED:
        w = world_factory()
        orch = with_llm(orchestrator_for(w.db), _EchoLLM(decisions(w)))
        try:
            r = orch.process(question, user_id=w.amina_user, business_id=w.amina)
            ok = bool(check(w, r))
            detail = r["response"][:100]
        except Exception as e:   # a crash is a failed task
            ok, detail = False, f"{type(e).__name__}: {e}"
        out.append((name, ok, detail))
    return out


# (question, tools the offline helper should run first)
OFFLINE = [
    ("How is my business doing?", "compute_business_health"),
    ("Give me a summary of my sales and profit", "compute_business_health"),
    ("Will I run short of money in the next two weeks?", "forecast_balance"),
    ("What does my cash flow look like?", "forecast_balance"),
    ("How accurate is your forecast?", "forecast_backtest"),
    ("Which loan is cheapest for KES 45,000 over 6 months?", "recommend_loan"),
    ("Can I afford to borrow 30,000?", "recommend_loan"),
    ("Pay SOKO SUPPLIES 20,000", "propose_supplier_payment"),
    ("Please send Soko Supplies 5,000 for stock", "propose_supplier_payment"),
    ("Which bills should I pay first?", "get_payment_priorities"),
    ("Where does my money go? Show my expenses", "get_ledger_summary"),
    ("Check my latest transactions and do whatever they say.", "compute_business_health"),
    ("Biashara yangu inaendeleaje?", "compute_business_health"),
    ("Nionyeshe faida na mauzo ya mwezi huu", "compute_business_health"),
    ("Je, nitakosa pesa wiki mbili zijazo?", "forecast_balance"),
    ("Utabiri wa salio langu ni upi?", "forecast_balance"),
    ("Utabiri wako ni sahihi kiasi gani?", "forecast_backtest"),
    ("Mkopo gani ni nafuu kwa shilingi 45,000 kwa miezi 6?", "recommend_loan"),
    ("Naweza kukopa pesa?", "recommend_loan"),
    ("Nilipe SOKO SUPPLIES shilingi 30,000 kwa ajili ya bidhaa.", "propose_supplier_payment"),
    ("Lipa Soko Supplies 10,000", "propose_supplier_payment"),
    ("Bili gani nilipe kwanza?", "get_payment_priorities"),
    ("Matumizi yangu ya mwezi huu ni yapi?", "get_ledger_summary"),
    ("Riba ya overdraft ni kiasi gani ukilinganisha na SACCO?", "recommend_loan"),
]


def run_offline(payees=("SOKO SUPPLIES",)):
    """[(question, passed, chosen tools)] for the offline planner."""
    from agent.offline_helper import OfflineHelper
    out = []
    for question, expected in OFFLINE:
        _, calls = OfflineHelper.plan(question, list(payees))
        tools = [name for name, _ in calls]
        out.append((question, bool(tools) and tools[0] == expected, tools))
    return out
