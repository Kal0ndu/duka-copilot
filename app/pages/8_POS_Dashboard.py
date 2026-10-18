"""Page 8: POS Dashboard — Quick Sale, Recent Transactions, Daily Summary."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.pos_engine import POSEngine, POSSetting
from core.inventory_manager import InventoryManager
from core.invoice_manager import InvoiceManager
from core.ai_sales_assistant import AISalesAssistant
from app.session_helpers import SessionManager

st.set_page_config(page_title="POS Dashboard — Duka", page_icon="🛒", layout="wide")

SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = profile.get("business_id", 1) if profile else 1

pos = POSEngine()
inv_mgr = InventoryManager()
inv = InvoiceManager()
ai = AISalesAssistant()

st.title("🛒 POS Dashboard")
st.caption("Point of Sale: quick sales, daily summary, and recent transactions.")

# ---- POS Settings Check ----
pos_settings = pos.get_pos_setting(biz_id)
if pos_settings is None:
    st.warning("⚠️ POS not configured for this business. Set up below:")
    with st.form("pos_setup"):
        biz_name = st.text_input("Business Name", value=profile.get("name", "") if profile else "")
        biz_phone = st.text_input("Business Phone")
        biz_pin = st.text_input("KRA PIN")
        vat = st.number_input("Default VAT %", value=16.0, min_value=0.0, max_value=100.0, step=0.5)
        if st.form_submit_button("Enable POS"):
            pos.upsert_pos_setting(POSSetting(
                business_id=biz_id,
                pos_enabled=True,
                default_vat_pct=vat,
                business_name=biz_name,
                business_phone=biz_phone,
                business_pin=biz_pin,
            ))
            st.rerun()
    st.stop()

# ---- Top KPI Row ----
sales_summary = pos.get_sales_summary(biz_id, days=30)
ai_summary = ai.get_ai_dashboard_summary(biz_id)
products = inv_mgr.list_products(biz_id, active_only=True, limit=500)
alerts = inv_mgr.get_reorder_alerts(biz_id)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Sales (30d)", f"KES {sales_summary['total_sales_minor']/100:,.0f}", f"{sales_summary['sale_count']} txns")
k2.metric("Products", f"{len(products)} active")
k3.metric("Outstanding Invoices", f"KES {ai_summary['total_outstanding_minor']/100:,.0f}", f"{ai_summary['overdue_invoices']} overdue")
k4.metric("Reorder Alerts", f"{len(alerts)} products", delta_color="inverse")

st.divider()

# ---- Quick Sale Form ----
col_left, col_right = st.columns([2, 3])

with col_left:
    st.subheader("🛍️ Quick Sale")
    with st.form("quick_sale"):
        product_opts = {f"{p.name} (KES {p.selling_price:,.2f} | Stock: {p.current_stock_qty})": p for p in products if p.current_stock_qty > 0}
        if not product_opts:
            st.warning("No products in stock. Add products in Inventory first.")
        else:
            selected_names = st.multiselect("Products", list(product_opts.keys()), key="qs_products")
            payment_method = st.selectbox("Payment", ["cash", "m_pesa", "card", "cheque", "credit"])
            customer_name = st.text_input("Customer Name (optional)", placeholder="Walk-in customer")
            notes = st.text_area("Notes (optional)")
            submitted = st.form_submit_button("💰 Complete Sale", use_container_width=True, type="primary")

            if submitted and selected_names:
                settings = pos.get_pos_setting(biz_id)
                vat_pct = settings.default_vat_pct if settings else 16.0
                line_items = []
                for sel in selected_names:
                    p = product_opts[sel]
                    li = POSEngine.build_line_item(
                        product_id=p.product_id,
                        quantity=1,
                        selling_price_minor=p.selling_price_minor,
                        vat_rate_pct=vat_pct,
                        vat_applicable=p.vat_applicable,
                    )
                    line_items.append(li)

                sale = pos.create_sale(
                    business_id=biz_id,
                    line_items=line_items,
                    customer_name_token=customer_name or None,
                    payment_method=payment_method,
                    notes=notes or None,
                    created_by_user=profile.get("phone", "pos_user") if profile else "pos_user",
                )
                st.success(f"✅ Sale {sale.sale_number} completed — KES {sale.total_amount_minor/100:,.2f}")
                with st.expander("🧾 Receipt"):
                    st.code(pos.format_receipt(sale, settings))
                st.rerun()

with col_right:
    st.subheader("📋 Recent Sales")
    recent_sales = pos.get_sales_for_business(biz_id, limit=20)
    if not recent_sales:
        st.info("No sales yet. Make your first sale!")
    else:
        for s in recent_sales:
            amt = f"KES {s.total_amount_minor/100:,.2f}"
            cust = s.customer_name_token or "Walk-in"
            st.write(f"**{s.sale_number}** — {amt} — {s.payment_method.upper()} — {cust} — {s.sale_date[:10]}")

# ---- Bottom Row: Reorder Alerts & AI Tasks ----\
st.divider()
bot1, bot2 = st.columns(2)

with bot1:
    st.subheader("⚠️ Reorder Alerts")
    if alerts:
        for p in alerts:
            st.warning(f"**{p.name}** — {p.current_stock_qty} left (reorder at {p.reorder_level_qty})")
    else:
        st.success("All products well-stocked!")

with bot2:
    st.subheader("🤖 AI Follow-ups")
    pending = ai.get_pending_tasks(biz_id, limit=10)
    if not pending:
        st.info("No pending follow-ups. Generate new tasks:")
        if st.button("🔄 Generate Follow-up Tasks"):
            result = ai.generate_all_tasks(biz_id)
            st.success(f"Created {result['total_new_tasks']} tasks")
            st.rerun()
    else:
        for t in pending:
            icon = "📧" if t.task_type == "payment_reminder" else "📋" if t.task_type == "quotation_follow_up" else "⚠️"
            st.write(f"{icon} **{t.task_type.replace('_',' ').title()}** — {t.customer_name_token or 'Unknown'}")
            with st.expander("Details"):
                st.caption(t.message_template)
                st.caption(f"*Suggested:* {t.ai_suggested_action}")
                col_a, col_b = st.columns(2)
                if col_a.button("✅ Done", key=f"done_{t.task_id}"):
                    ai.complete_task(t.task_id, "contacted_payment_promised", profile.get("phone") if profile else None)
                    st.rerun()
                if col_b.button("⏭️ Skip", key=f"skip_{t.task_id}"):
                    ai.skip_task(t.task_id)
                    st.rerun()
