"""
app.py - Step 9: the Duka Copilot web app (Streamlit)
=======================================================

Tabs: Overview (health cards + SMS-style alert), Forecast (chart), Credit (table),
Chat (the agent), Approvals (the ONLY place the owner approves, with a PIN),
Audit log (is the hash chain intact?).

The numbers on screen come from the same Python modules the agent uses
(analytics, forecast, credit). The AI never approves anything.

HOW TO RUN (in the VS Code terminal, inside the duka-copilot folder)
    py -m streamlit run app.py
Then open the link it prints (usually http://localhost:8501).
"""

import json
import os
import tempfile
from collections import deque
from datetime import timedelta
from math import ceil

import altair as alt
import pandas as pd
import streamlit as st

from agent import BUSINESSES, has_api_key, looks_like_instructions, make_agent, make_provider, \
    rows_from_statement
from analytics import DATA, date_range, load_ledger, summarise, true_positions
from credit import compare_options, fits, personal_cap, weekly_personal
from forecast import SAFETY_BUFFER, build_model, forecast, shortfall_alert
from providers import OfflineProvider
from sandbox import AUDIT_PATH
from security import POLICIES, AuditLog, verify_log

# Chart colours (validated reference palette from the dataviz guidance)
BLUE, CRITICAL, MUTED = "#2a78d6", "#d03b3b", "#898781"

# ---------------------------------------------------------------------------
# Words on screen, in English and Swahili
# ---------------------------------------------------------------------------

TEXT = {
    "en": {
        "subtitle": "AI finance copilot for small businesses that run on mobile money",
        "language": "Language", "business": "Business",
        "upload": "Upload a statement (CSV)",
        "upload_help": "A mobile-money statement export. It is read as data only.",
        "using_upload": "Showing the uploaded statement",
        "offline_mode": "Offline demo mode",
        "offline_banner": "OFFLINE DEMO MODE: no AI service is connected, so a simple "
                          "rule-based helper answers instead of the AI. All safety checks, "
                          "approvals and the audit log work exactly the same.",
        "ai_banner": "Connected to the AI service",
        "suspicious": "{n} transaction(s) in this statement contain text that looks like "
                      "instructions. It is hidden from the AI and treated as data only.",
        "tabs": ["Overview", "Forecast", "Credit", "Chat", "Approvals", "Audit log"],
        "balance": "Mobile-money balance", "owed": "Overdraft owed",
        "position": "True position", "position_help": "Balance minus overdraft owed",
        "sales": "Sales", "per_day": "a day", "profit": "Cash profit",
        "profit_help": "Sales minus business costs", "personal": "Personal money",
        "of_profit": "of profit", "fees": "Overdraft fees", "slow": "Slow days",
        "sms_title": "SMS alert preview", "sms_chars": "characters",
        "fc_title": "True position: last 4 weeks and next 14 days",
        "fc_caption": "Shaded band: low to high estimate (about 8 in 10 days land inside). "
                      "Red dashed line: safety buffer. The forecast assumes no new borrowing.",
        "actual": "Actual", "expected": "Expected", "low": "Low", "high": "High",
        "date": "Date", "table_view": "Show as a table",
        "amount": "Loan amount (KES)", "term": "Term (days)",
        "cols": ["Option", "Total repaid", "Cost", "Effective annual cost",
                 "Fits forecast now?", "Fits if personal money is at most (a week)"],
        "yes": "yes", "no": "no", "never": "never",
        "illustrative": "* SACCO and bank rates are ILLUSTRATIVE, not real quotes.",
        "personal_now": "Personal money now: about {x} a week.",
        "headline": "Overdraft habit: about {habit} a year in fees. {best} would cost about "
                    "{cost} a year: a saving of about {save} a year.",
        "chat_hint": "Ask about sales, cash, loans or payments (English or Swahili)",
        "thinking": "Thinking...", "pending_note": "A request is waiting in the Approvals tab.",
        "none_waiting": "No requests are waiting for approval.",
        "approvals_note": "This is the only place where requests can be approved. "
                          "The AI can only create requests; it never sees your PIN.",
        "pin": "Owner PIN", "approve": "Approve", "reject": "Reject",
        "wrong_pin": "Not approved: wrong PIN, or approvals are locked.",
        "sandbox": "Sandbox account (simulated, no real money)",
        "sandbox_balance": "Sandbox balance",
        "owed_statement": "Overdraft owed (from statement)",
        "past": "Past decisions",
        "past_cols": ["Time", "Request", "What", "Owner decision", "Outcome", "Receipt", "Details"],
        "decisions": {"approved": "approved", "rejected": "rejected"},
        "waiting_ai": "Waiting for the AI service... ({s:.0f}s)",
        "go_offline": "Switch to offline demo mode",
        "chain_ok": "Audit log chain intact: {n} entries checked.",
        "chain_bad": "AUDIT LOG CHAIN BROKEN: {problem}",
        "head": "Latest hash (keep a copy elsewhere)", "recent": "Most recent entries",
    },
    "sw": {
        "subtitle": "Msaidizi wa fedha wa AI kwa biashara ndogo zinazotumia pesa za simu",
        "language": "Lugha", "business": "Biashara",
        "upload": "Pakia taarifa ya miamala (CSV)",
        "upload_help": "Taarifa ya pesa za simu. Inasomwa kama data tu.",
        "using_upload": "Inaonyesha taarifa uliyopakia",
        "offline_mode": "Hali ya maonyesho bila mtandao",
        "offline_banner": "HALI YA MAONYESHO BILA MTANDAO: hakuna huduma ya AI iliyounganishwa, "
                          "kwa hivyo msaidizi rahisi wa sheria anajibu badala ya AI. Ukaguzi wote "
                          "wa usalama, idhini na kumbukumbu za ukaguzi hufanya kazi vivyo hivyo.",
        "ai_banner": "Imeunganishwa na huduma ya AI",
        "suspicious": "Miamala {n} katika taarifa hii ina maandishi yanayofanana na maagizo. "
                      "Yamefichwa kwa AI na yanachukuliwa kama data tu.",
        "tabs": ["Muhtasari", "Utabiri", "Mikopo", "Mazungumzo", "Idhini",
                 "Kumbukumbu za ukaguzi"],
        "balance": "Salio la pesa za simu", "owed": "Deni la overdraft",
        "position": "Hali halisi", "position_help": "Salio ukiondoa deni la overdraft",
        "sales": "Mauzo", "per_day": "kwa siku", "profit": "Faida ya pesa taslimu",
        "profit_help": "Mauzo ukiondoa gharama za biashara", "personal": "Pesa za matumizi binafsi",
        "of_profit": "ya faida", "fees": "Ada za overdraft", "slow": "Siku dhaifu",
        "sms_title": "Mfano wa ujumbe wa SMS", "sms_chars": "herufi",
        "fc_title": "Hali halisi: wiki 4 zilizopita na siku 14 zijazo",
        "fc_caption": "Eneo lenye kivuli: makadirio ya chini hadi ya juu (karibu siku 8 kati ya "
                      "10 huwa ndani). Mstari mwekundu: akiba ya usalama. Utabiri unadhani "
                      "hakuna mkopo mpya.",
        "actual": "Halisi", "expected": "Inatarajiwa", "low": "Chini", "high": "Juu",
        "date": "Tarehe", "table_view": "Onyesha kama jedwali",
        "amount": "Kiasi cha mkopo (KES)", "term": "Muda (siku)",
        "cols": ["Chaguo", "Jumla ya kulipa", "Gharama", "Gharama ya mwaka",
                 "Inafaa utabiri sasa?", "Inafaa ukitumia pesa binafsi zisizozidi (kwa wiki)"],
        "yes": "ndiyo", "no": "hapana", "never": "haiwezekani",
        "illustrative": "* Viwango vya SACCO na benki ni MIFANO tu, si bei halisi.",
        "personal_now": "Pesa za matumizi binafsi sasa: karibu {x} kwa wiki.",
        "headline": "Tabia ya overdraft: karibu {habit} kwa mwaka kwa ada. {best} ingegharimu "
                    "karibu {cost} kwa mwaka: akiba ya karibu {save} kwa mwaka.",
        "chat_hint": "Uliza kuhusu mauzo, pesa, mikopo au malipo (Kiswahili au Kiingereza)",
        "thinking": "Inafikiri...", "pending_note": "Ombi linasubiri kwenye kichupo cha Idhini.",
        "none_waiting": "Hakuna maombi yanayosubiri idhini.",
        "approvals_note": "Hapa ndipo mahali pekee pa kuidhinisha maombi. AI inaweza tu "
                          "kuandaa maombi; haioni PIN yako kamwe.",
        "pin": "PIN ya mmiliki", "approve": "Idhinisha", "reject": "Kataa",
        "wrong_pin": "Haijaidhinishwa: PIN si sahihi, au idhini zimefungwa.",
        "sandbox": "Akaunti ya majaribio (si pesa halisi)",
        "sandbox_balance": "Salio la majaribio",
        "owed_statement": "Deni la overdraft (kutoka taarifa)",
        "past": "Maamuzi yaliyopita",
        "past_cols": ["Saa", "Ombi", "Nini", "Uamuzi wa mmiliki", "Matokeo", "Risiti", "Maelezo"],
        "decisions": {"approved": "imeidhinishwa", "rejected": "imekataliwa"},
        "waiting_ai": "Inasubiri huduma ya AI... (sekunde {s:.0f})",
        "go_offline": "Washa hali ya maonyesho bila mtandao",
        "chain_ok": "Mnyororo wa kumbukumbu uko salama: kumbukumbu {n} zimekaguliwa.",
        "chain_bad": "MNYORORO WA KUMBUKUMBU UMEVUNJIKA: {problem}",
        "head": "Hash ya mwisho (weka nakala mahali pengine)", "recent": "Kumbukumbu za karibuni",
    },
}


def kes(x):
    return f"KES {x:,.0f}"


# ---------------------------------------------------------------------------
# Data (cached: the maths runs once per business/statement)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_audit():
    return AuditLog(AUDIT_PATH)


@st.cache_data(show_spinner=False)
def load_rows(business, upload=None):
    if upload is None:
        return load_ledger(DATA / f"{business}_ledger.csv")
    with tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False) as f:
        f.write(upload)
    try:
        return rows_from_statement(f.name, business)
    finally:
        os.remove(f.name)


@st.cache_data(show_spinner=False)
def forecast_data(rows):
    last = rows[-1]["date"]
    position = true_positions(rows, [last])[last]
    days = forecast(build_model(rows), last, position)
    past_dates = date_range(max(rows[0]["date"], last - timedelta(days=27)), last)
    past = true_positions(rows, past_dates)
    return position, days, shortfall_alert(days), past


@st.cache_data(show_spinner=False)
def credit_data(rows, amount, term):
    last = rows[-1]["date"]
    position = true_positions(rows, [last])[last]
    model = build_model(rows)
    options = compare_options(amount, term)
    for o in options:
        o["fits_now"] = fits(model, o, last, position, amount)
        o["cap"] = personal_cap(model, o, last, position, amount)
    return options, weekly_personal(model)


# ---------------------------------------------------------------------------
# Page sections
# ---------------------------------------------------------------------------

def overview(t, lang, health, alert, position):
    cash, credit, sales = health["cash"], health["credit"], health["sales"]
    c1, c2, c3 = st.columns(3)
    c1.metric(t["balance"], kes(cash["closing_balance"]))
    c2.metric(t["owed"], kes(cash["overdraft_owed"]))
    c3.metric(t["position"], kes(cash["true_position"]), help=t["position_help"])
    c4, c5, c6, c7 = st.columns(4)
    c4.metric(t["sales"], kes(sales["total"]), f"{kes(sales['per_day'])} {t['per_day']}",
              delta_color="off")
    c5.metric(t["profit"], kes(health["profit"]), help=t["profit_help"])
    share = health["personal"]["share_of_profit"]
    c6.metric(t["personal"], kes(health["personal"]["total"]),
              f"{share:.0%} {t['of_profit']}" if share is not None else None, delta_color="off")
    c7.metric(t["fees"], kes(credit["overdraft_fees"]))
    st.caption(f"{health['period']['start']} - {health['period']['end']} · "
               f"{t['slow']}: {', '.join(sales['slow_weekdays']) or '-'}")

    st.subheader(t["sms_title"])
    sms = sms_text(lang, alert, position)
    st.markdown(
        f"<div style='max-width:340px;padding:12px 14px;border-radius:16px 16px 16px 4px;"
        f"border:1px solid rgba(128,128,128,.35);background:rgba(128,128,128,.10);"
        f"font-family:system-ui,sans-serif;font-size:15px;line-height:1.4'>{sms}</div>",
        unsafe_allow_html=True)
    st.caption(f"{len(sms)} {t['sms_chars']}")


def sms_text(lang, alert, position):
    head = verify_log(AUDIT_PATH)[3][:6]          # anchors the audit log, see security.py
    if alert and lang == "sw":
        msg = (f"Duka Copilot: Tahadhari ya pesa. Kufikia {alert['worst_date']:%d/%m} pesa "
               f"zinaweza kushuka hadi {kes(alert['worst_low'])}. Unaweza kuhitaji "
               f"{kes(alert['amount_needed'])}. Fungua programu.")
    elif alert:
        msg = (f"Duka Copilot: Low cash alert. By {alert['worst_date']:%a %d %b} your money "
               f"may fall to {kes(alert['worst_low'])}. You may need "
               f"{kes(alert['amount_needed'])}. Open the app for options.")
    elif lang == "sw":
        msg = f"Duka Copilot: Hakuna upungufu wa pesa siku 14 zijazo. Hali halisi {kes(position)}."
    else:
        msg = f"Duka Copilot: No cash shortfall expected in the next 14 days. True position {kes(position)}."
    return f"{msg} Ref {head}"


def forecast_chart(t, days, past):
    rows = [{"date": d, "value": v, "kind": t["actual"]} for d, v in past.items()]
    last_date, last_value = max(past.items())
    band = pd.DataFrame([{"date": last_date, "low": last_value, "high": last_value,
                          "expected": last_value}] +
                        [{"date": d["date"], "low": round(d["low"]), "high": round(d["high"]),
                          "expected": round(d["expected"])} for d in days])
    band["date"] = pd.to_datetime(band["date"])
    actual = pd.DataFrame(rows)
    actual["date"] = pd.to_datetime(actual["date"])

    x = alt.X("date:T", title=None, axis=alt.Axis(format="%d %b", grid=False))
    y_title = f"{t['position']} (KES)"
    tooltip = [alt.Tooltip("date:T", title=t["date"], format="%a %d %b"),
               alt.Tooltip("low:Q", title=t["low"], format=",.0f"),
               alt.Tooltip("expected:Q", title=t["expected"], format=",.0f"),
               alt.Tooltip("high:Q", title=t["high"], format=",.0f")]
    area = alt.Chart(band).mark_area(color=BLUE, opacity=0.18).encode(
        x=x, y=alt.Y("low:Q", title=y_title), y2="high:Q")
    expected = alt.Chart(band).mark_line(color=BLUE, strokeWidth=2, strokeDash=[6, 4]).encode(
        x=x, y="expected:Q")
    points = alt.Chart(band).mark_point(size=120, opacity=0).encode(x=x, y="expected:Q",
                                                                    tooltip=tooltip)
    past_line = alt.Chart(actual).mark_line(color=BLUE, strokeWidth=2).encode(
        x=x, y="value:Q",
        tooltip=[alt.Tooltip("date:T", title=t["date"], format="%a %d %b"),
                 alt.Tooltip("value:Q", title=t["actual"], format=",.0f")])
    buffer = alt.Chart(pd.DataFrame({"y": [SAFETY_BUFFER]})).mark_rule(
        color=CRITICAL, strokeDash=[4, 4], strokeWidth=1.5).encode(y="y:Q")
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=MUTED, strokeWidth=1).encode(y="y:Q")
    chart = (area + zero + buffer + past_line + expected + points).properties(
        height=340, width="container").configure_axis(labelColor=MUTED, titleColor=MUTED,
                                                      gridColor="#e1e0d9", gridOpacity=0.5)
    st.altair_chart(chart)
    st.caption(t["fc_caption"])
    if st.toggle(t["table_view"]):
        st.dataframe(pd.DataFrame({
            t["date"]: band["date"].dt.strftime("%a %d %b"),
            t["low"]: band["low"].map(kes),
            t["expected"]: band["expected"].map(kes),
            t["high"]: band["high"].map(kes)}), hide_index=True)


def credit_section(t, rows, health, alert):
    need = alert["amount_needed"] if alert else 20_000
    c1, c2 = st.columns(2)
    amount = c1.number_input(t["amount"], min_value=1_000, max_value=1_000_000, step=5_000,
                             value=int(min(1_000_000, max(5_000, ceil(need / 5_000) * 5_000))))
    term = c2.selectbox(t["term"], [30, 90, 180, 365], index=2)
    options, weekly_now = credit_data(rows, float(amount), int(term))
    table = pd.DataFrame([{
        t["cols"][0]: o["name"], t["cols"][1]: kes(o["total_repaid"]), t["cols"][2]: kes(o["cost"]),
        t["cols"][3]: f"{o['annual_cost']:.0%}", t["cols"][4]: t["yes"] if o["fits_now"] else t["no"],
        t["cols"][5]: kes(o["cap"]) if o["cap"] is not None else t["never"]} for o in options])
    st.dataframe(table, hide_index=True)
    st.caption(t["illustrative"] + " " + t["personal_now"].format(x=kes(weekly_now)))

    fitting = [o for o in options if o["cap"] is not None]
    fees = health["credit"]["overdraft_fees"]
    if fitting and fees > 0:
        best = min(fitting, key=lambda o: o["cost"])
        habit = fees * 365 / health["period"]["days"]
        cost = best["cost"] * 365 / term
        st.success(t["headline"].format(habit=kes(habit), best=best["name"], cost=kes(cost),
                                        save=kes(habit - cost)))


def go_offline():
    st.session_state["offline"] = True


def chat_section(t, lang, entry):
    agent = entry["agent"]
    for role, text in entry["messages"]:
        with st.chat_message(role):
            st.markdown(text)
    if agent.last_error:                        # the AI service failed last time
        st.button(t["go_offline"], on_click=go_offline, type="primary")
    question = st.chat_input(t["chat_hint"])
    if question:
        before = len(agent.sandbox.approvals.waiting())
        with st.chat_message("user"):
            st.markdown(question)
        waiting = st.empty()
        agent.provider.on_wait = lambda s: waiting.info(t["waiting_ai"].format(s=s), icon="⏳")
        with st.spinner(t["thinking"]):
            answer = agent.ask(question, lang=lang)
        waiting.empty()
        if len(agent.sandbox.approvals.waiting()) > before:
            answer += f"\n\n*{t['pending_note']}*"
        entry["messages"] += [("user", question), ("assistant", answer)]
        st.rerun()


def describe(action, payees):
    if action["type"] == "pay_supplier":
        return f"Pay **{payees.get(action['payee_id'], action['payee_id'])}** {kes(action['amount'])}"
    return (f"**{action['product']}** loan of {kes(action['amount'])} "
            f"over {action['term_days']} days")


def approvals_section(t, entry, health):
    """THE ONLY PLACE APPROVALS HAPPEN. The owner types the PIN here."""
    sandbox = entry["agent"].sandbox
    payees = sandbox.guard.policy.verified_payees
    st.info(t["approvals_note"])
    for msg in entry["results"]:
        st.write(msg)
    waiting = sandbox.approvals.waiting()
    if not waiting:
        st.write(t["none_waiting"])
    for rid, action in waiting.items():
        with st.form(f"approve_{rid}", border=True):
            st.markdown(f"`{rid}` · {describe(action, payees)}")
            pin = st.text_input(t["pin"], type="password", key=f"pin_{rid}")
            c1, c2 = st.columns(2)
            approve = c1.form_submit_button(t["approve"], type="primary")
            reject = c2.form_submit_button(t["reject"])
        if approve:
            code = sandbox.owner_approve(rid, pin)
            result = sandbox.execute(rid, code) if code else {"status": "blocked",
                                                              "reason": t["wrong_pin"]}
            entry["results"].append(f"{rid}: **{result['status']}** · "
                                    f"{result.get('reason') or json.dumps(result)}")
            st.rerun()
        if reject:
            sandbox.owner_decline(rid)
            entry["results"].append(f"{rid}: **declined**")
            st.rerun()

    st.subheader(t["sandbox"])
    c1, c2 = st.columns(2)
    c1.metric(t["sandbox_balance"], kes(sandbox.account.balance))
    c2.metric(t["owed_statement"], kes(health["cash"]["overdraft_owed"]))

    if sandbox.decisions:
        st.subheader(t["past"])
        cols = t["past_cols"]
        st.dataframe(pd.DataFrame([{
            cols[0]: d["time"].strftime("%H:%M:%S"), cols[1]: d["request_id"],
            cols[2]: describe(d["action"], payees).replace("**", ""),
            cols[3]: t["decisions"][d["decision"]], cols[4]: d["outcome"],
            cols[5]: d["receipt"] or "-", cols[6]: d["detail"]}
            for d in reversed(sandbox.decisions)]), hide_index=True)


def audit_section(t):
    ok, count, problem, head = verify_log(AUDIT_PATH)
    if ok:
        st.success(t["chain_ok"].format(n=count))
    else:
        st.error(t["chain_bad"].format(problem=problem))
    st.caption(f"{t['head']}: `{head}`")
    st.subheader(t["recent"])
    if AUDIT_PATH.exists():
        with open(AUDIT_PATH, encoding="utf-8") as f:
            last = [json.loads(line) for line in deque(f, maxlen=30)]
        st.dataframe(pd.DataFrame([{
            "#": e["seq"], "time": e["time"][11:], "actor": e["actor"], "event": e["event"],
            "details": json.dumps(e["details"])[:120], "hash": e["hash"][:10]}
            for e in reversed(last)]), hide_index=True)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Duka Copilot", page_icon="💬", layout="wide")

    with st.sidebar:
        lang = "sw" if st.radio("Language / Lugha", ["English", "Kiswahili"],
                                horizontal=True) == "Kiswahili" else "en"
        t = TEXT[lang]
        business = st.selectbox(t["business"], list(BUSINESSES), index=0,   # Amina first
                                format_func=lambda b: BUSINESSES[b]["label"])
        upload = st.file_uploader(t["upload"], type=["csv"], help=t["upload_help"])
        key_ok = has_api_key()
        st.session_state.setdefault("offline", not key_ok)
        offline = st.toggle(t["offline_mode"], key="offline", disabled=not key_ok)

    st.title("Duka Copilot")
    st.caption(t["subtitle"])

    upload_bytes = upload.getvalue() if upload else None
    try:
        rows = load_rows(business, upload_bytes)
    except Exception as e:
        st.error(f"Could not read this statement: {type(e).__name__}. "
                 f"Please upload a mobile-money statement CSV.")
        return

    # One agent (with its own chat, sandbox and approvals) per business + statement
    agent_key = (business, hash(upload_bytes), offline)
    agents = st.session_state.setdefault("agents", {})
    if agent_key not in agents:
        provider = make_provider(offline, business)
        agents[agent_key] = {"agent": make_agent(provider, get_audit(), business, rows=rows),
                             "messages": [], "results": []}
    entry = agents[agent_key]

    if isinstance(entry["agent"].provider, OfflineProvider):
        st.warning(t["offline_banner"], icon="⚠️")
    else:
        st.caption(f"✅ {t['ai_banner']}: {entry['agent'].provider.name}")
    if upload:
        st.caption(f"📄 {t['using_upload']}: {upload.name}")
        suspicious = sum(looks_like_instructions(r["Description"]) for r in rows)
        if suspicious:
            st.error(t["suspicious"].format(n=suspicious), icon="🛡️")

    health = summarise(rows)
    position, days, alert, past = forecast_data(rows)
    waiting = len(entry["agent"].sandbox.approvals.waiting())
    if waiting:
        st.sidebar.warning(f"{t['tabs'][4]}: {waiting}", icon="🔔")
    tabs = st.tabs(t["tabs"])
    with tabs[0]:
        overview(t, lang, health, alert, position)
    with tabs[1]:
        st.subheader(t["fc_title"])
        forecast_chart(t, days, past)
    with tabs[2]:
        credit_section(t, rows, health, alert)
    with tabs[3]:
        chat_section(t, lang, entry)
    with tabs[4]:
        approvals_section(t, entry, health)
    with tabs[5]:
        audit_section(t)


main()
