"""Page 9: Invoice & Quotation Management — Create, track, manage, and follow up."""
import streamlit as st
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.invoice_manager import InvoiceManager, Invoice, Quotation, InvoiceLineItem, QuotationLineItem
from core.inventory_manager import InventoryManager
from core.pos_engine import POSEngine
from core.ai_sales_assistant import AISalesAssistant
from app.session_helpers import SessionManager

st.set_page_config(page_title="Invoicing — Duka", page_icon=":material/description:", layout="wide")

# ---- Session & Auth ----
SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = profile.get("business_id", 1) if profile else 1
biz_name = profile.get("name", "Your Business") if profile else "Your Business"

# ---- Initialize Managers ----
inv_mgr = InvoiceManager()  # Uses default db_path="data/duka.db"
inv_prod_mgr = InventoryManager()
pos = POSEngine()
ai_asst = AISalesAssistant()

st.title("Invoicing & Quotations")
st.caption(f"Manage invoices, quotations, and customer billing for **{biz_name}**")

# ---- Navigation Tabs ----
tab_overview, tab_new_invoice, tab_new_quotation, tab_manage, tab_payments = st.tabs([
    "Overview",
    "Create Invoice",
    ":material/edit_note: Create quotation",
    ":material/search: Manage",
    "Payments & Follow-Ups"
])

# ============================================================================
# TAB 1: OVERVIEW — Dashboard
# ============================================================================
with tab_overview:
    st.subheader("Invoicing Dashboard")
    
    # Fetch summary data
    outstanding_invoices = inv_mgr.get_outstanding_invoices(biz_id)
    all_invoices = inv_mgr.list_invoices(biz_id, limit=100)
    pending_quotations = inv_mgr.list_quotations(biz_id, status="sent")
    
    # Calculations
    total_outstanding = sum(inv.balance_due_minor for inv in outstanding_invoices)
    total_overdue = sum(
        inv.balance_due_minor 
        for inv in outstanding_invoices 
        if inv.payment_status == "overdue"
    )
    
    # KPIs
    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric(
        "Total Invoices",
        len(all_invoices),
        help="Total invoices issued this period"
    )
    kpi2.metric(
        "Outstanding",
        f"KES {total_outstanding/100:,.0f}",
        f"{len(outstanding_invoices)} invoices",
        help="Total amount still owed by customers"
    )
    kpi3.metric(
        "Overdue",
        f"KES {total_overdue/100:,.0f}",
        delta_color="inverse",
        help="Past due date"
    )
    kpi4.metric(
        "Pending Quotations",
        len(pending_quotations),
        help="Quotations waiting for customer decision"
    )
    
    # Get last 30 days data
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
    recent_invoices = [inv for inv in all_invoices if inv.created_at >= thirty_days_ago]
    total_30d_revenue = sum(inv.total_amount_minor for inv in recent_invoices)
    kpi5.metric(
        "Revenue (30d)",
        f"KES {total_30d_revenue/100:,.0f}",
        f"{len(recent_invoices)} invoices"
    )
    
    st.divider()
    
    # ---- Outstanding Invoices List ----
    st.subheader("Outstanding Invoices (Sorted by Due Date)")
    
    if not outstanding_invoices:
        st.success("All invoices paid! No outstanding balance.")
    else:
        # Sort by due date (overdue first)
        sorted_invoices = sorted(
            outstanding_invoices,
            key=lambda x: (x.due_date if x.payment_status != "overdue" else "0000-00-00")
        )
        
        df_outstanding = pd.DataFrame([
            {
                "Invoice #": inv.invoice_number,
                "Customer": inv.customer_name_token or "Unknown",
                "Amount Due (KES)": f"{inv.balance_due_minor/100:,.2f}",
                "Due Date": inv.due_date,
                "Status": inv.payment_status.upper(),
                "Days Outstanding": (datetime.utcnow().date() - datetime.fromisoformat(inv.due_date).date()).days,
            }
            for inv in sorted_invoices
        ])
        
        # Color code by status
        def highlight_status(row):
            if row["Status"] == "OVERDUE":
                return ["background-color: #FFE5E5"] * len(row)
            elif row["Status"] == "PARTIAL":
                return ["background-color: #FFF8DC"] * len(row)
            return [""] * len(row)
        
        st.dataframe(
            df_outstanding.style.apply(highlight_status, axis=1),
            width="stretch"
        )

# ============================================================================
# TAB 2: CREATE INVOICE
# ============================================================================
with tab_new_invoice:
    st.subheader("Create New Invoice")
    
    with st.form("create_invoice_form"):
        col_cust, col_date, col_due = st.columns(3)
        
        with col_cust:
            customer_name = st.text_input(
                "Customer Name / Business",
                placeholder="John's Retail Store",
                help="Name of the customer/business being invoiced"
            )
        
        with col_date:
            invoice_date = st.date_input(
                "Invoice Date",
                value=datetime.utcnow().date(),
                help="Date invoice is issued"
            )
        
        with col_due:
            due_days = st.number_input(
                "Payment Terms (days)",
                value=30,
                min_value=0,
                max_value=365,
                help="Days customer has to pay"
            )
            due_date = invoice_date + timedelta(days=due_days)
        
        st.divider()
        
        # ---- Line Items ----
        st.write("**Line Items:**")
        
        if "invoice_items" not in st.session_state:
            st.session_state.invoice_items = []
        
        # Display existing items
        if st.session_state.invoice_items:
            st.write("Current items:")
            for idx, item in enumerate(st.session_state.invoice_items):
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 0.3])
                with col1:
                    st.caption(item["description"])
                with col2:
                    st.caption(f"Qty: {item['quantity']}")
                with col3:
                    st.caption(f"KES {item['unit_price_minor']/100:,.0f}")
                with col4:
                    st.caption(f"KES {item['line_total_minor']/100:,.0f}")
                with col5:
                    if st.button(":material/close:", key=f"remove_{idx}", width="stretch"):
                        st.session_state.invoice_items.pop(idx)
                        st.rerun()
        
        st.divider()
        
        # ---- Add New Line Item ----
        st.write("**Add New Item:**")
        col_desc, col_qty, col_price = st.columns([2, 1, 1])
        
        with col_desc:
            # Option 1: Select from inventory
            products = inv_prod_mgr.list_products(biz_id, active_only=True)
            product_map = {f"{p.name} (SKU: {p.sku})": p for p in products}
            selected_product = st.selectbox(
                "Select Product",
                list(product_map.keys()),
                key="product_select",
                label_visibility="collapsed"
            )
            
            # If product selected, pre-fill price
            if selected_product:
                prod = product_map[selected_product]
                description = prod.name
                default_price = prod.selling_price_minor
                vat_applicable = prod.vat_applicable
                vat_rate = 16.0  # Default Kenya VAT
            else:
                description = st.text_input(
                    "Item Description",
                    placeholder="e.g., Consulting Services",
                    key="item_desc_freeform"
                )
                default_price = 0
                vat_applicable = True
                vat_rate = 16.0
        
        with col_qty:
            item_qty = st.number_input(
                "Qty",
                value=1,
                min_value=1,
                key="item_qty"
            )
        
        with col_price:
            item_price = st.number_input(
                "Unit Price (KES)",
                value=default_price/100 if default_price else 0.0,
                min_value=0.0,
                step=0.01,
                key="item_price"
            )
        
        # VAT info
        col_vat, col_add = st.columns([2, 1])
        with col_vat:
            apply_vat = st.checkbox("Apply VAT (16%)", value=True)
        
        # Add button
        if col_add.form_submit_button(":material/add: Add Item", width="stretch"):
            if not description:
                st.error("Please enter item description")
            elif item_qty <= 0 or item_price <= 0:
                st.error("Quantity and price must be greater than 0")
            else:
                item_price_minor = int(item_price * 100)
                line_subtotal = item_price_minor * item_qty
                
                # Calculate VAT
                if apply_vat:
                    vat_amount = int(line_subtotal * vat_rate / 100)
                    line_total = line_subtotal + vat_amount
                else:
                    vat_amount = 0
                    line_total = line_subtotal
                
                st.session_state.invoice_items.append({
                    "description": description,
                    "quantity": item_qty,
                    "unit_price_minor": item_price_minor,
                    "line_subtotal_minor": line_subtotal,
                    "vat_applicable": apply_vat,
                    "vat_rate_pct": vat_rate if apply_vat else 0,
                    "vat_amount_minor": vat_amount,
                    "line_total_minor": line_total,
                })
                st.rerun()
        
        st.divider()
        
        # ---- Invoice Totals ----
        if st.session_state.invoice_items:
            subtotal = sum(item["line_subtotal_minor"] for item in st.session_state.invoice_items)
            vat_total = sum(item.get("vat_amount_minor", 0) for item in st.session_state.invoice_items)
            total = subtotal + vat_total
            
            col_tot1, col_tot2, col_tot3 = st.columns(3)
            col_tot1.metric("Subtotal", f"KES {subtotal/100:,.2f}")
            col_tot2.metric("VAT (16%)", f"KES {vat_total/100:,.2f}")
            col_tot3.metric("Total", f"KES {total/100:,.2f}")
            
            st.divider()
            
            # ---- Notes ----
            notes = st.text_area(
                "Invoice Notes (optional)",
                placeholder="Payment terms, bank details, thank you note, etc.",
                height=3
            )
            
            # ---- Submit ----
            col_action1, col_action2 = st.columns(2)
            
            with col_action1:
                if st.form_submit_button(":material/save: Save as Draft", width="stretch"):
                    # Convert session line items to InvoiceLineItem objects
                    line_items = [
                        InvoiceLineItem(
                            description=item["description"],
                            quantity=item["quantity"],
                            unit_price_minor=item["unit_price_minor"],
                            line_subtotal_minor=item["line_subtotal_minor"],
                            vat_applicable=item.get("vat_applicable", True),
                            vat_rate_pct=item.get("vat_rate_pct", 16.0),
                            vat_amount_minor=item.get("vat_amount_minor", 0),
                            line_total_minor=item.get("line_total_minor", item["line_subtotal_minor"]),
                        )
                        for item in st.session_state.invoice_items
                    ]
                    
                    # Create invoice in draft status
                    invoice = inv_mgr.create_invoice(
                        business_id=biz_id,
                        customer_id=0,  # Will use customer_name_token instead
                        line_items=line_items,
                        customer_name_token=customer_name,
                        due_days=due_days,
                        notes=notes,
                        status="draft",
                        created_by=profile.get("phone", "pos_user") if profile else "pos_user",
                    )
                    st.success(f"Invoice saved as draft: {invoice.invoice_number}")
                    st.session_state.invoice_items = []
                    st.rerun()
            
            with col_action2:
                if st.form_submit_button(":material/send: Create & Send", width="stretch", type="primary"):
                    # Convert session line items to InvoiceLineItem objects
                    line_items = [
                        InvoiceLineItem(
                            description=item["description"],
                            quantity=item["quantity"],
                            unit_price_minor=item["unit_price_minor"],
                            line_subtotal_minor=item["line_subtotal_minor"],
                            vat_applicable=item.get("vat_applicable", True),
                            vat_rate_pct=item.get("vat_rate_pct", 16.0),
                            vat_amount_minor=item.get("vat_amount_minor", 0),
                            line_total_minor=item.get("line_total_minor", item["line_subtotal_minor"]),
                        )
                        for item in st.session_state.invoice_items
                    ]
                    
                    # Create invoice and mark as sent
                    invoice = inv_mgr.create_invoice(
                        business_id=biz_id,
                        customer_id=0,  # Will use customer_name_token instead
                        line_items=line_items,
                        customer_name_token=customer_name,
                        due_days=due_days,
                        notes=notes,
                        status="sent",
                        created_by=profile.get("phone", "pos_user") if profile else "pos_user",
                    )
                    st.success(f"Invoice created and marked as sent: {invoice.invoice_number}")
                    st.session_state.invoice_items = []
                    st.rerun()
        else:
            st.info("Add line items to create invoice")

# ============================================================================
# TAB 3: CREATE QUOTATION
# ============================================================================
with tab_new_quotation:
    st.subheader("Create New Quotation")
    st.caption("Create an estimate/quotation for a customer. Convert to invoice when accepted.")
    
    with st.form("create_quotation_form"):
        col_cust, col_date, col_valid = st.columns(3)
        
        with col_cust:
            quote_customer = st.text_input(
                "Customer Name",
                placeholder="ABC Trading Ltd",
                help="Customer requesting the quotation"
            )
        
        with col_date:
            quote_date = st.date_input(
                "Quotation Date",
                value=datetime.utcnow().date()
            )
        
        with col_valid:
            valid_days = st.number_input(
                "Valid for (days)",
                value=30,
                min_value=1,
                max_value=365,
                help="How long the quotation is valid"
            )
            valid_until = quote_date + timedelta(days=valid_days)
        
        st.divider()
        
        # ---- Quotation Line Items ----
        st.write("**Quotation Items:**")
        
        if "quotation_items" not in st.session_state:
            st.session_state.quotation_items = []
        
        # Display existing items
        if st.session_state.quotation_items:
            st.write("Current items:")
            for idx, item in enumerate(st.session_state.quotation_items):
                col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 0.3])
                with col1:
                    st.caption(item["description"])
                with col2:
                    st.caption(f"Qty: {item['quantity']}")
                with col3:
                    st.caption(f"KES {item['unit_price_minor']/100:,.0f}")
                with col4:
                    st.caption(f"KES {item['line_total_minor']/100:,.0f}")
                with col5:
                    if st.button(":material/close:", key=f"remove_quote_{idx}", width="stretch"):
                        st.session_state.quotation_items.pop(idx)
                        st.rerun()
        
        st.divider()
        
        # ---- Add Item ----
        st.write("**Add Item:**")
        col_desc_q, col_qty_q, col_price_q = st.columns([2, 1, 1])
        
        with col_desc_q:
            item_desc_q = st.text_input(
                "Item Description",
                placeholder="e.g., Supply of goods, Services, etc.",
                key="quote_item_desc"
            )
        
        with col_qty_q:
            item_qty_q = st.number_input(
                "Qty",
                value=1,
                min_value=1,
                key="quote_item_qty"
            )
        
        with col_price_q:
            item_price_q = st.number_input(
                "Unit Price (KES)",
                value=0.0,
                min_value=0.0,
                step=0.01,
                key="quote_item_price"
            )
        
        col_vat_q, col_add_q = st.columns([2, 1])
        with col_vat_q:
            apply_vat_q = st.checkbox("Apply VAT", value=True, key="quote_vat")
        
        if col_add_q.form_submit_button(":material/add: Add Item", width="stretch"):
            if not item_desc_q:
                st.error("Please enter item description")
            else:
                item_price_minor_q = int(item_price_q * 100)
                line_subtotal_q = item_price_minor_q * item_qty_q
                
                if apply_vat_q:
                    vat_amount_q = int(line_subtotal_q * 16 / 100)
                    line_total_q = line_subtotal_q + vat_amount_q
                else:
                    vat_amount_q = 0
                    line_total_q = line_subtotal_q
                
                st.session_state.quotation_items.append({
                    "description": item_desc_q,
                    "quantity": item_qty_q,
                    "unit_price_minor": item_price_minor_q,
                    "line_subtotal_minor": line_subtotal_q,
                    "vat_applicable": apply_vat_q,
                    "vat_rate_pct": 16.0 if apply_vat_q else 0,
                    "vat_amount_minor": vat_amount_q,
                    "line_total_minor": line_total_q,
                })
                st.rerun()
        
        st.divider()
        
        # ---- Quotation Totals ----
        if st.session_state.quotation_items:
            subtotal_q = sum(item["line_subtotal_minor"] for item in st.session_state.quotation_items)
            vat_total_q = sum(item.get("vat_amount_minor", 0) for item in st.session_state.quotation_items)
            total_q = subtotal_q + vat_total_q
            
            col_tot1_q, col_tot2_q, col_tot3_q = st.columns(3)
            col_tot1_q.metric("Subtotal", f"KES {subtotal_q/100:,.2f}")
            col_tot2_q.metric("VAT (16%)", f"KES {vat_total_q/100:,.2f}")
            col_tot3_q.metric("Total", f"KES {total_q/100:,.2f}")
            
            st.divider()
            
            # ---- Quotation Terms ----
            terms = st.text_area(
                "Payment Terms & Conditions (optional)",
                placeholder="50% upfront, balance on delivery. Valid for 30 days.",
                height=3
            )
            
            # ---- Submit ----
            if st.form_submit_button(":material/upload: Create Quotation", type="primary", width="stretch"):
                # Convert session line items to QuotationLineItem objects
                line_items_q = [
                    QuotationLineItem(
                        description=item["description"],
                        quantity=item["quantity"],
                        unit_price_minor=item["unit_price_minor"],
                        line_subtotal_minor=item["line_subtotal_minor"],
                        vat_applicable=item.get("vat_applicable", True),
                        vat_rate_pct=item.get("vat_rate_pct", 16.0),
                        vat_amount_minor=item.get("vat_amount_minor", 0),
                        line_total_minor=item.get("line_total_minor", item["line_subtotal_minor"]),
                    )
                    for item in st.session_state.quotation_items
                ]
                
                quotation = inv_mgr.create_quotation(
                    business_id=biz_id,
                    customer_id=0,  # Will use customer_name_token instead
                    line_items=line_items_q,
                    customer_name_token=quote_customer,
                    valid_days=valid_days,
                    terms=terms,
                    created_by=profile.get("phone", "pos_user") if profile else "pos_user",
                )
                st.success(f"Quotation created: {quotation.quotation_number}")
                st.session_state.quotation_items = []
                st.rerun()
        else:
            st.info("Add line items to create quotation")

# ============================================================================
# TAB 4: MANAGE INVOICES & QUOTATIONS
# ============================================================================
with tab_manage:
    st.subheader("Manage Invoices & Quotations")
    
    manage_tab1, manage_tab2 = st.tabs(["Invoices", "Quotations"])
    
    # ---- INVOICES ----
    with manage_tab1:
        st.write("**All Invoices:**")
        
        # Filters
        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            status_filter = st.multiselect(
                "Filter by Status",
                ["draft", "sent", "partial", "paid", "overdue", "cancelled"],
                default=["sent", "partial", "overdue"]
            )
        with col_filter2:
            search_invoice = st.text_input("Search by Invoice # or Customer")
        
        # Get invoices
        all_invs = inv_mgr.list_invoices(biz_id, limit=500)
        filtered_invs = [
            inv for inv in all_invs
            if (not status_filter or inv.payment_status in status_filter)
            and (not search_invoice or search_invoice.lower() in inv.invoice_number.lower() or
                 (inv.customer_name_token and search_invoice.lower() in inv.customer_name_token.lower()))
        ]
        
        if not filtered_invs:
            st.info("No invoices matching filters")
        else:
            # Display table
            df_invs = pd.DataFrame([
                {
                    "Invoice #": inv.invoice_number,
                    "Customer": inv.customer_name_token or "Unknown",
                    "Amount": f"KES {inv.total_amount_minor/100:,.2f}",
                    "Paid": f"KES {inv.amount_paid_minor/100:,.2f}",
                    "Due": f"KES {inv.balance_due_minor/100:,.2f}",
                    "Status": inv.payment_status.upper(),
                    "Due Date": inv.due_date,
                    "ID": inv.invoice_id,
                }
                for inv in filtered_invs
            ])
            
            st.dataframe(df_invs, width="stretch", hide_index=True)
            
            # ---- Actions on Selected Invoice ----
            st.divider()
            selected_inv_id = st.selectbox(
                "Select invoice to manage",
                [(inv.invoice_id, inv.invoice_number) for inv in filtered_invs],
                format_func=lambda x: x[1]
            )
            
            if selected_inv_id:
                inv_to_manage = next(inv for inv in filtered_invs if inv.invoice_id == selected_inv_id[0])
                
                col_act1, col_act2, col_act3 = st.columns(3)
                
                # View details
                if col_act1.button(":material/visibility: View Details", width="stretch"):
                    st.info(f"""
                    **Invoice:** {inv_to_manage.invoice_number}
                    **Customer:** {inv_to_manage.customer_name_token}
                    **Amount:** KES {inv_to_manage.total_amount_minor/100:,.2f}
                    **Due Date:** {inv_to_manage.due_date}
                    **Status:** {inv_to_manage.payment_status}
                    **Balance Due:** KES {inv_to_manage.balance_due_minor/100:,.2f}
                    """)
                
                # Record payment
                if col_act2.button(":material/credit_card: Record Payment", width="stretch"):
                    with st.form(f"payment_form_{inv_to_manage.invoice_id}"):
                        payment_amt = st.number_input(
                            "Payment Amount (KES)",
                            min_value=0.0,
                            max_value=float(inv_to_manage.balance_due_minor / 100),
                            value=float(inv_to_manage.balance_due_minor / 100),
                            step=0.01
                        )
                        payment_method_sel = st.selectbox(
                            "Payment Method",
                            ["cash", "m_pesa", "bank_transfer", "cheque", "other"]
                        )
                        if st.form_submit_button(":material/check_circle: Record", width="stretch"):
                            inv_mgr.record_payment(
                                inv_to_manage.invoice_id,
                                int(payment_amt * 100),
                                payment_method_sel
                            )
                            st.success("Payment recorded!")
                            st.rerun()
                
                # Send reminder
                if col_act3.button(":material/mail: Send Reminder", width="stretch"):
                    # Generate reminder tasks for this specific invoice
                    # by calling generate_payment_reminders
                    tasks = ai_asst.generate_payment_reminders(biz_id)
                    if tasks:
                        st.success("Follow-up task created. Check AI Follow-Ups tab.")
                    else:
                        st.info("Follow-up task already pending or invoice already paid.")
    
    # ---- QUOTATIONS ----
    with manage_tab2:
        st.write("**All Quotations:**")
        
        all_quotes = inv_mgr.list_quotations(biz_id, limit=500)
        
        if not all_quotes:
            st.info("No quotations yet")
        else:
            df_quotes = pd.DataFrame([
                {
                    "Quotation #": q.quotation_number,
                    "Customer": q.customer_name_token or "Unknown",
                    "Amount": f"KES {q.total_minor/100:,.2f}",
                    "Valid Until": q.valid_until_date,
                    "Status": q.status.upper(),
                    "ID": q.quotation_id,
                }
                for q in all_quotes
            ])
            
            st.dataframe(df_quotes, width="stretch", hide_index=True)
            
            # ---- Quotation Actions ----
            st.divider()
            selected_quote_id = st.selectbox(
                "Select quotation to manage",
                [(q.quotation_id, q.quotation_number) for q in all_quotes],
                format_func=lambda x: x[1],
                key="quote_select"
            )
            
            if selected_quote_id:
                quote_to_manage = next(q for q in all_quotes if q.quotation_id == selected_quote_id[0])
                
                col_q1, col_q2, col_q3 = st.columns(3)
                
                if col_q1.button(":material/visibility: View", key="view_quote", width="stretch"):
                    st.info(f"""
                    **Quotation:** {quote_to_manage.quotation_number}
                    **Customer:** {quote_to_manage.customer_name_token}
                    **Total:** KES {quote_to_manage.total_minor/100:,.2f}
                    **Valid Until:** {quote_to_manage.valid_until_date}
                    **Status:** {quote_to_manage.status}
                    """)
                
                if col_q2.button(":material/mail: Send to Customer", key="send_quote", width="stretch"):
                    inv_mgr.update_quotation_status(quote_to_manage.quotation_id, "sent")
                    st.success("Quotation marked as sent")
                    st.rerun()
                
                if col_q3.button(":material/check: Mark Accepted → Convert to Invoice", key="convert_quote", width="stretch"):
                    # Convert quotation to invoice
                    invoice = inv_mgr.convert_quotation_to_invoice(quote_to_manage.quotation_id)
                    st.success(f"Quotation converted to Invoice: {invoice.invoice_number}")
                    st.rerun()

# ============================================================================
# TAB 5: PAYMENTS & FOLLOW-UPS
# ============================================================================
with tab_payments:
    st.subheader("Payments & AI Follow-Ups")
    
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
                    "Invoice #": p.get("invoice_number", "N/A"),
                    "Amount (KES)": f"{p['amount_minor']/100:,.2f}",
                    "Method": p["payment_method"].upper(),
                    "Reference": p.get("reference_number", "—"),
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
