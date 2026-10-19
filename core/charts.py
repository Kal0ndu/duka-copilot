"""Reusable Altair charts for business metrics, forecasting, and risk analysis.

Colour rules (validated with the dataviz palette checker against the app's
dark surface #0F172A; every slot passes lightness, chroma, colour-blind and
normal-vision separation and 3:1 contrast):

* SERIES is the categorical palette, used in fixed order and never cycled.
* An entity keeps its colour on every page: money in = slot 1 (blue),
  money out = slot 2 (orange), net = slot 3 (green).
* STATUS colours mean good / warning / danger only (safety buffer, risk
  lines, over budget) and always come with a label.
* Every chart with two or more series has a legend; text uses text colours,
  never a series colour. Charts take real data from the caller only.
"""
from typing import Dict, List, Optional

import altair as alt
import pandas as pd

SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
MONEY_IN, MONEY_OUT, NET = SERIES[0], SERIES[1], SERIES[2]
GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"
TEXT, TEXT_MUTED = "#CBD5E1", "#94A3B8"
NEUTRAL = "#64748b"  # de-emphasised marks next to a status colour (validated against CRITICAL)
# Ordinal ramp (validated --ordinal): older / worse = stronger orange
ORDINAL_ORANGE = ["#f4b183", "#ec835a", "#d95926", "#a8401a"]

# Kept for callers that imported the old names
PRIMARY_GREEN, SECONDARY_BLUE, ACCENT_CORAL, AMBER_WARNING, MUTED_GRAY = NET, MONEY_IN, CRITICAL, WARNING, TEXT_MUTED

LEGEND_TOP = alt.Legend(title=None, orient="top", direction="horizontal", labelColor=TEXT, symbolStrokeWidth=2)
KES = ",.0f"
DATE_AXIS = alt.Axis(format="%d %b", labelColor=TEXT_MUTED, labelOverlap="greedy", labelSeparation=8, tickCount=8)


def _empty(message: str) -> alt.Chart:
    return alt.Chart(pd.DataFrame({"msg": [message]})).mark_text(color=TEXT_MUTED, fontSize=13).encode(text="msg:N")


def _hover_rule(df: pd.DataFrame, x: str, tooltip: list, x_type: str = "T") -> alt.LayerChart:
    """Vertical crosshair that snaps to the nearest x and shows a tooltip."""
    hover = alt.selection_point(fields=[x], nearest=True, on="pointerover", empty=False, clear="pointerout")
    x_enc = alt.X(f"{x}:{x_type}", sort=df[x].tolist()) if x_type == "O" else f"{x}:{x_type}"
    return alt.layer(
        alt.Chart(df).mark_rule(color=TEXT_MUTED, strokeWidth=1).encode(
            x=x_enc,
            opacity=alt.condition(hover, alt.value(0.6), alt.value(0)),
            tooltip=tooltip,
        ).add_params(hover),
    )


# ---------------------------------------------------------------------------
# Cash flow
# ---------------------------------------------------------------------------

def chart_cashflow_trend(daily_df: pd.DataFrame) -> alt.Chart:
    """Money in above zero, money out below zero, and the net per period.

    More than ~2 months of days is grouped by week so bars stay readable.
    Expects columns date, inflow, outflow (KES)."""
    if daily_df.empty:
        return _empty("No transactions yet")
    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    span = (df["date"].max() - df["date"].min()).days
    weekly = span > 62
    if weekly:
        df = (df.set_index("date")[["inflow", "outflow"]].resample("W-MON", label="left", closed="left")
                .sum().reset_index())
    df["net"] = df["inflow"] - df["outflow"]
    period = "Week of" if weekly else "Date"
    # A band axis gives every bar a real width (a time axis draws hairlines).
    df["Period"] = df["date"].dt.strftime("%d %b %y" if span > 300 else "%d %b")
    order = df["Period"].tolist()

    long = pd.concat([
        pd.DataFrame({"Period": df["Period"], "Series": "Money in", "KES": df["inflow"]}),
        pd.DataFrame({"Period": df["Period"], "Series": "Money out", "KES": -df["outflow"]}),
    ])
    color = alt.Color("Series:N", scale=alt.Scale(domain=["Money in", "Money out", "Net"],
                                                  range=[MONEY_IN, MONEY_OUT, NET]), legend=LEGEND_TOP)
    x = alt.X("Period:O", sort=order, title=None,
              axis=alt.Axis(labelAngle=0, labelColor=TEXT_MUTED, labelOverlap="greedy"),
              scale=alt.Scale(paddingInner=0.25))
    bars = alt.Chart(long).mark_bar(cornerRadiusEnd=3).encode(
        x=x, y=alt.Y("KES:Q", title="KES (money out shown below zero)", axis=alt.Axis(format="~s")), color=color)
    net = alt.Chart(df.assign(Series="Net")).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
        x=alt.X("Period:O", sort=order), y="net:Q", color=color)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=TEXT_MUTED, strokeWidth=1).encode(y="y:Q")
    tip = _hover_rule(df, "Period", x_type="O", tooltip=[
        alt.Tooltip("date:T", title=period, format="%a %d %b %Y"),
        alt.Tooltip("inflow:Q", title="Money in (KES)", format=KES),
        alt.Tooltip("outflow:Q", title="Money out (KES)", format=KES),
        alt.Tooltip("net:Q", title="Net (KES)", format=KES),
    ])
    return alt.layer(bars, zero, net, tip).properties(height=340)


def chart_forecast_confidence(points: List[Dict], buffer_kes: float = 5000.0,
                              bills: Optional[List[Dict]] = None) -> alt.Chart:
    """Monte Carlo fan chart with a legend that says what each part means:
    the likely range (8 in 10 simulated futures land inside), the expected
    balance, the bad-week balance, the safety buffer, risky days (bad-week
    balance under the buffer) and bills due (from `bills`: due_date,
    amount_minor, label)."""
    if not points:
        return _empty("No forecast available")
    df = pd.DataFrame([{
        "date": pd.Timestamp(p["date"][:10]),
        "p10": p["p10"] / 100.0, "p50": p["p50"] / 100.0, "p90": p["p90"] / 100.0,
        "buffer": buffer_kes,
    } for p in points])

    names = ["Likely range (8 in 10 outcomes)", "Expected balance", "Bad-week balance", "Safety buffer",
             "Risky day", "Bill due"]
    # Validated as a set (all pairs): blue, yellow, red; bills are a neutral light marker.
    color = alt.Color("Series:N", scale=alt.Scale(domain=names, range=[MONEY_IN, MONEY_IN, SERIES[3], CRITICAL,
                                                                       CRITICAL, TEXT]),
                      legend=alt.Legend(title=None, orient="top", direction="horizontal", columns=3,
                                        labelColor=TEXT, symbolStrokeWidth=2, labelLimit=260,
                                        symbolOpacity=1))
    x = alt.X("date:T", title=None, axis=DATE_AXIS)
    y_title = "Balance (KES)"

    band = alt.Chart(df.assign(Series=names[0])).mark_area(opacity=0.22).encode(
        x=x, y=alt.Y("p10:Q", title=y_title, axis=alt.Axis(format="~s")), y2="p90:Q", color=color)
    expected = alt.Chart(df.assign(Series=names[1])).mark_line(strokeWidth=2.5).encode(x="date:T", y="p50:Q",
                                                                                         color=color)
    bad_week = alt.Chart(df.assign(Series=names[2])).mark_line(strokeWidth=1.5).encode(x="date:T", y="p10:Q",
                                                                                         color=color)
    buffer = alt.Chart(df.assign(Series=names[3])).mark_line(strokeWidth=1.5, strokeDash=[6, 4]).encode(
        x="date:T", y="buffer:Q", color=color)
    risky = df[df["p10"] < buffer_kes].assign(Series=names[4])
    layers = [band, buffer, bad_week, expected]
    if not risky.empty:
        layers.append(alt.Chart(risky).mark_point(filled=True, size=55, shape="diamond").encode(
            x="date:T", y="p10:Q", color=color))
    if bills:
        b = pd.DataFrame([{"date": pd.Timestamp(str(o["due_date"])[:10]), "amount": o["amount_minor"] / 100.0,
                           "label": o.get("label") or "Bill"} for o in bills])
        b = b[(b["date"] >= df["date"].min()) & (b["date"] <= df["date"].max())]
        if not b.empty:
            b = (b.groupby("date").agg(amount=("amount", "sum"), label=("label", lambda s: ", ".join(s)))
                  .reset_index().merge(df[["date", "p50"]], on="date", how="left").assign(Series=names[5]))
            layers.append(alt.Chart(b).mark_point(filled=True, size=90, shape="triangle-down").encode(
                x="date:T", y="p50:Q", color=color,
                tooltip=[alt.Tooltip("date:T", title="Due", format="%a %d %b"),
                         alt.Tooltip("label:N", title="Bill(s)"),
                         alt.Tooltip("amount:Q", title="Amount (KES)", format=KES)]))
    # Direct labels: the end of the expected line, and the buffer
    last = df.iloc[[-1]]
    layers.append(alt.Chart(last).mark_text(align="left", dx=6, color=TEXT, fontSize=11).encode(
        x="date:T", y="p50:Q", text=alt.Text("p50:Q", format=",.0f")))
    layers.append(alt.Chart(df.iloc[[0]]).mark_text(align="left", dy=-7, color=TEXT_MUTED, fontSize=11).encode(
        x="date:T", y="buffer:Q", text=alt.value(f"Safety buffer KES {buffer_kes:,.0f}")))
    layers.append(_hover_rule(df, "date", [
        alt.Tooltip("date:T", title="Date", format="%a %d %b %Y"),
        alt.Tooltip("p50:Q", title="Expected (KES)", format=KES),
        alt.Tooltip("p10:Q", title="Bad week, P10 (KES)", format=KES),
        alt.Tooltip("p90:Q", title="Good week, P90 (KES)", format=KES),
        alt.Tooltip("buffer:Q", title="Safety buffer (KES)", format=KES),
    ]))
    return alt.layer(*layers).properties(height=380)


def chart_monthly_pnl(records: List[Dict]) -> alt.Chart:
    """Per month: sales income, cost of sales, running costs and personal
    drawings (grouped bars, one axis). Expects ledger records with
    local_date, amount_minor, direction, category_kind."""
    if not records:
        return _empty("No transactions yet")
    df = pd.DataFrame(records)
    if "category_kind" not in df.columns:
        return _empty("Categories needed for this chart")
    df["month"] = pd.to_datetime(df["local_date"].astype(str).str.slice(0, 7) + "-01", errors="coerce")
    kind_to_series = {("income", "in"): "Sales income", ("cogs", "out"): "Cost of sales",
                      ("opex", "out"): "Running costs", ("tax", "out"): "Running costs",
                      ("personal", "out"): "Personal drawings"}
    df["Series"] = [kind_to_series.get((k, d)) for k, d in zip(df["category_kind"], df["direction"])]
    df = df.dropna(subset=["Series", "month"])
    if df.empty:
        return _empty("No categorised income or costs yet")
    m = df.groupby(["month", "Series"], as_index=False)["amount_minor"].sum()
    m["KES"] = m["amount_minor"] / 100
    order = ["Sales income", "Cost of sales", "Running costs", "Personal drawings"]
    return alt.Chart(m).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("yearmonth(month):O", title=None, axis=alt.Axis(format="%b %Y", labelAngle=0, labelColor=TEXT_MUTED)),
        xOffset=alt.XOffset("Series:N", sort=order, scale=alt.Scale(paddingInner=0.06)),
        y=alt.Y("KES:Q", title="KES", axis=alt.Axis(format="~s")),
        color=alt.Color("Series:N", sort=order, scale=alt.Scale(domain=order, range=SERIES[:4]), legend=LEGEND_TOP),
        tooltip=[alt.Tooltip("yearmonth(month):O", title="Month", format="%B %Y"), alt.Tooltip("Series:N", title="What"),
                 alt.Tooltip("KES:Q", title="KES", format=KES)],
    ).properties(height=320)


def chart_category_breakdown(cat_dict: Dict[str, float], title: str = "Spending by category",
                             color: str = MONEY_OUT) -> alt.Chart:
    """Horizontal bars of spending (or income) by category, with each bar's share."""
    if not cat_dict:
        return _empty("No category data")
    total = sum(cat_dict.values())
    df = pd.DataFrame([{"Category": k, "KES": v, "Share": (v / total) if total else 0} for k, v in cat_dict.items()])
    # Largest first; a catch-all "other" row always goes last.
    order = sorted(df["Category"], key=lambda c: (str(c).lower().startswith(("all other", "other")),
                                                  -float(df.loc[df["Category"] == c, "KES"].iloc[0])))
    base = alt.Chart(df).encode(y=alt.Y("Category:N", sort=order, title=None, axis=alt.Axis(labelLimit=180)))
    bars = base.mark_bar(cornerRadiusEnd=4, color=color).encode(
        x=alt.X("KES:Q", title="KES", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("Category:N"), alt.Tooltip("KES:Q", title="KES", format=KES),
                 alt.Tooltip("Share:Q", format=".1%")])
    labels = base.mark_text(align="left", dx=4, color=TEXT, fontSize=11).encode(
        x="KES:Q", text=alt.Text("Share:Q", format=".0%"))
    return (bars + labels).properties(height=max(200, len(df) * 30))


def chart_weekday_seasonality(weekday_df: pd.DataFrame) -> alt.Chart:
    """Average money in and money out on each day of the week."""
    if weekday_df.empty:
        return _empty("Not enough history")
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    long = pd.concat([
        weekday_df[["day_name", "avg_txns"]].assign(Series="Money in", KES=weekday_df["avg_inflow"]),
        weekday_df[["day_name", "avg_txns"]].assign(Series="Money out", KES=weekday_df["avg_outflow"]),
    ])
    return alt.Chart(long).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("day_name:N", sort=days, title=None, axis=alt.Axis(labelExpr="slice(datum.label, 0, 3)",
                                                                   labelAngle=0, labelColor=TEXT_MUTED)),
        xOffset=alt.XOffset("Series:N", scale=alt.Scale(paddingInner=0.06)),
        y=alt.Y("KES:Q", title="Average per day (KES)", axis=alt.Axis(format="~s")),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["Money in", "Money out"], range=[MONEY_IN, MONEY_OUT]),
                        legend=LEGEND_TOP),
        tooltip=[alt.Tooltip("day_name:N", title="Day"), alt.Tooltip("Series:N", title="What"),
                 alt.Tooltip("KES:Q", title="Average (KES)", format=KES),
                 alt.Tooltip("avg_txns:Q", title="Average transactions", format=".1f")],
    ).properties(height=280)


# ---------------------------------------------------------------------------
# Customers and suppliers
# ---------------------------------------------------------------------------

def _party_rows(parties: List) -> pd.DataFrame:
    return pd.DataFrame([{
        "Name": p.party_name, "In": p.inflow_kes, "Out": p.outflow_kes, "Share": p.concentration_pct / 100,
        "Orders": p.transaction_count, "Days since": p.days_since_interaction, "Segment": p.segment,
        "Churn risk": p.churn_risk_score, "Risk": p.is_concentration_risk,
    } for p in parties])


def chart_customer_concentration(customers: List, limit: int = 10) -> alt.Chart:
    """Top customers by share of revenue, with the 20% concentration line."""
    if not customers:
        return _empty("No customer data")
    df = _party_rows(customers[:limit])
    df["Status"] = ["Over 20% of revenue" if s >= 0.20 else "Under 20%" for s in df["Share"]]
    top = max(0.25, float(df["Share"].max()) + 0.05)
    order = df.sort_values("Share", ascending=False)["Name"].tolist()
    base = alt.Chart(df).encode(y=alt.Y("Name:N", sort=order, title=None, axis=alt.Axis(labelLimit=200)))
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("Share:Q", title="Share of revenue", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, top])),
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Under 20%", "Over 20% of revenue"],
                                                    range=[MONEY_IN, CRITICAL]), legend=LEGEND_TOP),
        tooltip=[alt.Tooltip("Name:N", title="Customer"), alt.Tooltip("In:Q", title="Paid you (KES)", format=KES),
                 alt.Tooltip("Share:Q", title="Share", format=".1%"), alt.Tooltip("Orders:Q")])
    labels = base.mark_text(align="left", dx=4, color=TEXT, fontSize=11).encode(
        x="Share:Q", text=alt.Text("Share:Q", format=".1%"))
    rule_df = pd.DataFrame({"x": [0.20], "label": ["20% risk line"]})
    rule = alt.Chart(rule_df).mark_rule(color=CRITICAL, strokeDash=[4, 4], strokeWidth=1.5).encode(x="x:Q")
    # Label at the foot of the line: the largest bar sits at the top.
    rule_label = alt.Chart(rule_df).mark_text(color=TEXT_MUTED, align="left", dx=4, baseline="bottom", y="height",
                                              dy=-3, fontSize=11).encode(x="x:Q", text="label:N")
    return (bars + labels + rule + rule_label).properties(height=max(220, len(df) * 30))


def chart_revenue_pareto(customers: List, limit: int = 25) -> alt.Chart:
    """How concentrated revenue is: each customer's share (bars) and the
    running total (line), largest first, with where 80% is reached."""
    if not customers:
        return _empty("No customer data")
    df = _party_rows(customers).sort_values("In", ascending=False).reset_index(drop=True)
    total = df["In"].sum() or 1
    df["Rank"] = df.index + 1
    df["Each"] = df["In"] / total
    df["Running total"] = df["In"].cumsum() / total
    reach = int((df["Running total"] >= 0.8).idxmax()) + 1 if (df["Running total"] >= 0.8).any() else len(df)
    show = df.head(max(limit, min(reach, 60)))
    x = alt.X("Rank:O", title="Customers, largest first", axis=alt.Axis(labelAngle=0, labelColor=TEXT_MUTED,
                                                                        values=list(range(1, len(show) + 1, 2))))
    color = alt.Color("Series:N", scale=alt.Scale(domain=["Customer's share", "Running total"],
                                                  range=[MONEY_IN, NET]), legend=LEGEND_TOP)
    tips = [alt.Tooltip("Rank:O", title="Rank"), alt.Tooltip("Name:N", title="Customer"),
            alt.Tooltip("In:Q", title="Paid you (KES)", format=KES), alt.Tooltip("Each:Q", title="Share", format=".1%"),
            alt.Tooltip("Running total:Q", title="Running total", format=".1%")]
    bars = alt.Chart(show.assign(Series="Customer's share")).mark_bar(cornerRadiusEnd=2).encode(
        x=x, y=alt.Y("Each:Q", title="Share of revenue", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
        color=color, tooltip=tips)
    line = alt.Chart(show.assign(Series="Running total")).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=20)).encode(
        x="Rank:O", y="Running total:Q", color=color, tooltip=tips)
    eighty = alt.Chart(pd.DataFrame({"y": [0.8], "t": [f"80% of revenue: top {reach} of {len(df)} customers"]}))
    rule = eighty.mark_rule(color=TEXT_MUTED, strokeDash=[4, 4]).encode(y="y:Q")
    rule_text = eighty.mark_text(align="right", dy=-6, color=TEXT, fontSize=11, x="width").encode(y="y:Q", text="t:N")
    return (bars + line + rule + rule_text).properties(height=300)


SEGMENTS = ["High Value", "Growth", "At Risk", "Dormant"]


def chart_segments(customers: List, measure: str = "count") -> alt.Chart:
    """Customers per segment ('count') or revenue per segment ('revenue')."""
    if not customers:
        return _empty("No customer data")
    df = _party_rows(customers)
    agg = df.groupby("Segment").agg(Customers=("Name", "count"), Revenue=("In", "sum")).reindex(SEGMENTS).fillna(0)
    agg = agg.reset_index()
    field, title, fmt = ("Customers", "Customers", ",.0f") if measure == "count" else ("Revenue", "Revenue (KES)", KES)
    base = alt.Chart(agg).encode(x=alt.X("Segment:N", sort=SEGMENTS, title=None,
                                         axis=alt.Axis(labelAngle=0, labelColor=TEXT_MUTED)))
    bars = base.mark_bar(cornerRadiusEnd=4, color=MONEY_IN).encode(
        y=alt.Y(f"{field}:Q", title=title, axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("Segment:N"), alt.Tooltip("Customers:Q", format=",.0f"),
                 alt.Tooltip("Revenue:Q", title="Revenue (KES)", format=KES)])
    labels = base.mark_text(dy=-6, color=TEXT, fontSize=11).encode(y=f"{field}:Q", text=alt.Text(f"{field}:Q", format=fmt))
    return (bars + labels).properties(height=260)


RECENCY_BANDS = ["0–14 days", "15–30 days", "31–60 days", "Over 60 days"]


def chart_recency(customers: List) -> alt.Chart:
    """How long since each customer last paid: the churn early-warning view."""
    if not customers:
        return _empty("No customer data")
    df = _party_rows(customers)
    df["Band"] = pd.cut(df["Days since"], bins=[-1, 14, 30, 60, 10**6], labels=RECENCY_BANDS)
    agg = (df.groupby("Band", observed=False).agg(Customers=("Name", "count"), Revenue=("In", "sum"))
             .reindex(RECENCY_BANDS).fillna(0).reset_index())
    base = alt.Chart(agg).encode(x=alt.X("Band:N", sort=RECENCY_BANDS, title="Since their last payment",
                                         axis=alt.Axis(labelAngle=0, labelColor=TEXT_MUTED)))
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y("Customers:Q", title="Customers"),
        color=alt.Color("Band:N", sort=RECENCY_BANDS, scale=alt.Scale(domain=RECENCY_BANDS, range=ORDINAL_ORANGE),
                        legend=None),
        tooltip=[alt.Tooltip("Band:N", title="Last paid"), alt.Tooltip("Customers:Q", format=",.0f"),
                 alt.Tooltip("Revenue:Q", title="Their revenue to date (KES)", format=KES)])
    labels = base.mark_text(dy=-6, color=TEXT, fontSize=11).encode(y="Customers:Q", text="Customers:Q")
    return (bars + labels).properties(height=260)


def chart_supplier_spend(suppliers: List, limit: int = 10) -> alt.Chart:
    """Top suppliers by spend, with each one's share of all supplier spend."""
    if not suppliers:
        return _empty("No supplier data")
    df = _party_rows(suppliers)
    total = df["Out"].sum() or 1
    top = df.sort_values("Out", ascending=False).head(limit)
    return chart_category_breakdown({r.Name: r.Out for r in top.itertuples()} | (
        {"All other suppliers": total - top["Out"].sum()} if len(df) > limit else {}), color=MONEY_OUT)


# ---------------------------------------------------------------------------
# Credit, financing, budgets
# ---------------------------------------------------------------------------

def chart_aging_buckets(buckets: Dict[str, float], title: str = "Aging buckets") -> alt.Chart:
    """Amounts owed by age; older buckets are a stronger orange."""
    df = pd.DataFrame([{"Bucket": k, "KES": v} for k, v in buckets.items()])
    if df.empty:
        return _empty("Nothing outstanding")
    order = list(buckets.keys())
    ramp = ORDINAL_ORANGE[:len(order)] if len(order) <= 4 else (ORDINAL_ORANGE * 2)[:len(order)]
    base = alt.Chart(df).encode(x=alt.X("Bucket:N", sort=order, title=None,
                                        axis=alt.Axis(labelAngle=0, labelColor=TEXT_MUTED)))
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y("KES:Q", title="Outstanding (KES)", axis=alt.Axis(format="~s")),
        color=alt.Color("Bucket:N", sort=order, scale=alt.Scale(domain=order, range=ramp), legend=None),
        tooltip=[alt.Tooltip("Bucket:N", title="Age"), alt.Tooltip("KES:Q", format=KES)])
    labels = base.mark_text(dy=-6, color=TEXT, fontSize=11).encode(y="KES:Q", text=alt.Text("KES:Q", format=",.0f"))
    return (bars + labels).properties(height=260)


def chart_loan_comparison(offers: List) -> alt.Chart:
    """What you receive vs what you repay, per loan product (one axis)."""
    if not offers:
        return _empty("No loan offers")
    rows = []
    for o in offers:
        label = f"{getattr(o, 'lender', 'Lender')} · {getattr(o, 'product', 'Product')}"
        rows.append({"Product": label, "Series": "You receive", "KES": getattr(o, "disbursed_minor", 0) / 100.0})
        rows.append({"Product": label, "Series": "You repay", "KES": getattr(o, "total_repayable_minor", 0) / 100.0})
    df = pd.DataFrame(rows)
    return alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("Product:N", title=None, axis=alt.Axis(labelLimit=240)),
        yOffset=alt.YOffset("Series:N", sort=["You receive", "You repay"], scale=alt.Scale(paddingInner=0.06)),
        x=alt.X("KES:Q", title="KES", axis=alt.Axis(format="~s")),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["You receive", "You repay"], range=[MONEY_IN, MONEY_OUT]),
                        legend=LEGEND_TOP),
        tooltip=[alt.Tooltip("Product:N"), alt.Tooltip("Series:N", title="What"), alt.Tooltip("KES:Q", format=KES)],
    ).properties(height=max(220, len(offers) * 52))


def chart_budget_vs_actual(rows: List[Dict]) -> alt.Chart:
    """Spent this month per category against its budget (tick). rows:
    Category, Budget, Actual (KES), Status (OK / Near limit / Over budget)."""
    if not rows:
        return _empty("No budgets set")
    df = pd.DataFrame(rows)
    df["Used"] = df["Actual"] / df["Budget"].where(df["Budget"] > 0)
    statuses = ["OK", "Near limit", "Over budget"]
    order = df.sort_values("Used", ascending=False)["Category"].tolist()
    base = alt.Chart(df).encode(y=alt.Y("Category:N", title=None, sort=order, axis=alt.Axis(labelLimit=200)))
    tips = [alt.Tooltip("Category:N"), alt.Tooltip("Actual:Q", title="Spent (KES)", format=KES),
            alt.Tooltip("Budget:Q", title="Budget (KES)", format=KES), alt.Tooltip("Used:Q", title="Used", format=".0%"),
            alt.Tooltip("Status:N")]
    bars = base.mark_bar(cornerRadiusEnd=3, height=14).encode(
        x=alt.X("Actual:Q", title="KES this month", axis=alt.Axis(format="~s")),
        color=alt.Color("Status:N", scale=alt.Scale(domain=statuses, range=[GOOD, WARNING, CRITICAL]),
                        legend=alt.Legend(title=None, orient="top", direction="horizontal", labelColor=TEXT)),
        tooltip=tips)
    budget = base.mark_tick(color=TEXT, thickness=2, size=24).encode(x="Budget:Q", tooltip=tips)
    # Status in words as well as colour (green and red are hard to tell apart for some readers)
    labels = base.mark_text(align="left", dx=6, color=TEXT, fontSize=11).encode(
        x=alt.X("max_x:Q"), text="label:N").transform_calculate(
        max_x="max(datum.Actual, datum.Budget)",
        label="format(datum.Used, '.0%') + (datum.Status == 'OK' ? '' : ' · ' + lower(datum.Status))")
    return (bars + budget + labels).properties(height=max(200, len(df) * 34))


def chart_allocation(allocations: List[Dict]) -> alt.Chart:
    """Suggested split of available cash, in priority order."""
    if not allocations:
        return _empty("Nothing to allocate")
    df = pd.DataFrame([{"Use": f"{a['priority']}. {a['label']}", "KES": a["amount_minor"] / 100} for a in allocations])
    return chart_category_breakdown(dict(zip(df["Use"], df["KES"])), color=MONEY_IN)


def chart_daily_outflow_vs_limit(daily: pd.DataFrame, limits: List[Dict]) -> alt.Chart:
    """Money paid out each day against daily limit lines. daily: date, KES.
    limits: [{"label": ..., "KES": ...}] drawn as labelled dashed rules
    (the first in amber, any further ones in red)."""
    if daily.empty:
        return _empty("No payments yet")
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    lines = pd.DataFrame(limits)
    over = df["KES"] > (lines["KES"].min() if not lines.empty else float("inf"))
    df["Status"] = ["Over a daily limit" if o else "Within limits" for o in over]
    x = alt.X("date:T", title=None, axis=DATE_AXIS)
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=2).encode(
        x=x, y=alt.Y("KES:Q", title="Paid out that day (KES)", axis=alt.Axis(format="~s")),
        color=alt.Color("Status:N", scale=alt.Scale(domain=["Within limits", "Over a daily limit"],
                                                    range=[NEUTRAL, CRITICAL]), legend=LEGEND_TOP),
        tooltip=[alt.Tooltip("date:T", title="Date", format="%a %d %b %Y"),
                 alt.Tooltip("KES:Q", title="Paid out (KES)", format=KES), alt.Tooltip("Status:N")])
    layers = [bars]
    for i, row in enumerate(lines.to_dict("records")):
        one = pd.DataFrame([row])
        dash = [6, 4] if i == 0 else [2, 3]
        layers.append(alt.Chart(one).mark_rule(color=CRITICAL if i else WARNING, strokeDash=dash,
                                               strokeWidth=1.5).encode(y="KES:Q"))
        layers.append(alt.Chart(one).mark_text(align="right", x="width", dx=-2, dy=-6, color=TEXT,
                                               fontSize=11).encode(y="KES:Q", text="label:N"))
    return alt.layer(*layers).properties(height=280)


# ---------------------------------------------------------------------------
# Sales, stock, tax
# ---------------------------------------------------------------------------

def chart_daily_sales(daily: pd.DataFrame) -> alt.Chart:
    """Sales per day (bars) and the 7-day average (line). daily: date, KES, count."""
    if daily.empty:
        return _empty("No sales yet")
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["avg7"] = df["KES"].rolling(7, min_periods=1).mean()
    color = alt.Color("Series:N", scale=alt.Scale(domain=["Sales", "7-day average"], range=[MONEY_IN, NET]),
                      legend=LEGEND_TOP)
    x = alt.X("date:T", title=None, axis=DATE_AXIS)
    bars = alt.Chart(df.assign(Series="Sales")).mark_bar(cornerRadiusEnd=2).encode(
        x=x, y=alt.Y("KES:Q", title="KES", axis=alt.Axis(format="~s")), color=color)
    line = alt.Chart(df.assign(Series="7-day average")).mark_line(strokeWidth=2).encode(x="date:T", y="avg7:Q",
                                                                                         color=color)
    tip = _hover_rule(df, "date", [alt.Tooltip("date:T", title="Date", format="%a %d %b"),
                                   alt.Tooltip("KES:Q", title="Sales (KES)", format=KES),
                                   alt.Tooltip("count:Q", title="Sales count"),
                                   alt.Tooltip("avg7:Q", title="7-day average (KES)", format=KES)])
    return alt.layer(bars, line, tip).properties(height=260)


def chart_top_products(rows: pd.DataFrame, limit: int = 10) -> alt.Chart:
    """Best-selling products by revenue. rows: Product, KES, Units."""
    if rows.empty:
        return _empty("No sales yet")
    top = rows.sort_values("KES", ascending=False).head(limit)
    base = alt.Chart(top).encode(y=alt.Y("Product:N", sort=top["Product"].tolist(), title=None,
                                         axis=alt.Axis(labelLimit=200)))
    bars = base.mark_bar(cornerRadiusEnd=4, color=MONEY_IN).encode(
        x=alt.X("KES:Q", title="Revenue (KES)", axis=alt.Axis(format="~s")),
        tooltip=[alt.Tooltip("Product:N"), alt.Tooltip("KES:Q", title="Revenue (KES)", format=KES),
                 alt.Tooltip("Units:Q", format=",.0f")])
    labels = base.mark_text(align="left", dx=4, color=TEXT, fontSize=11).encode(
        x="KES:Q", text=alt.Text("Units:Q", format=",.0f"))
    return (bars + labels).properties(height=max(200, len(top) * 30))


def chart_stock_value(by_category: Dict[str, Dict]) -> alt.Chart:
    """Stock value at cost per product category."""
    data = {(k or "Uncategorised"): v["cost_value_minor"] / 100 for k, v in (by_category or {}).items()}
    return chart_category_breakdown(data, color=MONEY_IN) if data else _empty("No stock data")


def chart_vat_by_month(rows: List[Dict]) -> alt.Chart:
    """Output VAT (collected) and input VAT (paid) per month, plus net payable.
    rows: month (YYYY-MM), output, input (KES)."""
    df = pd.DataFrame(rows)
    if df.empty or not (df["output"].sum() or df["input"].sum()):
        return _empty("No VAT in this period")
    df["month"] = pd.to_datetime(df["month"] + "-01")
    df["net"] = df["output"] - df["input"]
    long = pd.concat([df.assign(Series="VAT collected", KES=df["output"]),
                      df.assign(Series="VAT paid on purchases", KES=df["input"])])
    color = alt.Color("Series:N", scale=alt.Scale(domain=["VAT collected", "VAT paid on purchases", "Net payable"],
                                                  range=[MONEY_IN, MONEY_OUT, NET]), legend=LEGEND_TOP)
    x = alt.X("yearmonth(month):O", title=None, axis=alt.Axis(format="%b %y", labelAngle=0, labelColor=TEXT_MUTED))
    tips = [alt.Tooltip("yearmonth(month):O", title="Month", format="%B %Y"),
            alt.Tooltip("output:Q", title="Collected (KES)", format=",.2f"),
            alt.Tooltip("input:Q", title="Paid (KES)", format=",.2f"), alt.Tooltip("net:Q", title="Net payable (KES)", format=",.2f")]
    bars = alt.Chart(long).mark_bar(cornerRadiusEnd=3).encode(
        x=x, xOffset=alt.XOffset("Series:N", scale=alt.Scale(paddingInner=0.06)), y=alt.Y("KES:Q", title="KES", axis=alt.Axis(format="~s")),
        color=color, tooltip=tips)
    net = alt.Chart(df.assign(Series="Net payable")).mark_line(strokeWidth=2, point=True).encode(
        x=x, y="net:Q", color=color, tooltip=tips)
    return (bars + net).properties(height=280)


# ---- Tool wrapper function for agent dispatch ----

def build_chart(args, business_id: Optional[int] = None,
                db_path: Optional[str] = None) -> dict:
    """Return a chart specification and underlying data.
    
    Args:
        args: BuildChartArgs with chart_id and optional parameters
        business_id: Active business ID
        db_path: Database path
    
    Returns:
        dict with chart specification (Altair JSON) and data frame
    """
    import sqlite3
    import json
    from core.config import Config
    
    if db_path is None:
        db_path = Config.DB_PATH
    if business_id is None:
        return {"error": "business_id required"}
    
    try:
        chart_id = args.chart_id
        params = args.parameters or {}
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Fetch transaction data
        cursor.execute("""
            SELECT 
                local_date as date,
                SUM(CASE WHEN direction = 'in' THEN amount_minor ELSE 0 END) as inflow,
                SUM(CASE WHEN direction = 'out' THEN amount_minor ELSE 0 END) as outflow
            FROM transaction_ledger
            WHERE business_id = ? AND voided = 0
            GROUP BY local_date
            ORDER BY local_date DESC
            LIMIT 365
        """, (business_id,))
        
        rows = cursor.fetchall()
        
        # Convert to DataFrame
        daily_df = pd.DataFrame([
            {
                "date": r["date"],
                "inflow": (r["inflow"] or 0) / 100.0,
                "outflow": (r["outflow"] or 0) / 100.0,
                "net": ((r["inflow"] or 0) - (r["outflow"] or 0)) / 100.0,
            }
            for r in rows
        ])
        
        conn.close()
        
        # Build chart based on chart_id
        if chart_id == "cashflow_trend":
            chart = chart_cashflow_trend(daily_df.sort_values("date"))
        elif chart_id == "category_breakdown":
            # Aggregate by category
            conn = sqlite3.connect(db_path)
            rows = conn.execute("""
                SELECT c.code, SUM(t.amount_minor) as total
                FROM transaction_ledger t
                LEFT JOIN category c ON c.category_id = t.category_id
                WHERE t.business_id = ? AND t.voided = 0 AND t.direction = 'out'
                GROUP BY c.code
            """, (business_id,)).fetchall()
            conn.close()
            cat_data = {row[0] or "UNCLASSIFIED": row[1] / 100.0 for row in rows}
            chart = chart_category_breakdown(cat_data)
        elif chart_id == "forecast_confidence":
            # The business's latest saved forecast (run forecast_balance first)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            run = conn.execute(
                "SELECT run_id, buffer_minor FROM forecast_run WHERE business_id = ? ORDER BY run_id DESC LIMIT 1",
                (business_id,),
            ).fetchone()
            points = [] if run is None else [
                {"date": p["date"], "p10": p["p10_minor"], "p50": p["p50_minor"],
                 "p90": p["p90_minor"], "expected": p["expected_minor"]}
                for p in conn.execute(
                    "SELECT * FROM forecast_point WHERE run_id = ? ORDER BY day_offset", (run["run_id"],))
            ]
            conn.close()
            if not points:
                return {"error": "No forecast yet. Run forecast_balance first."}
            chart = chart_forecast_confidence(points, buffer_kes=run["buffer_minor"] / 100.0)
        else:
            return {"error": f"Unknown chart_id: {chart_id}"}
        
        return {
            "chart_id": chart_id,
            "chart_spec": chart.to_dict(),
            "data_rows": len(daily_df),
            "last_updated": daily_df["date"].max() if len(daily_df) > 0 else None,
        }
    
    except Exception as e:
        return {"error": f"Chart build failed: {e}"}
