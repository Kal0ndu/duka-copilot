"""Offline helper: answers without the LLM, using the same tools.

Used when there is no API key, when Gemini's rate limit or daily quota is
hit, or when the AI service is down - so a demo never dies on stage.

respond() picks tools from keywords (English and Swahili), runs them through
the orchestrator's normal tool path (same guard, same audit log, same
approval rules) and formats the results in the owner's language. It can
propose a payment or loan, but - like the AI - never approve one.
answer() is the older static guidance, used when no business is loaded.
"""
from typing import Callable, Dict, List, Optional, Tuple
import re
from core.i18n import I18n, Language


def _kes(value) -> str:
    try:
        return f"KES {float(value):,.0f}"
    except (TypeError, ValueError):
        return "KES -"


_AMOUNT = re.compile(r"(?:kes|ksh|sh(?:s|ilingi)?\.?)?\s*(\d{1,3}(?:,\d{3})+|\d{3,})(?:\s*(?:k\b|bob|shillings?|shilingi))?",
                     re.IGNORECASE)
_MONTHS = re.compile(r"(\d{1,2})\s*(?:months?|miezi|mwezi)|(?:months?|miezi|mwezi)\s*(\d{1,2})", re.IGNORECASE)

# (intent, english keywords, swahili keywords). First match wins, so the
# action intents (pay, loan) come before the read-only ones.
_INTENTS = [
    # "Which bills should I pay first?" is about priorities, not a payment.
    ("bills", [r"pay first", r"\bfirst\b.*\bpay", r"which bills?", r"bills?\b.*\b(first|due)", r"standing order"],
     [r"\bkwanza\b", r"bili gani", r"malipo ya kudumu"]),
    ("pay", [r"\bpay\b", r"\bsend\b", r"\bpayment to\b"], [r"\blipa\b", r"\bnilipe\b", r"\btuma\b"]),
    ("loan", [r"\bloan\b", r"\bborrow", r"\bcredit\b", r"\bfinanc", r"\boverdraft\b", r"\binterest\b"],
     [r"\bmkopo\b", r"\bmikopo\b", r"\bkukopa\b", r"\bkopa\b", r"\briba\b"]),
    ("accuracy", [r"accura", r"backtest", r"how good is the forecast", r"reliab"], [r"\bsahihi\b", r"usahihi"]),
    ("forecast", [r"forecast", r"run short", r"shortfall", r"next (two|2) weeks", r"next \d+ days",
                  r"run out", r"cash ?flow", r"balance"],
     [r"utabiri", r"upungufu", r"wiki mbili", r"nitakosa", r"\bsalio\b", r"pesa zitatosha"]),
    ("bills", [r"\bbills?\b", r"\brent\b.*due", r"what.*due"], [r"\bbili\b", r"\bkodi\b"]),
    ("spending", [r"spend", r"expens", r"categor", r"where.*money go", r"costs?\b", r"transactions?"],
     [r"matumizi", r"gharama", r"miamala"]),
    ("health", [r"how is my business", r"how('s| is) business", r"doing", r"profit", r"health", r"sales",
                r"revenue", r"margin", r"summary", r"overview"],
     [r"biashara yangu", r"inaendeleaje", r"faida", r"mauzo", r"hali ya biashara"]),
]

_TEXT = {
    "en": {
        "offline_note": "_(Offline helper: these figures come straight from your data.)_",
        "busy": "The AI service is busy right now (too many requests per minute), so I answered with the "
                "offline helper instead.",
        "daily": "The AI service's daily limit is used up (it resets in about {hours} hours), so I answered "
                 "with the offline helper instead.",
        "down": "I couldn't reach the AI service, so I answered with the offline helper instead.",
        "no_data": "I don't have any transactions for your business yet. Upload your M-Pesa statement on the "
                   "**Upload Statement** page and ask again.",
        "health": "**Last {period}** ({start} to {end}): money in {rev}, business costs {costs} "
                  "(margin {margin:.1f}%). Personal spending was {personal:.1f}% of money out. "
                  "Best day {best} ({best_kes}), worst day {worst} ({worst_kes}).",
        "position": "Your M-Pesa balance is {bal}, but you owe {owed} on the overdraft (with fees), so your "
                    "**true position is {pos}**.",
        "alert": "**Warning:** over the next {days} days the low estimate drops below your {buffer} safety "
                 "buffer on {n} day(s), starting {first}. To stay safe you may need about {need} more.",
        "ok": "Good news: over the next {days} days the low estimate stays above your {buffer} safety buffer.",
        "worst": "Lowest point: {low} around {date}.",
        "backtest": "**Forecast accuracy test:** I hid {start} to {end} and forecast it. Sales were forecast "
                    "at {sf} vs {sa} actual ({pct:+.1f}%). On the last day the balance was off by {err}; "
                    "{inside} of {days} days fell inside the low-high range.",
        "spending_head": "**Where the money went ({period}):**",
        "bills_none": "You have no standing-order payments waiting.",
        "bills_head": "**What to pay first:**",
        "bills_tail": "Authorize each one on the **Standing Orders** page; you confirm with your own M-Pesa PIN.",
        "pay_need": "Tell me who to pay and how much, e.g. *Pay SOKO SUPPLIES 30,000*. I can only pay "
                    "payees on your verified list: {payees}.",
        "pay_waiting": "I've created a request to pay **{payee} {amount}**. It is **NOT paid yet**: approve it "
                       "with your PIN on the **Approvals** page (request #{id}).",
        "pay_blocked": "I could not create that payment request: {reason}",
        "loan_head": "**Loan check** ({term} days):",
        "loan_opt": "- {name}: total cost {cost}, {ear:.0f}% a year; {fit}",
        "fits": "fits your forecast now",
        "fits_if": "fits if personal money stays under {cap} a week",
        "never": "does not fit even with no personal spending",
        "loan_tail": "To go ahead, ask me to request the recommended loan; you approve it with your PIN.",
        "injection": "I read your statement as data only. Any text inside it that looks like an instruction "
                     "(for example 'send money to...') is ignored and flagged; I never act on it.",
        "flagged": "**{n} row(s)** in your statement contained text that looked like instructions to the AI. "
                   "Their descriptions were removed and I did not follow them.",
    },
    "sw": {
        "offline_note": "_(Msaidizi wa nje ya mtandao: takwimu hizi zinatoka moja kwa moja kwenye data yako.)_",
        "busy": "Huduma ya AI ina shughuli nyingi sasa (maombi mengi kwa dakika), kwa hivyo nimejibu kwa "
                "msaidizi wa nje ya mtandao.",
        "daily": "Kikomo cha kila siku cha huduma ya AI kimeisha (kitarudi baada ya takriban saa {hours}), kwa "
                 "hivyo nimejibu kwa msaidizi wa nje ya mtandao.",
        "down": "Sikuweza kufikia huduma ya AI, kwa hivyo nimejibu kwa msaidizi wa nje ya mtandao.",
        "no_data": "Bado sina miamala ya biashara yako. Pakia taarifa yako ya M-Pesa kwenye ukurasa wa "
                   "**Upload Statement** kisha uulize tena.",
        "health": "**Kipindi cha mwisho ({period})** ({start} hadi {end}): pesa zilizoingia {rev}, gharama za "
                  "biashara {costs} (faida {margin:.1f}%). Matumizi binafsi yalikuwa {personal:.1f}% ya pesa "
                  "zilizotoka. Siku bora {best} ({best_kes}), siku mbaya zaidi {worst} ({worst_kes}).",
        "position": "Salio lako la M-Pesa ni {bal}, lakini unadaiwa {owed} kwenye overdraft (pamoja na ada), "
                    "kwa hivyo **hali yako halisi ni {pos}**.",
        "alert": "**Tahadhari:** katika siku {days} zijazo, makadirio ya chini yanashuka chini ya akiba yako ya "
                 "usalama ya {buffer} kwa siku {n}, kuanzia {first}. Ili kuwa salama unaweza kuhitaji takriban "
                 "{need} zaidi.",
        "ok": "Habari njema: katika siku {days} zijazo, makadirio ya chini yanabaki juu ya akiba yako ya "
              "usalama ya {buffer}.",
        "worst": "Kiwango cha chini kabisa: {low} karibu {date}.",
        "backtest": "**Jaribio la usahihi wa utabiri:** nilificha {start} hadi {end} na kutabiri. Mauzo "
                    "yalitabiriwa {sf} dhidi ya {sa} halisi ({pct:+.1f}%). Siku ya mwisho salio lilitofautiana "
                    "kwa {err}; siku {inside} kati ya {days} zilikuwa ndani ya kiwango cha chini hadi juu.",
        "spending_head": "**Pesa zilikoenda ({period}):**",
        "bills_none": "Huna malipo ya kudumu yanayosubiri.",
        "bills_head": "**Lipa haya kwanza:**",
        "bills_tail": "Idhinisha kila moja kwenye ukurasa wa **Standing Orders**; unathibitisha kwa PIN yako "
                      "ya M-Pesa.",
        "pay_need": "Niambie nimlipe nani na kiasi gani, k.m. *Lipa SOKO SUPPLIES 30,000*. Ninaweza kulipa tu "
                    "wapokeaji walio kwenye orodha yako iliyothibitishwa: {payees}.",
        "pay_waiting": "Nimeunda ombi la kulipa **{payee} {amount}**. **BADO HALIJALIPWA**: liidhinishe kwa "
                       "PIN yako kwenye ukurasa wa **Approvals** (ombi #{id}).",
        "pay_blocked": "Sikuweza kuunda ombi hilo la malipo: {reason}",
        "loan_head": "**Ukaguzi wa mkopo** (siku {term}):",
        "loan_opt": "- {name}: gharama jumla {cost}, {ear:.0f}% kwa mwaka; {fit}",
        "fits": "unafaa utabiri wako sasa",
        "fits_if": "unafaa ukiweka matumizi binafsi chini ya {cap} kwa wiki",
        "never": "haufai hata bila matumizi binafsi",
        "loan_tail": "Ukitaka kuendelea, niambie niombe mkopo uliopendekezwa; utauidhinisha kwa PIN yako.",
        "injection": "Ninasoma taarifa yako kama data tu. Maandishi yoyote ndani yake yanayoonekana kama agizo "
                     "(k.m. 'tuma pesa kwa...') yanapuuzwa na kuwekwa alama; sitayafuata kamwe.",
        "flagged": "**Safu {n}** kwenye taarifa yako zilikuwa na maandishi yaliyoonekana kama maagizo kwa AI. "
                   "Maelezo yake yaliondolewa na sikuyafuata.",
    },
}

_CATEGORY_SW = {
    "SALES_TILL": "Mauzo (Till)", "SALES_TRANSFER": "Mauzo (kutumiwa pesa)",
    "STOCK_PURCHASES": "Ununuzi wa bidhaa", "RENT": "Kodi ya nyumba", "UTILITIES": "Umeme na maji",
    "WAGES": "Mishahara", "TRANSPORT": "Usafiri", "AIRTIME_DATA": "Muda wa maongezi na data",
    "SCHOOL_FEES": "Karo ya shule", "LOAN_REPAYMENT": "Malipo ya mkopo", "TXN_CHARGES": "Ada za miamala",
    "FAMILY_TRANSFER": "Pesa kwa familia", "PERSONAL_WITHDRAWAL": "Kutoa pesa binafsi",
    "LOAN_DISBURSEMENT": "Mkopo uliopokelewa", "UNCLASSIFIED": "Haijapangwa", "UNCATEGORISED": "Haijapangwa",
}


class OfflineHelper:
    """Provides answers without the LLM when the API key or network is unavailable.

    This enables a demo to work even if the API key is missing or rate-limited.
    Supports both English and Swahili.
    """

    # ---- planning ----

    @staticmethod
    def detect_intent(query: str) -> str:
        q = query.lower()
        if re.search(r"ignore|do whatever|instruction|they say", q):
            return "injection"
        for intent, en, sw in _INTENTS:
            if any(re.search(p, q) for p in en + sw):
                return intent
        return "unknown"

    @staticmethod
    def extract_amount_minor(query: str) -> Optional[int]:
        best = None
        for m in _AMOUNT.finditer(query):
            value = int(m.group(1).replace(",", ""))
            if re.search(r"\d\s*k\b", m.group(0), re.IGNORECASE):
                value *= 1000
            if value >= 100 and (best is None or value > best):
                best = value
        return best * 100 if best else None

    @staticmethod
    def extract_term_days(query: str) -> Optional[int]:
        m = _MONTHS.search(query)
        if m:
            return max(1, min(12, int(m.group(1) or m.group(2)))) * 30
        m = re.search(r"(\d{2,3})\s*(?:days?|siku)", query, re.IGNORECASE)
        return int(m.group(1)) if m else None

    @classmethod
    def plan(cls, query: str, payees: List[str]) -> Tuple[str, List[Tuple[str, dict]]]:
        """(intent, [(tool, args)]) for a question."""
        intent = cls.detect_intent(query)
        if intent == "pay":
            amount = cls.extract_amount_minor(query)
            q = query.upper()
            payee = next((p for p in sorted(payees, key=len, reverse=True) if p.upper() in q), None)
            if payee is None:
                # The name the owner typed, so look-alikes are caught by the guard.
                m = re.search(r"(?:pay|lipa|nilipe|tuma)\s+(?:to\s+|kwa\s+)?([A-Za-z][A-Za-z0-9 &.'-]{2,40}?)"
                              r"\s+(?:kes|ksh|sh|shilingi|\d)", query, re.IGNORECASE)
                payee = m.group(1).strip() if m else None
            if not amount or not payee:
                return "pay_need", []
            return intent, [("propose_supplier_payment", {"payee_name": payee, "amount_minor": amount})]
        if intent == "loan":
            args = {"term_days": cls.extract_term_days(query) or 180}
            amount = cls.extract_amount_minor(query)
            if amount and amount >= 100_000:
                args["amount_minor"] = amount
            return intent, [("recommend_loan", args)]
        if intent == "forecast":
            return intent, [("forecast_balance", {"horizon_days": 14})]
        if intent == "accuracy":
            return intent, [("forecast_backtest", {"horizon_days": 14})]
        if intent == "bills":
            return intent, [("get_payment_priorities", {})]
        if intent == "spending":
            return intent, [("get_ledger_summary", {"period": "month"})]
        if intent == "health":
            return intent, [("compute_business_health", {"period": "month"}),
                            ("forecast_balance", {"horizon_days": 14})]
        if intent == "injection":
            return intent, [("compute_business_health", {"period": "month"})]
        return intent, []

    # ---- answering with the user's own data ----

    @classmethod
    def respond(cls, query: str, language: Language, run_tool: Callable[[str, dict], dict],
                payees: Optional[List[str]] = None, notice: Optional[str] = None,
                flagged_rows: int = 0) -> str:
        """Plan, run the tools, and write the answer. `notice` is 'busy',
        'daily:<hours>' or 'down' when the AI failed (shown first)."""
        lang = "sw" if language == Language.SWAHILI else "en"
        t = _TEXT[lang]
        payees = payees or []
        intent, calls = cls.plan(query, payees)
        parts = []
        if notice:
            kind, _, hours = notice.partition(":")
            parts.append(t[kind].format(hours=hours or "24"))

        if intent == "pay_need":
            parts.append(t["pay_need"].format(payees=", ".join(payees) or "-"))
        elif not calls:
            static = cls.answer(query, language)
            parts.append(static)
        else:
            results = {}
            for name, args in calls:
                if name == "recommend_loan":
                    args = dict(args, language=lang)
                results[name] = run_tool(name, args)
            if all("error" in r for r in results.values()) and any(
                    "Upload" in str(r.get("error")) or "No transaction" in str(r.get("error"))
                    for r in results.values()):
                parts.append(t["no_data"])
            else:
                parts.extend(cls._format(intent, results, t, lang))
            if intent == "injection":
                parts.append(t["injection"])
                if flagged_rows:
                    parts.append(t["flagged"].format(n=flagged_rows))
        parts.append(t["offline_note"])
        return "\n\n".join(p for p in parts if p)

    @classmethod
    def _format(cls, intent: str, results: Dict[str, dict], t: dict, lang: str) -> List[str]:
        out = []
        h = results.get("compute_business_health")
        if h and "error" not in h and h.get("transaction_count"):
            period_names = {"en": {"day": "day", "week": "7 days", "month": "30 days", "quarter": "quarter"},
                            "sw": {"day": "siku", "week": "siku 7", "month": "siku 30", "quarter": "robo mwaka"}}
            out.append(t["health"].format(
                period=period_names[lang].get(h["period"], h["period"]), start=h["from_date"], end=h["to_date"], rev=_kes(h["revenue_kes"]),
                costs=_kes(h["costs_kes"]), margin=h["margin_pct"], personal=h["personal_mix_pct"],
                best=h["best_day"], best_kes=_kes(h["best_day_cashflow_kes"]),
                worst=h["worst_day"], worst_kes=_kes(h["worst_day_cashflow_kes"])))
        f = results.get("forecast_balance")
        if f and "error" not in f:
            out.append(t["position"].format(bal=_kes(f["balance_kes"]), owed=_kes(f["overdraft_owed_kes"]),
                                            pos=_kes(f["true_position_kes"])))
            below = [p for p in f["points"] if p["low_kes"] < f["buffer_kes"]]
            if below:
                need = f["buffer_kes"] - f["lowest_low_kes"]
                out.append(t["alert"].format(days=f["horizon_days"], buffer=_kes(f["buffer_kes"]),
                                             n=len(below), first=below[0]["date"], need=_kes(need)))
            else:
                out.append(t["ok"].format(days=f["horizon_days"], buffer=_kes(f["buffer_kes"])))
            out.append(t["worst"].format(low=_kes(f["lowest_low_kes"]), date=f["lowest_low_date"]))
        b = results.get("forecast_backtest")
        if b and "error" not in b:
            out.append(t["backtest"].format(
                start=b["test_start"], end=b["test_end"], sf=_kes(b["sales_forecast_kes"]),
                sa=_kes(b["sales_actual_kes"]), pct=b["sales_error_pct"] or 0,
                err=_kes(abs(b["final_balance_error_kes"])), inside=b["days_inside_range"], days=b["days"]))
        s = results.get("get_ledger_summary")
        if s and "error" not in s:
            rows = [r for r in s["summary"] if r["direction"] == "out"]
            latest = rows[0]["period"] if rows else None
            top = sorted([r for r in rows if r["period"] == latest], key=lambda r: -r["total_kes"])[:6]
            out.append(t["spending_head"].format(period=latest or "-"))
            out.append("\n".join(
                f"- {_CATEGORY_SW.get(r['category'], r['category']) if lang == 'sw' else r['category'].replace('_', ' ').title()}: "
                f"{_kes(r['total_kes'])} ({r['transaction_count']})" for r in top))
        p = results.get("get_payment_priorities")
        if p and "error" not in p:
            if not p["payments"]:
                out.append(t["bills_none"])
            else:
                out.append(t["bills_head"])
                out.append("\n".join(f"{i}. {x['label']}: {_kes(x['amount_kes'])} due {x['due_date']} "
                                     f"({x['priority_band']})" for i, x in enumerate(p["payments"][:5], 1)))
                out.append(t["bills_tail"])
        pay = results.get("propose_supplier_payment")
        if pay:
            if pay.get("status") == "PENDING_APPROVAL":
                out.append(t["pay_waiting"].format(payee=pay["payee"], amount=_kes(pay["amount_kes"]),
                                                   id=pay["action_id"]))
            else:
                out.append(t["pay_blocked"].format(reason=pay.get("reason") or pay.get("error")))
        loan = results.get("recommend_loan")
        if loan and "error" not in loan and loan.get("no_need"):
            out.append(loan["advice"])
        elif loan and "error" not in loan:
            out.append(t["loan_head"].format(term=loan["term_days"]))
            lines = []
            for o in loan["options"]:
                cap = o["max_weekly_personal_minor"]
                fit = t["fits"] if o["fits_now"] else (t["never"] if cap is None
                                                        else t["fits_if"].format(cap=_kes(cap / 100)))
                lines.append(t["loan_opt"].format(name=o["product_name"], cost=_kes(o["tcc_minor"] / 100),
                                                  ear=o["ear_pct"], fit=fit))
            out.append("\n".join(lines))
            out.append(loan["advice"])
            if loan.get("best"):
                out.append(t["loan_tail"])
        errors = [r["error"] for r in results.values() if isinstance(r, dict) and "error" in r]
        if errors and not out:
            out.append(errors[0])
        return out

    # ---- static guidance (no business data needed) ----

    # Knowledge base: patterns and responses
    _PATTERNS = [
        # Cash flow queries
        {
            "patterns": [r"cash\s*flow", r"balance", r"how\s+much\s+money", r"current\s+balance",
                        r"salio", r"kiasi\s+gani", r"pesa\s+ngapi"],
            "response_en": "To check your cash flow: Upload a recent statement using the 'Upload Statement' page, "
                          "and I'll analyze your daily inflows and outflows. I can then show you a forecast and "
                          "alert you to potential shortfalls where your balance drops below a safety buffer.",
            "response_sw": "Ili kuangalia mzunguko wa pesa zako: pakia taarifa ya karibuni kwenye ukurasa wa "
                          "'Upload Statement', nami nitachambua pesa zinazoingia na kutoka kila siku. Kisha "
                          "nitakuonyesha utabiri na kukuonya mapema salio lako likikaribia kushuka chini ya "
                          "akiba ya usalama.",
        },
        # Forecast queries
        {
            "patterns": [r"forecast", r"predict", r"next\s+\d+\s+days?", r"will\s+i\s+run\s+out",
                        r"utabiri", r"nitakosa"],
            "response_en": "I can forecast your balance for the next 14-90 days using patterns from your transaction history. "
                          "This shows a conservative (P10), expected (P50), and optimistic (P90) projection. "
                          "To get started: Upload your M-Pesa statement in the 'Upload Statement' tab.",
            "response_sw": "Ninaweza kutabiri salio lako kwa siku 14 hadi 90 zijazo kwa kutumia mwenendo wa "
                          "miamala yako. Utaona makadirio ya chini (P10), yanayotarajiwa (P50) na ya juu (P90). "
                          "Ili kuanza: pakia taarifa yako ya M-Pesa kwenye ukurasa wa 'Upload Statement'.",
        },
        # Loan/financing queries
        {
            "patterns": [r"loan", r"credit", r"borrow", r"financing", r"interest",
                        r"mkopo", r"mikopo", r"riba"],
            "response_en": "I can compare digital credit products available to you. Here's what I check:\n"
                          "• Total Cost of Credit (interest + fees)\n"
                          "• Effective annual rate, so a 30-day loan compares fairly with a 6-month one\n"
                          "• Whether the repayments fit your cash flow forecast\n\n"
                          "To compare options: Go to the 'Financing' tab and enter your needed amount and term.",
            "response_sw": "Ninaweza kulinganisha mikopo ya kidijitali inayopatikana kwako. Ninaangalia:\n"
                          "• Gharama jumla ya mkopo (riba + ada)\n"
                          "• Gharama ya mwaka mzima, ili mkopo wa siku 30 ulinganishwe kwa haki na wa miezi 6\n"
                          "• Kama marejesho yanatoshea katika utabiri wa pesa zako\n\n"
                          "Ili kulinganisha: nenda kwenye ukurasa wa 'Financing' na uweke kiasi na muda unaohitaji.",
        },
        # How to use the app
        {
            "patterns": [r"how\s+do\s+i", r"how\s+to", r"what\s+is", r"get\s+started", r"tutorial",
                        r"vipi", r"nianze", r"kuanza", r"mwongozo"],
            "response_en": "Getting started with Duka:\n"
                          "1. **Upload Statement** → M-Pesa PDF or CSV\n"
                          "2. **Review Ledger** → Verify categorizations\n"
                          "3. **View Insights** → Revenue, costs, margins, best days\n"
                          "4. **Forecast** → See 14-30 day balance with alerts\n"
                          "5. **Financing** → Compare credit options by cost\n"
                          "6. **Standing Orders** → Schedule recurring payments\n"
                          "7. **Approvals** → Approve what the assistant proposes, with your PIN\n"
                          "8. **Chat** → Ask me questions about your business",
            "response_sw": "Kuanza na Duka:\n"
                          "1. **Upload Statement** → pakia taarifa ya M-Pesa (PDF au CSV)\n"
                          "2. **Kagua miamala** → thibitisha aina za matumizi\n"
                          "3. **Uchambuzi** → mapato, gharama, faida, siku bora\n"
                          "4. **Utabiri** → salio la siku 14 hadi 30 pamoja na tahadhari\n"
                          "5. **Financing** → linganisha mikopo kwa gharama halisi\n"
                          "6. **Standing Orders** → panga malipo ya kudumu\n"
                          "7. **Approvals** → idhinisha anachopendekeza msaidizi, kwa PIN yako\n"
                          "8. **Mazungumzo** → niulize maswali kuhusu biashara yako",
        },
    ]

    @classmethod
    def answer(cls, query: str, language: Language = Language.ENGLISH) -> Optional[str]:
        """Return a rule-based answer if query matches a pattern.

        Args:
            query: User's question
            language: Language to respond in

        Returns:
            Response in the requested language (generic help if nothing matches).
        """
        query_lower = query.lower().strip()

        for pattern_group in cls._PATTERNS:
            for pattern in pattern_group["patterns"]:
                if re.search(pattern, query_lower):
                    if language == Language.SWAHILI:
                        return pattern_group.get("response_sw", pattern_group.get("response_en"))
                    else:
                        return pattern_group.get("response_en")

        # Fallback for unmatched queries
        return cls.get_generic_response(language)

    @classmethod
    def get_generic_response(cls, language: Language = Language.ENGLISH) -> str:
        """Return a generic helpful response for unmatched queries."""
        if language == Language.SWAHILI:
            return (
                "Ninaweza kusaidia na maswali kuhusu:\n"
                "• Biashara yako inaendeleaje (mauzo, gharama, faida)\n"
                "• Utabiri wa salio na tahadhari za upungufu\n"
                "• Mikopo: ipi ni nafuu na kama inatoshea\n"
                "• Matumizi binafsi dhidi ya ya biashara\n"
                "• Malipo ya kudumu: lipi lilipwe kwanza\n"
                "• Kuomba malipo kwa mpokeaji aliyethibitishwa (wewe unaidhinisha kwa PIN)\n\n"
                "Jaribu kuuliza: 'Biashara yangu inaendeleaje?' au 'Nitakosa pesa wiki mbili zijazo?'"
            )
        else:
            return (
                "I can help with questions about:\n"
                "• How your business is doing (sales, costs, profit)\n"
                "• Balance forecasting and shortfall warnings\n"
                "• Loans: which is cheapest and whether it fits\n"
                "• Personal spending vs business spending\n"
                "• Standing orders: what to pay first\n"
                "• Requesting a payment to a verified payee (you approve with your PIN)\n\n"
                "Try asking: 'How is my business doing?' or 'Will I run short in the next two weeks?'"
            )

    @classmethod
    def get_welcome_message(cls, language: Language = Language.ENGLISH) -> str:
        """Return a welcome message for offline mode."""
        if language == Language.SWAHILI:
            return (
                "👋 Karibu Duka Copilot!\n\n"
                "Kwa sasa ninafanya kazi bila huduma ya AI (hakuna muunganisho). Bado ninaweza kujibu "
                "kwa kutumia takwimu za biashara yako:\n\n"
                "**Ninachoweza kufanya:**\n"
                "• Kueleza hali ya biashara yako, utabiri na mikopo\n"
                "• Kukuongoza kutumia sehemu za Duka\n"
                "• Kuomba malipo, ambayo wewe unaidhinisha kwa PIN yako\n\n"
                "**Kurudisha AI kamili:**\n"
                "1. Angalia LLM_API_KEY kwenye mipangilio\n"
                "2. Hakikisha una mtandao\n"
                "3. Au niulize kitu kama: 'Nianze vipi?'"
            )
        else:
            return (
                "👋 Welcome to Duka Copilot!\n\n"
                "I'm temporarily running in offline mode (no AI connection). "
                "I can still answer using your own business figures:\n\n"
                "**What I can do:**\n"
                "• Explain how your business is doing, your forecast and loan options\n"
                "• Guide you through using Duka features\n"
                "• Request a payment, which you approve with your PIN\n\n"
                "**To unlock full AI features:**\n"
                "1. Check your LLM_API_KEY configuration\n"
                "2. Ensure you have internet connectivity\n"
                "3. Or ask me something like: 'How do I get started?'"
            )

    @classmethod
    def get_api_key_error_message(cls, language: Language = Language.ENGLISH) -> str:
        """Return a message when API key is missing."""
        if language == Language.SWAHILI:
            return (
                "⚠️ Ufunguo wa API haupo\n\n"
                "Ninafanya kazi bila huduma ya AI kwa sababu hakuna ufunguo wa API uliowekwa. "
                "Bado ninaweza kujibu maswali kwa takwimu zako!\n\n"
                "Ili kuwasha AI kamili, weka **LLM_API_KEY** kwenye faili yako ya `.env`."
            )
        else:
            return (
                "⚠️ API Key Missing\n\n"
                "I'm running in offline mode because no API key was configured. "
                "I can still answer using your own figures!\n\n"
                "To enable full AI features, set **LLM_API_KEY** in your `.env` file."
            )
