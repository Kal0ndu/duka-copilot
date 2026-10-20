"""Page 8: POS Dashboard — Quick Sale, Recent Transactions, Daily Summary."""
import streamlit as st
import sys
from datetime import date

import pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.charts import chart_daily_sales, chart_top_products
from core.pos_engine import POSEngine, POSSetting
from core.inventory_manager import InventoryManager
from core.invoice_manager import InvoiceManager
from core.ai_sales_assistant import AISalesAssistant
from app.session_helpers import SessionManager
from auth.middleware import get_business_id

st.set_page_config(page_title="POS Dashboard — Duka Copilot", page_icon=":material/shopping_cart:", layout="wide")
# ---- Authentication Gate ----
require_auth()

SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = get_business_id()
if not biz_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

pos = POSEngine()
inv_mgr = InventoryManager()
inv = InvoiceManager()
ai = AISalesAssistant()

st.title("POS dashboard", icon=":material/point_of_sale:", anchor=False)
st.caption("Point of Sale: quick sales, daily summary, and recent transactions.")

# ---- POS Settings Check ----
pos_settings = pos.get_pos_setting(biz_id)
if pos_settings is None:
    st.warning("POS not configured for this business. Set up below:")
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

METHOD_LABEL = {"cash": "Cash", "m_pesa": "M-Pesa", "card": "Card", "cheque": "Cheque", "credit": "Credit"}
MONEY = st.column_config.NumberColumn(format="accounting")

# ---- Top KPI Row ----
sales_summary = pos.get_sales_summary(biz_id, days=30)
today_totals = pos.get_day_totals(biz_id, date.today().isoformat())
ai_summary = ai.get_ai_dashboard_summary(biz_id)
products = inv_mgr.list_products(biz_id, active_only=True, limit=500)
alerts = inv_mgr.get_reorder_alerts(biz_id)
avg_ticket = sales_summary["total_sales_minor"] / sales_summary["sale_count"] if sales_summary["sale_count"] else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Sales today", f"KES {today_totals['total_minor']/100:,.0f}", f"{today_totals['count']} sales",
          delta_color="off", border=True)
k2.metric("Sales (30 days)", f"KES {sales_summary['total_sales_minor']/100:,.0f}",
          f"{sales_summary['sale_count']} sales", delta_color="off", border=True)
k3.metric("Average sale (30 days)", f"KES {avg_ticket/100:,.0f}", border=True)
k4.metric("Outstanding invoices", f"KES {ai_summary['total_outstanding_minor']/100:,.0f}",
          f"{ai_summary['overdue_invoices']} overdue", delta_color="inverse" if ai_summary["overdue_invoices"] else "off",
          border=True)
k5.metric("Reorder alerts", f"{len(alerts)}", f"of {len(products)} active products", delta_color="off", border=True)

# ---- Last completed sale (shown after the rerun that saved it) ----
last = st.session_state.pop("pos_last_sale", None)
if last:
    st.success(f"Sale **{last['number']}** completed — KES {last['total']/100:,.2f} ({last['method']})",
               icon=":material/check_circle:")
    with st.expander("Receipt", icon=":material/receipt_long:"):
        st.code(last["receipt"], language=None)

st.divider()

col_left, col_right = st.columns([5, 6], gap="large")

# ---- Quick Sale: pick products, edit quantities in the cart, check totals, complete ----
with col_left:
    st.subheader("Quick sale", anchor=False)
    in_stock = {p.product_id: p for p in products if p.current_stock_qty > 0}
    if not in_stock:
        st.warning("No products in stock. Add products in **Inventory** first.")
    else:
        picked = st.multiselect(
            "Add products", list(in_stock), key="qs_products",
            format_func=lambda pid: f"{in_stock[pid].name} · KES {in_stock[pid].selling_price:,.2f}",
            placeholder="Search products…",
        )
        if picked:
            # Qty/discount per product survive adding or removing other products.
            saved = st.session_state.setdefault("qs_cart_values", {})
            cart = pd.DataFrame([{
                "product_id": pid,
                "Product": in_stock[pid].name,
                "In stock": in_stock[pid].current_stock_qty,
                "Unit price (KES)": in_stock[pid].selling_price_minor / 100,
                "Qty": saved.get(pid, (1, 0.0))[0],
                "Discount %": saved.get(pid, (1, 0.0))[1],
            } for pid in picked])
            edited = st.data_editor(
                cart, key=f"qs_cart_{'-'.join(map(str, picked))}", hide_index=True, width="stretch",
                column_order=["Product", "In stock", "Unit price (KES)", "Qty", "Discount %"],
                disabled=["Product", "In stock", "Unit price (KES)"],
                column_config={
                    "Unit price (KES)": MONEY,
                    "Qty": st.column_config.NumberColumn(min_value=1, step=1, required=True),
                    "Discount %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.5,
                                                                format="%.1f%%"),
                },
            )

            line_items, problems = [], []
            for row in edited.to_dict("records"):
                p = in_stock[row["product_id"]]
                qty = int(row["Qty"] or 1)
                disc = float(row["Discount %"] or 0.0)
                saved[p.product_id] = (qty, disc)
                if qty > p.current_stock_qty:
                    problems.append(f"{p.name}: only {p.current_stock_qty} in stock")
                line_items.append(POSEngine.build_line_item(
                    product_id=p.product_id, quantity=qty, selling_price_minor=p.selling_price_minor,
                    vat_rate_pct=p.vat_rate_pct, vat_applicable=p.vat_applicable,
                    discount_pct=disc or None,
                ))
            subtotal = sum(li.line_subtotal_minor for li in line_items)
            discount = sum(li.discount_amount_minor for li in line_items)
            vat = sum(li.vat_amount_minor for li in line_items)

            t1, t2, t3 = st.columns(3)
            t1.metric("Subtotal", f"KES {subtotal/100:,.2f}",
                      f"-{discount/100:,.2f} discount" if discount else None, delta_color="off")
            t2.metric("VAT", f"KES {vat/100:,.2f}")
            t3.metric("Total", f"KES {(subtotal + vat)/100:,.2f}")

            c1, c2 = st.columns(2)
            payment_method = c1.segmented_control("Payment", list(METHOD_LABEL), default="cash",
                                                  format_func=METHOD_LABEL.get, key="qs_method")
            customer_name = c2.text_input("Customer (optional)", placeholder="Walk-in customer", key="qs_customer")
            notes = st.text_input("Notes (optional)", key="qs_notes")
            if payment_method == "credit" and not customer_name.strip():
                problems.append("A credit sale needs the customer's name")
            for msg in problems:
                st.error(msg, icon=":material/error:")

            if st.button(":material/payments: Complete sale", type="primary", width="stretch",
                         disabled=bool(problems) or not payment_method):
                settings = pos.get_pos_setting(biz_id)
                sale = pos.create_sale(
                    business_id=biz_id,
                    line_items=line_items,
                    customer_name_token=customer_name.strip() or None,
                    payment_method=payment_method,
                    notes=notes or None,
                    created_by_user=profile.get("phone", "pos_user") if profile else "pos_user",
                )
                st.session_state["pos_last_sale"] = {
                    "number": sale.sale_number, "total": sale.total_amount_minor,
                    "method": METHOD_LABEL[payment_method], "receipt": pos.format_receipt(sale, settings),
                }
                for k in ("qs_products", "qs_customer", "qs_notes", "qs_cart_values"):
                    st.session_state.pop(k, None)
                st.rerun()
        else:
            st.caption("Pick one or more products to start a sale. Quantities and discounts are set in the cart.")

# ---- Recent Sales table (select a row for its receipt) ----
with col_right:
    st.subheader("Recent sales", anchor=False)
    recent = pos.get_recent_sales_table(biz_id, limit=50)
    if not recent:
        st.info("No sales yet. Make your first sale!", icon=":material/info:")
    else:
        df = pd.DataFrame([{
            "sale_id": r["sale_id"],
            "Sale #": r["sale_number"],
            "Date": pd.to_datetime(r["sale_date"][:16].replace("T", " ")),
            "Customer": r["customer_name_token"] or "Walk-in",
            "Items": int(r["items"]),
            "Payment": METHOD_LABEL.get(r["payment_method"], r["payment_method"]),
            "Total (KES)": r["total_amount_minor"] / 100,
            "Status": "Owed" if r["payment_status"] == "pending" else "Paid",
        } for r in recent])
        picked_sale = st.dataframe(
            df, hide_index=True, width="stretch", height=420,
            column_order=["Sale #", "Date", "Customer", "Items", "Payment", "Total (KES)", "Status"],
            column_config={
                "Date": st.column_config.DatetimeColumn(format="D MMM YYYY, HH:mm"),
                "Items": st.column_config.NumberColumn(width="small"),
                "Total (KES)": MONEY,
            },
            on_select="rerun", selection_mode="single-row", key="pos_recent",
        )
        rows = picked_sale.selection.rows
        if rows:
            sale = pos.get_sale(int(df.iloc[rows[0]]["sale_id"]))
            with st.container(border=True):
                st.markdown(f"**{sale.sale_number}** · {sale.customer_name_token or 'Walk-in'}")
                names = {p.product_id: p.name for p in inv_mgr.list_products(biz_id, active_only=False, limit=1000)}
                st.dataframe(pd.DataFrame([{
                    "Product": names.get(li.product_id, f"#{li.product_id}"),
                    "Qty": li.quantity,
                    "Unit (KES)": li.unit_price_minor / 100,
                    "Discount (KES)": li.discount_amount_minor / 100,
                    "VAT (KES)": li.vat_amount_minor / 100,
                    "Line total (KES)": li.line_total_minor / 100,
                } for li in sale.line_items]), hide_index=True, width="stretch", column_config={
                    "Unit (KES)": MONEY, "Discount (KES)": MONEY, "VAT (KES)": MONEY, "Line total (KES)": MONEY})
        else:
            st.caption("Select a row to see what was sold.")

        breakdown = sales_summary["payment_breakdown"]
        if breakdown:
            st.markdown("**Payment mix (30 days)**")
            total_30 = sales_summary["total_sales_minor"] or 1
            st.dataframe(pd.DataFrame([{
                "Payment": METHOD_LABEL.get(m, m),
                "Sales": v["count"],
                "Total (KES)": v["total_minor"] / 100,
                "Share": v["total_minor"] / total_30,
            } for m, v in sorted(breakdown.items(), key=lambda kv: -kv[1]["total_minor"])]),
                hide_index=True, width="stretch", column_config={
                    "Total (KES)": MONEY,
                    "Share": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                })

# ---- Sales trend and best sellers (last 30 days) ----
st.subheader("Sales over the last 30 days", icon=":material/insights:", anchor=False)
trend_col, top_col = st.columns([3, 2], gap="large")
with trend_col:
    daily = pd.DataFrame(pos.get_daily_sales(biz_id, days=30))
    daily["KES"] = daily["total_minor"] / 100
    st.caption("Blue bars: sales each day. Green line: the 7-day average, which smooths out busy and quiet days.")
    st.altair_chart(chart_daily_sales(daily[["date", "KES", "count"]]), width="stretch")
with top_col:
    top = pd.DataFrame(pos.get_top_products(biz_id, days=30))
    st.caption("Best sellers by money taken (incl. VAT). Labels show units sold.")
    if top.empty:
        st.info("No sales in the last 30 days.", icon=":material/info:")
    else:
        st.altair_chart(chart_top_products(top.rename(columns={"product": "Product", "units": "Units"})
                                              .assign(KES=top["total"] / 100)), width="stretch")

# ---- Bottom Row: Reorder Alerts & AI Tasks ----
st.divider()
bot1, bot2 = st.columns(2)

with bot1:
    st.subheader("Reorder alerts", anchor=False)
    if alerts:
        st.dataframe(pd.DataFrame([{
            "Product": p.name,
            "SKU": p.sku,
            "In stock": p.current_stock_qty,
            "Reorder at": p.reorder_level_qty,
            "Stock level": min(1.0, p.current_stock_qty / p.reorder_level_qty) if p.reorder_level_qty else 0.0,
            "Order qty": p.reorder_qty,
        } for p in alerts]), hide_index=True, width="stretch", column_config={
            "Stock level": st.column_config.ProgressColumn(
                format="percent", min_value=0, max_value=1, help="Stock as a share of the reorder level"),
        })
    else:
        st.success("All products well-stocked!", icon=":material/check_circle:")

with bot2:
    st.subheader("AI follow-ups", icon=":material/smart_toy:", anchor=False)
    pending = ai.get_pending_tasks(biz_id, limit=10)
    if not pending:
        st.info("No pending follow-ups. Generate new tasks:")
        if st.button(":material/refresh: Generate Follow-up Tasks"):
            result = ai.generate_all_tasks(biz_id)
            st.success(f"Created {result['total_new_tasks']} tasks")
            st.rerun()
    else:
        for t in pending:
            icon = ":material/mail:" if t.task_type == "payment_reminder" else ":material/list_alt:" if t.task_type == "quotation_follow_up" else ":material/warning:"
            st.write(f"{icon} **{t.task_type.replace('_',' ').title()}** — {t.customer_name_token or 'Unknown'}")
            with st.expander("Details"):
                st.caption(t.message_template)
                st.caption(f"*Suggested:* {t.ai_suggested_action}")
                col_a, col_b = st.columns(2)
                if col_a.button(":material/check_circle: Done", key=f"done_{t.task_id}"):
                    ai.complete_task(t.task_id, "contacted_payment_promised", profile.get("phone") if profile else None)
                    st.rerun()
                if col_b.button(":material/skip_next: Skip", key=f"skip_{t.task_id}"):
                    ai.skip_task(t.task_id)
                    st.rerun()
