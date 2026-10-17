"""
providers.py - the AI "brain", kept behind one small interface
================================================================

agent.py only ever calls  provider.respond(system, history, tools)  and gets a
Reply back (some text and/or tool calls). To use a different AI company later,
write one new class with the same respond() method. Nothing else changes.

  GeminiProvider  - Google's Gemini API through the official google-genai SDK
  OfflineProvider - a rule-based stand-in so the app runs with no API key
                    (for judges). It goes through exactly the same checks.

History format (the same for every provider):
  {"role": "user", "text": "...", "lang": "en" | "sw"}
  {"role": "assistant", "text": "...", "tool_calls": [ToolCall], "raw": <provider's own copy>}
  {"role": "tool", "results": [{"id": ..., "name": ..., "content": {...}}]}
"""

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str = ""


@dataclass
class Reply:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    raw: object = None          # the provider's own record of this turn


class Provider:
    name = "base"

    def respond(self, system, history, tools):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------

SWAHILI_WORDS = {
    "je", "nini", "mauzo", "pesa", "biashara", "yangu", "wangu", "yako", "wiki", "hii",
    "kwa", "na", "ya", "za", "mkopo", "nilipe", "lipa", "mlipe", "shilingi", "bidhaa",
    "ajili", "itatosha", "siku", "zijazo", "ijayo", "habari", "tafadhali", "ninaweza",
    "naweza", "kiasi", "gani", "hali", "faida", "deni", "nina", "sina", "miezi", "mbili",
    "nitakosa", "upungufu", "miamala", "taarifa", "nafuu", "zaidi", "inaendeleaje",
}


def detect_language(text):
    """'sw' if the text has at least two common Swahili words, else 'en'."""
    words = re.findall(r"[a-z]+", text.lower())
    return "sw" if sum(w in SWAHILI_WORDS for w in words) >= 2 else "en"


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class RateLimitError(Exception):
    """The AI service is still saying 'too many requests' after our retries.
    daily=True means the DAILY quota is used up: retrying soon won't help."""

    def __init__(self, message, daily=False, retry_after=None):
        super().__init__(message)
        self.daily, self.retry_after = daily, retry_after


def retry_delay(error, default=15):
    """Seconds the service asked us to wait (its 'retryDelay'), else the default."""
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s", str(error.details))
    return float(match.group(1)) if match else default


def is_daily_limit(error, delay):
    """A per-day quota (or a wait of over a minute) can't be fixed by retrying now."""
    return "PerDay" in str(error.details) or delay > 60


class GeminiProvider(Provider):
    name = "Gemini"
    MAX_RETRIES = 3                 # extra tries after a "too many requests" (429) error
    _recent_calls = deque()         # shared by every Gemini provider in this program,
    _lock = threading.Lock()        # so the whole app stays under the per-minute limit

    def __init__(self, api_key, model, per_minute=5):
        from google import genai            # imported here so offline mode needs no SDK
        from google.genai import errors, types
        self.types, self.errors = types, errors
        self.model = model
        self.name = f"Gemini ({model})"
        self.client = genai.Client(api_key=api_key)
        self.per_minute = per_minute        # free tier: 5 requests per minute
        self.on_wait = None                 # function(seconds): show "Waiting for the AI service..."

    def _wait(self, seconds):
        if self.on_wait:
            self.on_wait(seconds)
        time.sleep(seconds)

    def _space_calls(self):
        """Wait until fewer than `per_minute` calls were made in the last 60 seconds."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._recent_calls and now - self._recent_calls[0] >= 60:
                    self._recent_calls.popleft()
                if len(self._recent_calls) < self.per_minute:
                    self._recent_calls.append(now)
                    return
                wait = 60 - (now - self._recent_calls[0]) + 0.5
            self._wait(wait)

    def _generate(self, contents, config):
        """One AI call, spaced out, retrying up to 3 times on 'too many requests'."""
        for attempt in range(self.MAX_RETRIES + 1):
            self._space_calls()
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config)
            except self.errors.ClientError as e:
                if e.code != 429:
                    raise
                delay = retry_delay(e)
                if is_daily_limit(e, delay):
                    raise RateLimitError("daily quota used up", daily=True,
                                         retry_after=delay) from e
                if attempt == self.MAX_RETRIES:
                    raise RateLimitError("still too many requests after retrying") from e
                self._wait(delay)

    def respond(self, system, history, tools):
        t = self.types
        declarations = [t.FunctionDeclaration(name=name, description=spec["description"],
                                              parameters_json_schema=spec["parameters"])
                        for name, spec in tools.items()]
        config = t.GenerateContentConfig(
            system_instruction=system,
            tools=[t.Tool(function_declarations=declarations)],
            # Our code runs every tool (after checking it), never the SDK by itself
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._generate(self._contents(history), config)

        content = response.candidates[0].content if response.candidates else None
        parts = (content.parts or []) if content else []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = [ToolCall(fc.name or "", dict(fc.args or {}), fc.id or "")
                 for fc in (response.function_calls or [])]
        return Reply(text=text, tool_calls=calls, raw=content)

    def _contents(self, history):
        t = self.types
        contents = []
        for m in history:
            if m["role"] == "user":
                text = m["text"]
                if m.get("lang") == "sw":
                    text += "\n\n[App note: the owner wrote in Swahili. Reply in Swahili.]"
                contents.append(t.Content(role="user", parts=[t.Part(text=text)]))
            elif m["role"] == "assistant":
                # Send back Gemini's own turn exactly as received (keeps its
                # "thought signatures", which Gemini 3 models need)
                contents.append(m["raw"] if m.get("raw") is not None else
                                t.Content(role="model", parts=[t.Part(text=m["text"])]))
            elif m["role"] == "tool":
                parts = [t.Part(function_response=t.FunctionResponse(
                            id=r["id"] or None, name=r["name"], response=r["content"]))
                         for r in m["results"]]
                contents.append(t.Content(role="user", parts=parts))
        return contents


# ---------------------------------------------------------------------------
# Offline demo
# ---------------------------------------------------------------------------

def parse_amounts(text):
    """'pay 30,000 then 5000' -> [30000, 5000]"""
    return [int(a.replace(",", "")) for a in re.findall(r"\d{1,3}(?:,\d{3})+|\d+", text)
            if int(a.replace(",", "")) >= 100]


def kes(x):
    return f"KES {x:,.0f}"


class OfflineProvider(Provider):
    """Picks a tool by keywords, then fills an answer template from the tool's
    result. Simple, but it uses the same schema checks, guard and audit log."""
    name = "offline demo (no API key)"

    def __init__(self, payees):
        self.payees = payees        # payee_id -> name

    def respond(self, system, history, tools):
        last = history[-1]
        if last["role"] == "user":
            return Reply(tool_calls=[self._plan(last["text"])])
        lang = next(m.get("lang", "en") for m in reversed(history) if m["role"] == "user")
        text = "\n".join(self._answer(r["name"], r["content"], lang) for r in last["results"])
        return Reply(text=text)

    def _plan(self, text):
        t = text.lower()
        amounts = parse_amounts(t)
        loan = any(w in t for w in ("loan", "mkopo", "credit", "borrow", "kukopa"))
        if loan and any(w in t for w in ("take", "get ", "apply", "request", "chukua", "omba")):
            months = re.search(r"(\d+)\s*(?:months?|miezi)", t)
            days = (int(months.group(1)) * 30 if months else
                    365 if ("year" in t or "mwaka" in t) else 180)
            product = ("bank" if "bank" in t or "benki" in t else
                       "micro_loan" if "micro" in t or "mobile" in t else "sacco")
            return ToolCall("propose_loan", {"product": product, "term_days": days,
                                             "amount": amounts[0] if amounts else 0})
        if any(w in t for w in ("pay ", "lipa", "nilipe", "mlipe", "send ", "tuma")):
            payee = next((pid for pid, name in self.payees.items()
                          if pid.lower() in t or name.lower() in t
                          or name.split()[0].lower() in t), None)
            if payee is None and "[phone]" in t:
                payee = "[PHONE]"
            return ToolCall("propose_payment", {"payee_id": payee or "unknown",
                                                "amount": amounts[0] if amounts else 0})
        if loan:
            months = re.search(r"(\d+)\s*(?:months?|miezi)", t)
            return ToolCall("compare_credit", {
                "amount": next((a for a in amounts if a >= 1000), 45_000),
                "term_days": int(months.group(1)) * 30 if months else 180})
        if any(w in t for w in ("short", "forecast", "two weeks", "run out", "upungufu",
                                "wiki mbili", "itatosha", "nitakosa")):
            return ToolCall("get_forecast", {})
        if any(w in t for w in ("transaction", "statement", "miamala", "taarifa", "instruction")):
            return ToolCall("get_ledger_summary", {"recent": 5})
        return ToolCall("get_business_health", {})

    # --- answer templates (numbers come only from the tool results) ---

    def describe_result(self, tool, result, lang="en"):
        """Plain-words version of one tool result (also used when an AI answer
        fails the number check)."""
        return self._answer(tool, result, lang)

    def _answer(self, tool, r, lang):
        sw = lang == "sw"
        if "error" in r:
            return (f"Samahani, hatua hii imeshindikana: {r['error']}" if sw
                    else f"Sorry, that step failed: {r['error']}")
        return getattr(self, f"_answer_{tool}")(r, sw)

    def _answer_get_business_health(self, r, sw):
        s, c = r["sales"], r["cash"]
        share = r["personal"]["share_of_profit"]
        if sw:
            return (f"Biashara yako ({r['period']['start']} hadi {r['period']['end']}): mauzo "
                    f"{kes(s['total'])}, wastani {kes(s['per_day'])} kwa siku. Faida ya pesa "
                    f"taslimu (mauzo ukiondoa gharama za biashara): {kes(r['profit'])}. Pesa za matumizi binafsi: "
                    f"{kes(r['personal']['total'])} ({share:.0%} ya faida). Hali halisi: "
                    f"{kes(c['true_position'])} (salio ukiondoa deni la overdraft "
                    f"{kes(c['overdraft_owed'])}). Siku dhaifu: {', '.join(s['slow_weekdays'])}.")
        return (f"Your business ({r['period']['start']} to {r['period']['end']}): sales "
                f"{kes(s['total'])}, {kes(s['per_day'])} a day on average. Cash profit "
                f"(sales minus business costs): {kes(r['profit'])}. Personal money taken out: "
                f"{kes(r['personal']['total'])} ({share:.0%} of profit). True position: "
                f"{kes(c['true_position'])} (balance minus {kes(c['overdraft_owed'])} overdraft "
                f"owed). Overdraft fees so far: {kes(r['credit']['overdraft_fees'])}. "
                f"Slow days: {', '.join(s['slow_weekdays'])}.")

    def _answer_get_forecast(self, r, sw):
        a = r["alert"]
        if a and sw:
            return (f"Tahadhari: hali yako halisi sasa ni {kes(r['true_position'])}. Katika siku "
                    f"14 zijazo makadirio ya chini yako chini ya akiba ya usalama "
                    f"{kes(r['safety_buffer'])} kwa siku {a['risky_days']}. Siku mbaya zaidi: "
                    f"{a['worst_date']} ({kes(a['worst_low'])}). Unaweza kuhitaji "
                    f"{kes(a['amount_needed'])} zaidi.")
        if a:
            return (f"Warning: your true position is {kes(r['true_position'])}. Over the next 14 "
                    f"days the low estimate is below your {kes(r['safety_buffer'])} safety buffer "
                    f"on {a['risky_days']} days. Worst day: {a['worst_date']} "
                    f"({kes(a['worst_low'])}). You may need {kes(a['amount_needed'])} more.")
        return ("Hakuna tatizo: makadirio ya chini yanabaki juu ya akiba yako ya usalama kwa siku "
                "zote 14." if sw else
                "No shortfall expected: the low estimate stays above your safety buffer for "
                "all 14 days.")

    def _answer_compare_credit(self, r, sw):
        lines = [f"{'Mkopo wa' if sw else 'A loan of'} {kes(r['amount'])} "
                 f"{'kwa siku' if sw else 'over'} {r['term_days']}{'' if sw else ' days'}:"]
        for o in r["options"]:
            fits = "yes" if o["fits_forecast_now"] else "no"
            if sw:
                fits = "ndiyo" if o["fits_forecast_now"] else "hapana"
            lines.append(f"  - {o['name']}: {'gharama' if sw else 'cost'} {kes(o['cost'])}, "
                         f"{'gharama ya mwaka' if sw else 'annual cost'} "
                         f"{o['effective_annual_cost_pct']}%, "
                         f"{'inafaa sasa' if sw else 'fits now'}: {fits}")
        best = min(r["options"], key=lambda o: o["cost"])
        cap = best["max_weekly_personal_money_for_fit"]
        if sw:
            lines.append(f"Nafuu zaidi: {best['name']}. Itafaa ukipunguza pesa za matumizi binafsi "
                         f"hadi {kes(cap)} kwa wiki (sasa {kes(r['weekly_personal_money_now'])})."
                         if cap is not None else f"Nafuu zaidi: {best['name']}.")
            lines.append("*Viwango vya SACCO na benki ni mifano tu, si bei halisi.")
        else:
            lines.append(f"Cheapest: {best['name']}. It fits if personal money is capped at "
                         f"{kes(cap)} a week (now {kes(r['weekly_personal_money_now'])})."
                         if cap is not None else f"Cheapest: {best['name']}.")
            lines.append("*SACCO and bank rates are illustrative, not real quotes.")
        return "\n".join(lines)

    def _answer_propose(self, r, sw):
        if r["status"] == "waiting_for_owner" and sw:
            a = r["action"]
            what = (f"kulipa {self.payees.get(a['payee_id'], a['payee_id'])} {kes(a['amount'])}"
                    if a["type"] == "pay_supplier" else
                    f"mkopo wa {a['product']} wa {kes(a['amount'])} kwa siku {a['term_days']}")
            return (f"Nimeandaa ombi {r['request_id']}: {what}. Bado HALIJAFANYIKA. "
                    f"Tafadhali liidhinishe kwenye programu kwa PIN yako.")
        if r["status"] == "waiting_for_owner":
            return (f"I've prepared request {r['request_id']}: {r['summary']}. It is NOT done "
                    f"yet. Please approve it in the app with your PIN.")
        return (f"Siwezi kuandaa ombi hili. Sababu: {r['reason']}" if sw else
                f"I can't prepare this request. Reason: {r['reason']}")

    _answer_propose_payment = _answer_propose
    _answer_propose_loan = _answer_propose

    def _answer_get_ledger_summary(self, r, sw):
        lines = [f"{'Miamala' if sw else 'Transactions'}: {r['transactions']} "
                 f"({r['period']['start']} - {r['period']['end']}). "
                 f"{'Ya karibuni' if sw else 'Most recent'}:"]
        for t in r["recent_transactions"]:
            amount = f"+{t['in']:,.0f}" if t["in"] else f"-{t['out']:,.0f}"
            lines.append(f"  {t['date']} {amount:>9}  {t['category']}  {t['description']}")
        n = len(r["suspicious_rows"])
        if n and sw:
            dates = ", ".join(s["date"] for s in r["suspicious_rows"])
            lines.append(f"ONYO: muamala {n} ({dates}) una maandishi yanayofanana na maagizo. "
                         f"Nimeyaficha na kuyachukulia kama data tu; sikuyafuata, na hakuna "
                         f"malipo yaliyopendekezwa.")
        elif n:
            dates = ", ".join(s["date"] for s in r["suspicious_rows"])
            lines.append(f"WARNING: {n} transaction(s) ({dates}) contain text that looks like "
                         f"instructions. I treat statement text as data only, so I did not follow "
                         f"it and no payment was proposed.")
        return "\n".join(lines)
