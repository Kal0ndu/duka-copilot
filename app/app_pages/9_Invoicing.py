"""Page 9: Invoice & Quotation Management — Create, track, manage, and follow up."""
import streamlit as st
import sys
import pandas as pd
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core import csv_import
from core.config import config
from core.invoice_manager import (
    ISSUED_STATUSES, OPEN_PAYMENT_STATUSES, InvoiceManager, InvoiceLineItem, QuotationLineItem, list_customers,
)
from core.inventory_manager import InventoryManager
from core.pos_engine import POSEngine
from core.ai_sales_assistant import AISalesAssistant
from app.session_helpers import SessionManager
from auth.middleware import get_business_id

st.set_page_config(page_title="Invoicing — Duka Copilot", page_icon=":material/description:", layout="wide")

# ---- Session & Auth ----
require_auth()
SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = get_business_id()
if not biz_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

# ---- Initialize Managers ----
inv_mgr = InvoiceManager()
inv_prod_mgr = InventoryManager()
pos = POSEngine()
ai_asst = AISalesAssistant()

VAT_RATE = 16.0  # Kenya standard rate
CUSTOM_ITEM = "— Custom item / service —"
NEW_CUSTOMER = "— New customer (type the name) —"


def _display_status(inv) -> str:
    """What the owner sees: draft/cancelled first, then overdue by due date, else payment status."""
    if inv.status in ("draft", "cancelled"):
        return inv.status
    if inv.is_overdue:
        return "overdue"
    return inv.payment_status


def _line_items_editor(state_key: str, products) -> list:
    """Line items kept in session state: list with remove buttons, then an
    add-item form. Buttons live outside forms (Streamlit forbids st.button
    inside st.form). Returns the current items."""
    items = st.session_state.setdefault(state_key, [])
    if items:
        st.write("Current items:")
        for idx, item in enumerate(items):
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 0.5], vertical_alignment="center")
            col1.caption(item["description"] + ("" if item["vat_applicable"] else " (no VAT)"))
            col2.caption(f"Qty: {item['quantity']}")
            col3.caption(f"KES {item['unit_price_minor']/100:,.2f}")
            col4.caption(f"KES {item['line_total_minor']/100:,.2f}")
            if col5.button(":material/close:", key=f"{state_key}_remove_{idx}"):
                items.pop(idx)
                st.rerun()

    product_map = {f"{p.name} (SKU: {p.sku})": p for p in products}
    with st.form(f"{state_key}_add", clear_on_submit=True):
        st.write("**Add item:**")
        c1, c2 = st.columns([2, 2])
        choice = c1.selectbox("Item", [CUSTOM_ITEM] + list(product_map), key=f"{state_key}_choice")
        desc = c2.text_input("Description", key=f"{state_key}_desc",
                             placeholder="Required for a custom item; blank uses the product name")
        c3, c4, c5 = st.columns([1, 1, 2], vertical_alignment="bottom")
        qty = c3.number_input("Qty", min_value=1, value=1, step=1, key=f"{state_key}_qty")
        price = c4.number_input("Unit price (KES)", min_value=0.0, value=0.0, step=0.01, format="%.2f",
                                key=f"{state_key}_price", help="0 uses the product's selling price")
        apply_vat = c5.checkbox(f"Apply VAT ({VAT_RATE:g}%)", value=True, key=f"{state_key}_vat")
        if st.form_submit_button(":material/add: Add item", width="stretch"):
            product = product_map.get(choice)
            description = desc.strip() or (product.name if product else "")
            # round, not int(): 0.29 * 100 is 28.999... and would lose a cent
            unit_price_minor = int(round(price * 100)) or (product.selling_price_minor if product else 0)
            if not description:
                st.error("Please enter an item description.")
            elif unit_price_minor <= 0:
                st.error("The unit price must be greater than 0.")
            else:
                subtotal = unit_price_minor * int(qty)
                vat = int(subtotal * VAT_RATE / 100) if apply_vat else 0
                items.append({
                    "product_id": product.product_id if product else None,
                    "description": description,
                    "quantity": int(qty),
                    "unit_price_minor": unit_price_minor,
                    "line_subtotal_minor": subtotal,
                    "vat_applicable": apply_vat,
                    "vat_rate_pct": VAT_RATE if apply_vat else 0.0,
                    "vat_amount_minor": vat,
                    "line_total_minor": subtotal + vat,
                })
                st.rerun()

    if items:
        subtotal = sum(i["line_subtotal_minor"] for i in items)
        vat_total = sum(i["vat_amount_minor"] for i in items)
        t1, t2, t3 = st.columns(3)
        t1.metric("Subtotal", f"KES {subtotal/100:,.2f}")
        t2.metric(f"VAT ({VAT_RATE:g}%)", f"KES {vat_total/100:,.2f}")
        t3.metric("Total", f"KES {(subtotal + vat_total)/100:,.2f}")
    return items


st.title("Invoicing & quotations", icon=":material/receipt_long:")
st.caption(f"Manage invoices, quotations, and customer billing for **{biz_name}**")

# ---- Navigation Tabs ----
tab_overview, tab_new_invoice, tab_new_quotation, tab_manage, tab_payments, tab_import = st.tabs([
    "Overview",
    "Create Invoice",
    ":material/edit_note: Create quotation",
    ":material/search: Manage",
    "Payments & Follow-Ups",
    ":material/upload_file: Import CSV",
])
customer_names = [c["name"] for c in list_customers(config.DB_PATH, biz_id)]

# ============================================================================
# TAB 1: OVERVIEW — Dashboard
# ============================================================================
with tab_overview:
    st.subheader("Invoicing dashboard")

    outstanding_invoices = inv_mgr.get_outstanding_invoices(biz_id)
    all_invoices = inv_mgr.list_invoices(biz_id, limit=100)
    pending_quotations = inv_mgr.list_quotations(biz_id, status="sent")

    total_outstanding = sum(inv.balance_due_minor for inv in outstanding_invoices)
    overdue_invoices = [inv for inv in outstanding_invoices if inv.is_overdue]
    total_overdue = sum(inv.balance_due_minor for inv in overdue_invoices)

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("Total Invoices", len(all_invoices), help="Invoices of every status, drafts included")
    kpi2.metric(
        "Outstanding",
        f"KES {total_outstanding/100:,.0f}",
        f"{len(outstanding_invoices)} invoices",
        help="Total amount still owed by customers on issued invoices"
    )
    kpi3.metric(
        "Overdue",
        f"KES {total_overdue/100:,.0f}",
        f"{len(overdue_invoices)} invoices",
        delta_color="inverse",
        help="Owed on invoices past their due date"
    )
    kpi4.metric("Pending Quotations", len(pending_quotations),
                help="Quotations sent and waiting for the customer's decision")

    # Issued (not draft or cancelled) invoices dated in the last 30 days
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_invoices = [inv for inv in all_invoices
                       if inv.status in ISSUED_STATUSES and inv.invoice_date[:10] >= thirty_days_ago]
    kpi5.metric(
        "Invoiced (30d)",
        f"KES {sum(inv.total_amount_minor for inv in recent_invoices)/100:,.0f}",
        f"{len(recent_invoices)} invoices"
    )

    st.divider()
    st.subheader("Outstanding invoices (overdue first, then by due date)")

    if not outstanding_invoices:
        st.success("All invoices paid! No outstanding balance.")
    else:
        today = date.today()
        sorted_invoices = sorted(outstanding_invoices, key=lambda x: (not x.is_overdue, x.due_date))
        df_outstanding = pd.DataFrame([
            {
                "Invoice #": inv.invoice_number,
                "Customer": inv.customer_name_token or "Unknown",
                "Amount Due (KES)": f"{inv.balance_due_minor/100:,.2f}",
                "Due Date": inv.due_date[:10],
                "Status": _display_status(inv).upper(),
                "Days Overdue": max(0, (today - date.fromisoformat(inv.due_date[:10])).days),
            }
            for inv in sorted_invoices
        ])

        def highlight_status(row):
            if row["Status"] == "OVERDUE":
                return ["background-color: #FFE5E5"] * len(row)
            elif row["Status"] == "PARTIAL":
                return ["background-color: #FFF8DC"] * len(row)
            return [""] * len(row)

        st.dataframe(df_outstanding.style.apply(highlight_status, axis=1), width="stretch", hide_index=True)

# ============================================================================
# TAB 2: CREATE INVOICE
# ============================================================================
with tab_new_invoice:
    st.subheader("Create new invoice")
    products = inv_prod_mgr.list_products(biz_id, active_only=True)
    invoice_items = _line_items_editor("invoice_items", products)

    with st.form("create_invoice_form"):
        col_cust, col_date, col_due = st.columns(3)
        existing_customer = col_cust.selectbox("Customer", [NEW_CUSTOMER] + customer_names, key="inv_customer_pick")
        typed_customer = col_cust.text_input("Customer Name / Business", placeholder="John's Retail Store",
                                             help="Name of the customer/business being invoiced")
        invoice_date = col_date.date_input("Invoice Date", value=date.today(), help="Date invoice is issued")
        due_days = col_due.number_input("Payment Terms (days)", value=30, min_value=0, max_value=365,
                                        help="Days customer has to pay; due date = invoice date + terms")
        notes = st.text_area("Invoice Notes (optional)",
                             placeholder="Payment terms, bank details, thank you note, etc.")
        col_action1, col_action2 = st.columns(2)
        save_draft = col_action1.form_submit_button(":material/save: Save as Draft", width="stretch")
        send = col_action2.form_submit_button(":material/send: Create & Send", width="stretch", type="primary")

    if save_draft or send:
        customer_name = typed_customer.strip() or (existing_customer if existing_customer != NEW_CUSTOMER else "")
        if not customer_name:
            st.error("Please enter the customer's name.")
        elif not invoice_items:
            st.error("Add at least one line item first.")
        else:
            invoice = inv_mgr.create_invoice(
                business_id=biz_id,
                customer_id=0,  # customers are identified by name token
                line_items=[InvoiceLineItem(**item) for item in invoice_items],
                customer_name_token=customer_name.strip(),
                due_days=int(due_days),
                notes=notes or None,
                status="draft" if save_draft else "sent",
                created_by=profile.get("phone", "pos_user") if profile else "pos_user",
                invoice_date=invoice_date,
            )
            st.session_state.invoice_items = []
            st.success(f"Invoice {invoice.invoice_number} {'saved as draft' if save_draft else 'created and sent'}"
                       f" — KES {invoice.total_amount_minor/100:,.2f}, due {invoice.due_date[:10]}")

# ============================================================================
# TAB 3: CREATE QUOTATION
# ============================================================================
with tab_new_quotation:
    st.subheader("Create new quotation")
    st.caption("Create an estimate/quotation for a customer. Convert to invoice when accepted.")
    products_q = inv_prod_mgr.list_products(biz_id, active_only=True)
    quotation_items = _line_items_editor("quotation_items", products_q)

    with st.form("create_quotation_form"):
        col_cust, col_date, col_valid = st.columns(3)
        existing_quote_customer = col_cust.selectbox("Customer", [NEW_CUSTOMER] + customer_names,
                                                     key="quote_customer_pick")
        typed_quote_customer = col_cust.text_input("Customer Name", placeholder="ABC Trading Ltd",
                                                   help="Customer requesting the quotation")
        quote_date = col_date.date_input("Quotation Date", value=date.today())
        valid_days = col_valid.number_input("Valid for (days)", value=30, min_value=1, max_value=365,
                                            help="How long the quotation is valid")
        terms = st.text_area("Payment Terms & Conditions (optional)",
                             placeholder="50% upfront, balance on delivery. Valid for 30 days.")
        create_quote = st.form_submit_button(":material/upload: Create Quotation", type="primary", width="stretch")

    if create_quote:
        quote_customer = typed_quote_customer.strip() or (
            existing_quote_customer if existing_quote_customer != NEW_CUSTOMER else "")
        if not quote_customer:
            st.error("Please enter the customer's name.")
        elif not quotation_items:
            st.error("Add at least one line item first.")
        else:
            quotation = inv_mgr.create_quotation(
                business_id=biz_id,
                customer_id=0,
                line_items=[QuotationLineItem(**item) for item in quotation_items],
                customer_name_token=quote_customer.strip(),
                valid_days=int(valid_days),
                terms=terms or None,
                created_by=profile.get("phone", "pos_user") if profile else "pos_user",
                quotation_date=quote_date,
            )
            st.session_state.quotation_items = []
            st.success(f"Quotation {quotation.quotation_number} created — KES {quotation.total_minor/100:,.2f}, "
                       f"valid until {quotation.valid_until_date[:10]}")

# ============================================================================
# TAB 4: MANAGE INVOICES & QUOTATIONS
# ============================================================================
with tab_manage:
    st.subheader("Manage invoices & quotations")

    manage_tab1, manage_tab2 = st.tabs(["Invoices", "Quotations"])

    # ---- INVOICES ----
    with manage_tab1:
        st.write("**All Invoices:**")

        col_filter1, col_filter2 = st.columns(2)
        status_filter = col_filter1.multiselect(
            "Filter by Status",
            ["draft", "unpaid", "partial", "overdue", "paid", "cancelled"],
            default=["unpaid", "partial", "overdue"],
        )
        search_invoice = col_filter2.text_input("Search by Invoice # or Customer")

        all_invs = inv_mgr.list_invoices(biz_id, limit=500)
        filtered_invs = [
            inv for inv in all_invs
            if (not status_filter or _display_status(inv) in status_filter)
            and (not search_invoice or search_invoice.lower() in inv.invoice_number.lower() or
                 (inv.customer_name_token and search_invoice.lower() in inv.customer_name_token.lower()))
        ]

        if not filtered_invs:
            st.info("No invoices matching filters")
        else:
            st.dataframe(pd.DataFrame([
                {
                    "Invoice #": inv.invoice_number,
                    "Customer": inv.customer_name_token or "Unknown",
                    "Amount": f"KES {inv.total_amount_minor/100:,.2f}",
                    "Paid": f"KES {inv.amount_paid_minor/100:,.2f}",
                    "Due": f"KES {inv.balance_due_minor/100:,.2f}",
                    "Status": _display_status(inv).upper(),
                    "Due Date": inv.due_date[:10],
                }
                for inv in filtered_invs
            ]), width="stretch", hide_index=True)

            st.divider()
            selected_inv_id = st.selectbox(
                "Select invoice to manage",
                [(inv.invoice_id, inv.invoice_number) for inv in filtered_invs],
                format_func=lambda x: x[1]
            )

            if selected_inv_id:
                inv_to_manage = next(inv for inv in filtered_invs if inv.invoice_id == selected_inv_id[0])
                col_act1, col_act2 = st.columns(2)

                with col_act1:
                    st.info(
                        f"**Invoice:** {inv_to_manage.invoice_number}  \n"
                        f"**Customer:** {inv_to_manage.customer_name_token}  \n"
                        f"**Amount:** KES {inv_to_manage.total_amount_minor/100:,.2f}  \n"
                        f"**Paid:** KES {inv_to_manage.amount_paid_minor/100:,.2f}  \n"
                        f"**Balance Due:** KES {inv_to_manage.balance_due_minor/100:,.2f}  \n"
                        f"**Due Date:** {inv_to_manage.due_date[:10]}  \n"
                        f"**Status:** {_display_status(inv_to_manage)}"
                    )
                    if st.button(":material/mail: Send Reminder", width="stretch"):
                        tasks = ai_asst.generate_payment_reminders(biz_id)
                        if tasks:
                            st.success("Follow-up task created. Check AI Follow-Ups tab.")
                        else:
                            st.info("Follow-up task already pending or invoice already paid.")

                with col_act2:
                    can_pay = (inv_to_manage.status in ISSUED_STATUSES
                               and inv_to_manage.payment_status in OPEN_PAYMENT_STATUSES
                               and inv_to_manage.balance_due_minor > 0)
                    if not can_pay:
                        st.caption("Payments can be recorded only on issued invoices with a balance due "
                                   "(not drafts, paid or cancelled invoices).")
                    else:
                        with st.form(f"payment_form_{inv_to_manage.invoice_id}"):
                            st.write("**Record payment**")
                            payment_amt = st.number_input(
                                "Payment Amount (KES)",
                                min_value=0.01,
                                max_value=inv_to_manage.balance_due_minor / 100,
                                value=inv_to_manage.balance_due_minor / 100,
                                step=0.01, format="%.2f",
                            )
                            payment_method_sel = st.selectbox(
                                "Payment Method", ["cash", "m_pesa", "bank_transfer", "cheque", "card", "other"])
                            mpesa_ref = st.text_input("M-Pesa / reference code (optional)")
                            if st.form_submit_button(":material/check_circle: Record", width="stretch"):
                                ok = inv_mgr.record_payment(
                                    business_id=biz_id,
                                    invoice_id=inv_to_manage.invoice_id,
                                    amount_minor=int(round(payment_amt * 100)),
                                    payment_method=payment_method_sel,
                                    mpesa_reference=mpesa_ref.strip() or None,
                                    recorded_by=profile.get("phone") if profile else None,
                                )
                                if ok:
                                    st.success("Payment recorded!")
                                    st.rerun()
                                else:
                                    st.error("Payment not recorded: the invoice can't take this payment.")

    # ---- QUOTATIONS ----
    with manage_tab2:
        st.write("**All Quotations:**")

        all_quotes = inv_mgr.list_quotations(biz_id, limit=500)

        if not all_quotes:
            st.info("No quotations yet")
        else:
            st.dataframe(pd.DataFrame([
                {
                    "Quotation #": q.quotation_number,
                    "Customer": q.customer_name_token or "Unknown",
                    "Amount": f"KES {q.total_minor/100:,.2f}",
                    "Valid Until": q.valid_until_date[:10],
                    "Status": q.status.upper(),
                }
                for q in all_quotes
            ]), width="stretch", hide_index=True)

            st.divider()
            selected_quote_id = st.selectbox(
                "Select quotation to manage",
                [(q.quotation_id, q.quotation_number) for q in all_quotes],
                format_func=lambda x: x[1],
                key="quote_select"
            )

            if selected_quote_id:
                quote_to_manage = next(q for q in all_quotes if q.quotation_id == selected_quote_id[0])
                open_quote = quote_to_manage.status in ("draft", "sent", "accepted")

                col_q1, col_q2 = st.columns(2)
                if col_q1.button(":material/mail: Send to Customer", key="send_quote", width="stretch",
                                 disabled=quote_to_manage.status != "draft"):
                    inv_mgr.update_quotation_status(quote_to_manage.quotation_id, "sent")
                    st.success("Quotation marked as sent")
                    st.rerun()

                if col_q2.button(":material/check: Mark Accepted → Convert to Invoice", key="convert_quote",
                                 width="stretch", disabled=not open_quote):
                    invoice = inv_mgr.convert_quotation_to_invoice(quote_to_manage.quotation_id)
                    if invoice is None:
                        st.error("This quotation can't be converted (it was rejected, expired or already converted).")
                    else:
                        st.success(f"Quotation converted to Invoice: {invoice.invoice_number}")
                        st.rerun()
                if not open_quote:
                    st.caption(f"This quotation is {quote_to_manage.status.replace('_', ' ')}.")

# ============================================================================
# TAB 5: PAYMENTS & FOLLOW-UPS
# ============================================================================
with tab_payments:
    st.subheader("Payments & AI follow-ups")
    
    payments_tab1, payments_tab2 = st.tabs(["Recent Payments", "AI Follow-up Tasks"])
    
    # ---- RECENT PAYMENTS ----
    with payments_tab1:
        st.write("**Recent Payments:**")
        
        recent_payments = inv_mgr.get_recent_payments(biz_id, days=30, limit=50)
        
        if not recent_payments:
            st.info("No payments in the last 30 days")
        else:
            df_payments = pd.DataFrame([
                {
                    "Date": p["payment_date"][:10],
                    "Invoice #": p["invoice_number"],
                    "Amount (KES)": f"{p['amount_minor']/100:,.2f}",
                    "Method": p["payment_method"].upper(),
                    "Reference": p["reference_number"] or p["mpesa_reference"] or "—",
                }
                for p in recent_payments
            ])
            
            st.dataframe(df_payments, width="stretch", hide_index=True)
            
            # Summary
            total_paid = sum(p["amount_minor"] for p in recent_payments)
            st.metric("Total Payments (30d)", f"KES {total_paid/100:,.0f}")
    
    # ---- AI FOLLOW-UP TASKS ----
    with payments_tab2:
        st.write("**AI Follow-up Tasks:**")
        
        pending_tasks = ai_asst.get_pending_tasks(biz_id, limit=50)
        
        if not pending_tasks:
            st.success("No pending follow-up tasks")
            if st.button(":material/refresh: Generate New Follow-up Tasks"):
                result = ai_asst.generate_all_tasks(biz_id)
                st.success(f"Created {result['total_new_tasks']} follow-up tasks")
                st.rerun()
        else:
            st.write(f"**{len(pending_tasks)} pending tasks:**")
            
            for task in pending_tasks:
                with st.expander(f"{task.task_type.replace('_', ' ').title()} — {task.customer_name_token}"):
                    st.write(f"**Entity:** {task.entity_type.upper()} #{task.entity_id}")
                    st.write(f"**Suggested Action:** {task.ai_suggested_action}")
                    st.info(f"**Message:** {task.message_template}")
                    
                    col_done, col_skip = st.columns(2)
                    
                    if col_done.button(":material/check_circle: Done", key=f"complete_{task.task_id}"):
                        ai_asst.complete_task(
                            task.task_id,
                            "contacted_payment_promised",
                            profile.get("phone") if profile else None
                        )
                        st.success("Task marked done")
                        st.rerun()
                    
                    if col_skip.button(":material/skip_next: Skip", key=f"skip_{task.task_id}"):
                        ai_asst.skip_task(task.task_id)
                        st.success("Task skipped")
                        st.rerun()

st.divider()
st.caption("**Tip:** Use the POS Dashboard to quickly create sales, then convert them to invoices here for credit customers.")

# ============================================================================
# TAB 6: IMPORT CSV — products, customers, past sales
# ============================================================================
with tab_import:
    st.subheader("Import from CSV")
    st.caption("Load many products, customers or past sales at once. Every row is checked; rows with a "
               "problem are listed and skipped, the rest are saved. Importing the same file again is safe: "
               "products (by SKU) and customers (by name) are updated, and sales already imported are skipped.")

    IMPORTS = [
        ("products", "Products", csv_import.PRODUCT_TEMPLATE, csv_import.import_products,
         "Required: sku, name, cost_price, selling_price. vat_applicable is yes/no (default yes); "
         "stock_qty sets the stock level."),
        ("customers", "Customers", csv_import.CUSTOMER_TEMPLATE, csv_import.import_customers,
         "Required: name. Phone and email are checked and stored only as hashes."),
        ("sales", "Past sales", csv_import.SALE_TEMPLATE, csv_import.import_sales,
         "Required: sale_ref, sale_date, sku, quantity, payment_method (cash, m_pesa, card, cheque, credit). "
         "Rows with the same sale_ref are one sale. Blank unit_price uses the product price. "
         "Import products first: stock is reduced and a sale without enough stock is rejected."),
    ]
    for kind, label, template, importer, help_text in IMPORTS:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.markdown(f"**{label}**  \n{help_text}")
            c2.download_button(":material/download: Template", template, file_name=f"duka_{kind}_template.csv",
                               mime="text/csv", key=f"tpl_{kind}", width="stretch")
            upload = st.file_uploader(f"{label} CSV", type=["csv"], key=f"import_{kind}")
            if upload is not None and st.button(f":material/upload: Import {label.lower()}", key=f"do_import_{kind}",
                                                type="primary"):
                try:
                    report = importer(upload.getvalue(), biz_id)
                except csv_import.CSVImportError as e:
                    st.error(str(e))
                else:
                    (st.success if report.ok else st.warning)(report.summary())
                    if report.errors:
                        st.dataframe(pd.DataFrame(report.errors, columns=["Line", "Problem"]),
                                     hide_index=True, width="stretch")

    if customer_names:
        with st.expander(f"Your customers ({len(customer_names)})"):
            st.dataframe(pd.DataFrame({"Customer": customer_names}), hide_index=True, width="stretch")
