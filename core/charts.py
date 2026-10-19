"""Reusable Altair charts for business metrics, forecasting, and risk analysis."""
import pandas as pd
import altair as alt
from typing import Dict, List, Optional


# Palette
PRIMARY_GREEN = "#10B981"  # Inflows / Safe / Profit
SECONDARY_BLUE = "#3B82F6" # Expected / Medians
ACCENT_CORAL = "#EF4444"   # Outflows / Risks / Buffer
AMBER_WARNING = "#F59E0B"  # Moderate risk / At-Risk
MUTED_GRAY = "#6B7280"     # Neutral


def chart_cashflow_trend(daily_df: pd.DataFrame) -> alt.Chart:
    """Layered chart showing daily inflows, outflows, and net cashflow."""
    if daily_df.empty:
        return alt.Chart(pd.DataFrame({"msg": ["No data available"]})).mark_text().encode(text="msg")

    df_melt = pd.melt(
        daily_df,
        id_vars=["date"],
        value_vars=["inflow", "outflow"],
        var_name="Flow Type",
        value_name="KES"
    )
    df_melt["Flow Type"] = df_melt["Flow Type"].map({"inflow": "Money In (Sales)", "outflow": "Money Out (Expenses)"})

    bars = alt.Chart(df_melt).mark_bar(opacity=0.85).encode(
        x=alt.X("date:T", title="Date", axis=alt.Axis(format="%b %d")),
        y=alt.Y("KES:Q", title="Amount (KES)"),
        color=alt.Color(
            "Flow Type:N",
            scale=alt.Scale(
                domain=["Money In (Sales)", "Money Out (Expenses)"],
                range=[PRIMARY_GREEN, ACCENT_CORAL]
            ),
            legend=alt.Legend(title="", orient="top")
        ),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
            alt.Tooltip("Flow Type:N", title="Type"),
            alt.Tooltip("KES:Q", title="Amount (KES)", format=",.0f"),
        ]
    )

    line = alt.Chart(daily_df).mark_line(color="#1E3A8A", strokeWidth=2.5, point=True).encode(
        x=alt.X("date:T"),
        y=alt.Y("net:Q", title="Net Margin (KES)"),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
            alt.Tooltip("net:Q", title="Net (KES)", format=",.0f"),
        ]
    )

    return (bars + line).properties(height=340).interactive()


def chart_forecast_confidence(points: List[Dict], buffer_kes: float = 5000.0) -> alt.Chart:
    """Monte Carlo Forecast fan chart: P10-P90 band, P50 median line, and safety buffer threshold."""
    if not points:
        return alt.Chart(pd.DataFrame({"msg": ["No forecast available"]})).mark_text().encode(text="msg")

    data = []
    for p in points:
        data.append({
            "date": p["date"],
            "p10_kes": p["p10"] / 100.0,
            "p50_kes": p["p50"] / 100.0,
            "p90_kes": p["p90"] / 100.0,
            "expected_kes": p.get("expected", p["p50"]) / 100.0,
            "buffer_kes": buffer_kes,
        })
    df = pd.DataFrame(data)

    # Shaded confidence band (P10 to P90)
    band = alt.Chart(df).mark_area(opacity=0.25, color=SECONDARY_BLUE).encode(
        x=alt.X("date:T", title="Forecast Date", axis=alt.Axis(format="%b %d")),
        y=alt.Y("p10_kes:Q", title="Projected Balance (KES)"),
        y2=alt.Y2("p90_kes:Q"),
    )

    # Median expected path (P50)
    p50_line = alt.Chart(df).mark_line(color=SECONDARY_BLUE, strokeWidth=3).encode(
        x=alt.X("date:T"),
        y=alt.Y("p50_kes:Q"),
        tooltip=[
            alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
            alt.Tooltip("p50_kes:Q", title="Expected (P50)", format=",.0f"),
            alt.Tooltip("p10_kes:Q", title="Conservative (P10)", format=",.0f"),
            alt.Tooltip("p90_kes:Q", title="Optimistic (P90)", format=",.0f"),
        ]
    )

    # Safety buffer reference line
    buffer_rule = alt.Chart(df).mark_rule(color=ACCENT_CORAL, strokeDash=[5, 5], strokeWidth=2).encode(
        y=alt.Y("buffer_kes:Q"),
        tooltip=[alt.Tooltip("buffer_kes:Q", title="Safety Buffer (KES)", format=",.0f")]
    )

    return (band + p50_line + buffer_rule).properties(height=360).interactive()


def chart_category_breakdown(cat_dict: Dict[str, float], title: str = "Spending by Category") -> alt.Chart:
    """Horizontal bar chart of spending or income by category."""
    if not cat_dict:
        return alt.Chart(pd.DataFrame({"msg": ["No category data"]})).mark_text().encode(text="msg")

    total = sum(cat_dict.values())
    rows = []
    for k, v in cat_dict.items():
        pct = (v / total * 100.0) if total > 0 else 0
        rows.append({"Category": k, "Amount (KES)": v, "Share (%)": round(pct, 1)})

    df = pd.DataFrame(rows).sort_values("Amount (KES)", ascending=True)

    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=4, color="#3B82F6").encode(
        x=alt.X("Amount (KES):Q", title="Total Amount (KES)"),
        y=alt.Y("Category:N", sort="-x", title=""),
        tooltip=[
            alt.Tooltip("Category:N"),
            alt.Tooltip("Amount (KES):Q", format=",.0f"),
            alt.Tooltip("Share (%):Q", format=".1f"),
        ]
    ).properties(height=max(200, len(df) * 32))

    text = chart.mark_text(
        align="left",
        baseline="middle",
        dx=5,
        fontSize=11,
        color="#374151"
    ).encode(
        text=alt.Text("Share (%):Q", format=".1f")
    )

    return (chart + text)


def chart_weekday_seasonality(weekday_df: pd.DataFrame) -> alt.Chart:
    """Bar chart showing sales trends across Monday through Sunday."""
    if weekday_df.empty:
        return alt.Chart(pd.DataFrame({"msg": ["No data"]})).mark_text().encode(text="msg")

    chart = alt.Chart(weekday_df).mark_bar(cornerRadius=4, color=PRIMARY_GREEN).encode(
        x=alt.X("day_name:N", sort=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], title="Day of Week"),
        y=alt.Y("avg_inflow:Q", title="Average Daily Sales (KES)"),
        tooltip=[
            alt.Tooltip("day_name:N", title="Day"),
            alt.Tooltip("avg_inflow:Q", title="Avg Sales (KES)", format=",.0f"),
            alt.Tooltip("avg_outflow:Q", title="Avg Expenses (KES)", format=",.0f"),
            alt.Tooltip("avg_txns:Q", title="Avg Transactions", format=".1f"),
        ]
    ).properties(height=280)

    return chart


def chart_aging_buckets(buckets: Dict[str, float], title: str = "Aging Buckets") -> alt.Chart:
    """Bar chart for receivables or payables aging buckets."""
    df = pd.DataFrame([{"Bucket": k, "Amount (KES)": v} for k, v in buckets.items()])

    chart = alt.Chart(df).mark_bar(cornerRadius=4).encode(
        x=alt.X("Bucket:N", sort=None, title=""),
        y=alt.Y("Amount (KES):Q", title="Outstanding (KES)"),
        color=alt.Color(
            "Bucket:N",
            scale=alt.Scale(
                domain=list(buckets.keys()),
                range=[PRIMARY_GREEN, AMBER_WARNING, "#F97316", ACCENT_CORAL][:len(buckets)]
            ),
            legend=None
        ),
        tooltip=[
            alt.Tooltip("Bucket:N"),
            alt.Tooltip("Amount (KES):Q", format=",.0f"),
        ]
    ).properties(height=260)

    return chart


def chart_customer_concentration(customers: List) -> alt.Chart:
    """Horizontal bar chart showing top customers and concentration risk threshold (>20%)."""
    if not customers:
        return alt.Chart(pd.DataFrame({"msg": ["No customer data"]})).mark_text().encode(text="msg")

    data = []
    for c in customers[:10]:
        data.append({
            "Customer": c.party_name if hasattr(c, "party_name") else str(c.get("name", "")),
            "Revenue (KES)": c.inflow_kes if hasattr(c, "inflow_kes") else float(c.get("volume", 0)),
            "Share (%)": c.concentration_pct if hasattr(c, "concentration_pct") else float(c.get("share", 0)),
            "Is Risk": c.is_concentration_risk if hasattr(c, "is_concentration_risk") else False,
        })
    df = pd.DataFrame(data).sort_values("Share (%)", ascending=False)

    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("Share (%):Q", title="% of Total Revenue", scale=alt.Scale(domain=[0, max(25, df["Share (%)"].max() + 5)])),
        y=alt.Y("Customer:N", sort="-x", title=""),
        color=alt.condition(
            alt.datum["Share (%)"] >= 20.0,
            alt.value(ACCENT_CORAL),
            alt.value(PRIMARY_GREEN)
        ),
        tooltip=[
            alt.Tooltip("Customer:N"),
            alt.Tooltip("Revenue (KES):Q", format=",.0f"),
            alt.Tooltip("Share (%):Q", format=".1f"),
        ]
    ).properties(height=max(200, len(df) * 32))

    rule = alt.Chart(pd.DataFrame({"risk_limit": [20.0]})).mark_rule(
        color=ACCENT_CORAL, strokeDash=[4, 4], strokeWidth=2
    ).encode(
        x="risk_limit:Q"
    )

    return (bars + rule)


def chart_loan_comparison(offers: List) -> alt.Chart:
    """Grouped bar chart comparing Disbursed amount vs Total Repayable across digital lenders."""
    if not offers:
        return alt.Chart(pd.DataFrame({"msg": ["No loan offers"]})).mark_text().encode(text="msg")

    rows = []
    for o in offers:
        lender = getattr(o, "lender", "Lender")
        product = getattr(o, "product", "Product")
        label = f"{lender} ({product})"
        rows.append({"Product": label, "Type": "Disbursed (You Receive)", "KES": getattr(o, "disbursed_minor", 0) / 100.0})
        rows.append({"Product": label, "Type": "Total Repayable", "KES": getattr(o, "total_repayable_minor", 0) / 100.0})

    df = pd.DataFrame(rows)

    chart = alt.Chart(df).mark_bar(cornerRadius=3).encode(
        x=alt.X("Type:N", title="", axis=alt.Axis(labels=False)),
        y=alt.Y("KES:Q", title="KES"),
        color=alt.Color(
            "Type:N",
            scale=alt.Scale(domain=["Disbursed (You Receive)", "Total Repayable"], range=[PRIMARY_GREEN, ACCENT_CORAL]),
            legend=alt.Legend(orient="top", title="")
        ),
        column=alt.Column("Product:N", title="Digital Loan Options", header=alt.Header(labelAngle=-25, labelAlign="right")),
        tooltip=[
            alt.Tooltip("Product:N"),
            alt.Tooltip("Type:N"),
            alt.Tooltip("KES:Q", format=",.0f"),
        ]
    ).properties(width=100, height=280)

    return chart


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
