"""Page 4: Customer & Supplier Intelligence, Concentration Risk, and Churn Radar."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.relationship_analyzer import RelationshipAnalyzer
from core.charts import (
    chart_customer_concentration, chart_recency, chart_revenue_pareto, chart_segments, chart_supplier_spend,
)
from app.sample_loader import load_sample_business, MOCK_PROFILES
from app.session_helpers import SessionManager, render_data_info_banner

st.set_page_config(page_title="Party Intelligence — Duka", page_icon=":material/handshake:", layout="wide")
# ---- Authentication Gate ----
require_auth()


# Initialize session and check for data
SessionManager.init_session()
transactions = SessionManager.get_transactions()
profile = SessionManager.get_profile()

if not transactions:
    st.warning("No statement currently loaded.")
    st.info("Load a sample business profile to inspect customer relationships and supplier dependencies:")
    col1, col2, col3 = st.columns(3)
    if col1.button(":material/storefront: Load Amina's Grocery", width="stretch"):
        SessionManager.set_transactions(load_sample_business("amina_grocery"), MOCK_PROFILES["amina_grocery"])
        st.rerun()
    if col2.button(":material/directions_bike: Load Otieno Transport", width="stretch"):
        SessionManager.set_transactions(load_sample_business("otieno_transport"), MOCK_PROFILES["otieno_transport"])
        st.rerun()
    if col3.button(":material/content_cut: Load Grace Salon", width="stretch"):
        SessionManager.set_transactions(load_sample_business("grace_salon"), MOCK_PROFILES["grace_salon"])
        st.rerun()
    st.stop()

analyzer = RelationshipAnalyzer(transactions)
customers = analyzer.get_customers()
suppliers = analyzer.get_suppliers()
all_concentration = analyzer.get_concentration_risks()
# Customers: share of revenue. Suppliers: share of spending (a different risk).
concentration_risks = [p for p in all_concentration if p.party_type == "customer"]
supplier_dependencies = [p for p in all_concentration if p.party_type == "supplier"]
churn_risks = analyzer.get_churn_risks()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

st.title("Customer & supplier intelligence", icon=":material/groups:")
st.caption(f"Identify VIP clients, customer concentration risks, and dormant accounts for **{biz_name}**.")

# ---- ROW 1: RELATIONSHIP OVERVIEW KPIS ----
top_share = customers[0].concentration_pct if customers else 0.0
top_name = customers[0].party_name if customers else "None"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Active Customers", len(customers), help="Unique buyers identified in statement.")
c2.metric("Active Suppliers", len(suppliers), help="Vendors and operational payees.")
c3.metric(
    "Top Buyer Concentration",
    f"{top_share:.1f}%",
    delta="High Risk (>20%)" if top_share >= 20.0 else "Healthy (<20%)",
    delta_color="inverse" if top_share >= 20.0 else "normal",
    help="Share of total revenue from your single largest customer."
)
c4.metric(
    "At-Risk / Lapsed Clients",
    len(churn_risks),
    delta="Needs Attention" if churn_risks else "Stable",
    delta_color="inverse" if churn_risks else "normal"
)

st.divider()

# ---- SECTION 2: CONCENTRATION RISK RADAR ----
st.subheader("Revenue concentration risk", icon=":material/warning:")
st.caption("A healthy business should not rely on any single customer for more than 20% of its income.")

if concentration_risks:
    st.error(
        f"**Concentration Alert:** You have **{len(concentration_risks)}** customer(s) each representing "
        "20% or more of your total business revenue! If any of them switches to a competitor, "
        "your cashflow will suffer severe disruption."
    )
    for risk in concentration_risks:
        st.markdown(
            f"- **{risk.party_name}**: Accounts for **{risk.concentration_pct:.1f}%** of your total revenue "
            f"(KES {risk.inflow_kes:,.0f} across {risk.transaction_count} orders). "
            f"*{risk.recommendation}*"
        )
else:
    st.success("**Well-Diversified Revenue:** No single customer accounts for more than 20% of your sales.")

st.caption("Your 10 biggest customers by share of revenue. Red bars are past the 20% risk line.")
st.altair_chart(chart_customer_concentration(customers), width="stretch")

st.subheader("How spread out your revenue is", icon=":material/stacked_line_chart:")
st.caption("Blue bars: each customer's share, largest first. Green line: the running total. The sooner the line "
           "reaches 80%, the more you depend on a few customers.")
st.altair_chart(chart_revenue_pareto(customers), width="stretch")

# ---- CUSTOMER DISTRIBUTION ----
st.subheader("Your customers at a glance", icon=":material/donut_small:")
col_seg, col_rec = st.columns(2)
with col_seg:
    seg_measure = st.segmented_control("Show", ["Customers", "Revenue"], default="Customers", key="pi_seg_measure",
                                       label_visibility="collapsed")
    st.caption("**Segments.** High value: 15%+ of revenue, or 10%+ with 5+ orders. Growth: paid in the last "
               "3 weeks. At risk: 22–45 days quiet. Dormant: over 45 days.")
    st.altair_chart(chart_segments(customers, "revenue" if seg_measure == "Revenue" else "count"), width="stretch")
with col_rec:
    st.caption("**Time since last payment.** Darker bars are customers who have gone quiet the longest; "
               "hover to see how much they have paid you so far.")
    st.altair_chart(chart_recency(customers), width="stretch")

# ---- SECTION 3: CUSTOMER RFM SEGMENTATION & CHURN WATCHLIST ----
st.subheader("Customer segments & churn early warning")
tab_all_cust, tab_churn, tab_high_val = st.tabs([
    "All Customers Ranking",
    "Churn watchlist (At-Risk / Dormant)",
    ":material/star: High-value VIP clients"
])

with tab_all_cust:
    cust_table = []
    for rank, c in enumerate(customers[:25], 1):
        cust_table.append({
            "Rank": f"#{rank}",
            "Customer (Token)": c.party_name,
            "Total Volume (KES)": f"{c.inflow_kes:,.2f}",
            "Revenue Share": f"{c.concentration_pct:.1f}%",
            "Orders": c.transaction_count,
            "Avg Order": f"KES {c.avg_transaction_kes:,.0f}",
            "Days Since Last Purchase": f"{c.days_since_interaction}d ago",
            "Segment": c.segment,
            "Churn Risk Score": f"{c.churn_risk_score}/100",
        })
    st.dataframe(cust_table, width="stretch")

with tab_churn:
    if churn_risks:
        st.warning(f"Found **{len(churn_risks)}** customers whose purchasing pattern is cooling down or dormant.")
        churn_table = []
        for c in churn_risks:
            churn_table.append({
                "Customer": c.party_name,
                "Status": c.segment,
                "Days Inactive": f"{c.days_since_interaction} days",
                "Historical Value (KES)": f"{c.inflow_kes:,.0f}",
                "Churn Probability": f"{c.churn_risk_score}%",
                "Action Prompt": c.recommendation,
            })
        st.dataframe(churn_table, width="stretch")

        st.markdown("##### :material/chat: Recommended re-engagement SMS / WhatsApp Message:")
        sample_c = churn_risks[0]
        st.code(
            f"Habari {sample_c.party_name}! We haven't seen you at {biz_name} lately and wanted to check in. "
            f"Enjoy 10% off your next purchase this week. Karibu sana!",
            language="text"
        )
    else:
        st.success("All customers are currently active and engaged. Zero high churn risks detected!")

with tab_high_val:
    vip_cust = [c for c in customers if c.segment == "High Value"]
    if vip_cust:
        st.markdown(f"**{len(vip_cust)} VIP Clients** drive the bulk of your business profit:")
        vip_table = []
        for c in vip_cust:
            vip_table.append({
                "Customer": c.party_name,
                "Total Spent (KES)": f"{c.inflow_kes:,.0f}",
                "Share of Business": f"{c.concentration_pct:.1f}%",
                "Transaction Count": c.transaction_count,
                "Last Active": c.last_interaction,
                "Strategy": c.recommendation,
            })
        st.dataframe(vip_table, width="stretch")
    else:
        st.info("No customers classified as High Value yet.")

st.divider()

# ---- SECTION 4: SUPPLIER DEPENDENCY ----
st.subheader("Supplier spending & vendor reliance", icon=":material/local_shipping:")
st.caption("Track who you spend the most money with and identify reliance on single vendors.")
if suppliers:
    st.altair_chart(chart_supplier_spend(suppliers), width="stretch")

for dep in supplier_dependencies:
    st.warning(
        f"**Supplier dependency:** {dep.party_name} receives **{dep.concentration_pct:.1f}%** of everything you pay out "
        f"(KES {dep.outflow_kes:,.0f} across {dep.transaction_count} payments). Line up a backup supplier in case "
        "they raise prices or can't deliver."
    )

if suppliers:
    sup_table = []
    total_out = sum(s.outflow_kes for s in suppliers)
    for s in suppliers[:15]:
        share = (s.outflow_kes / total_out * 100.0) if total_out > 0 else 0
        sup_table.append({
            "Supplier / Vendor": s.party_name,
            "Total Spend (KES)": f"{s.outflow_kes:,.2f}",
            "Share of Total Outflow": f"{share:.1f}%",
            "Payments Made": s.transaction_count,
            "Avg Payment": f"KES {s.avg_transaction_kes:,.0f}",
            "Last Paid": s.last_interaction,
        })
    st.dataframe(sup_table, width="stretch")
else:
    st.info("No supplier records found.")
