"""Page 10: Inventory Management — Products, Stock, Reorder Alerts, Valuation."""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth, check_auth

from core.inventory_manager import InventoryManager, Product, InventoryTransaction
from core.pos_engine import POSEngine
from app.session_helpers import SessionManager
from auth.middleware import get_business_id

st.set_page_config(page_title="Inventory — Duka", page_icon=":material/inventory:", layout="wide")
# ---- Authentication Gate ----
require_auth()


SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = get_business_id()
if not biz_id:
    st.warning("Please register your business first in **Business Setup**.")
    st.stop()

inv_mgr = InventoryManager()
pos = POSEngine()

st.title("Inventory Management")
st.caption("Products, stock levels, reorder alerts, and valuation.")

# ---- Tabs ----
tab_products, tab_stock, tab_alerts, tab_valuation = st.tabs([
    "Products",
    "Stock Movements",
    "Reorder Alerts",
    "Valuation"
])

# ============================================================================
# TAB 1: PRODUCTS
# ============================================================================
with tab_products:
    st.subheader("Product Catalog")

    products = inv_mgr.list_products(biz_id, active_only=False, limit=500)

    col_view, col_add = st.columns([3, 2])

    with col_view:
        if not products:
            st.info("No products yet. Add your first product!")
        else:
            search = st.text_input(":material/search: Search by name or SKU", key="prod_search")
            filtered = products
            if search:
                s = search.lower()
                filtered = [p for p in products if s in p.name.lower() or s in p.sku.lower()]

            st.caption(f"{len(filtered)} product(s) shown")

            for p in filtered:
                status_icon = ":material/check_circle:" if p.is_active and not p.needs_reorder else ":material/warning:" if p.needs_reorder else ":material/cancel:"
                margin = p.compute_margin_pct()
                with st.expander(
                    f"{status_icon} **{p.name}** — KES {p.selling_price:,.2f} | Stock: {p.current_stock_qty} | Margin: {margin:.1f}%"
                ):
                    col1, col2 = st.columns(2)
                    col1.write(f"**SKU:** {p.sku}")
                    col1.write(f"**Category:** {p.category or '—'}")
                    col1.write(f"**Cost:** KES {p.cost_price:,.2f}")
                    col1.write(f"**Selling:** KES {p.selling_price:,.2f}")
                    col1.write(f"**Stock:** {p.current_stock_qty} (reorder at {p.reorder_level_qty})")
                    col2.write(f"**VAT:** {p.vat_rate_pct}% {'(applicable)' if p.vat_applicable else '(exempt)'}")
                    col2.write(f"**Barcode:** {p.barcode or '—'}")
                    col2.write(f"**Stock Value:** KES {p.stock_value_minor/100:,.2f}")
                    col2.write(f"**Margin:** {margin:.1f}%")
                    if p.last_restocked_at:
                        col2.write(f"**Last Restocked:** {p.last_restocked_at[:10]}")

                    # Quick actions
                    c_edit, c_toggle, c_restock = st.columns(3)
                    if c_edit.button(":material/edit: Edit", key=f"edit_{p.product_id}"):
                        st.session_state[f"editing_product_{p.product_id}"] = True
                    if c_toggle.button(
                        ":material/block: Deactivate" if p.is_active else ":material/play_circle: Activate",
                        key=f"toggle_{p.product_id}"
                    ):
                        inv_mgr.toggle_product_active(p.product_id)
                        st.rerun()
                    if c_restock.button(":material/download: Restock", key=f"rstk_{p.product_id}"):
                        st.session_state[f"restocking_{p.product_id}"] = True

    with col_add:
        st.subheader("Add / Edit Product")
        edit_id = None
        for p in products:
            if st.session_state.get(f"editing_product_{p.product_id}"):
                edit_id = p.product_id
                break

        edit_product = inv_mgr.get_product(edit_id) if edit_id else None

        with st.form("add_product_form", clear_on_submit=not edit_product):
            name = st.text_input("Product Name *", value=edit_product.name if edit_product else "")
            sku = st.text_input("SKU *", value=edit_product.sku if edit_product else "")
            category = st.text_input("Category", value=edit_product.category or "" if edit_product else "")
            description = st.text_area("Description", value=edit_product.description or "" if edit_product else "")

            c1, c2 = st.columns(2)
            cost = c1.number_input("Cost Price (KES) *", min_value=0.0, step=1.0,
                                   value=edit_product.cost_price if edit_product else 0.0)
            selling = c2.number_input("Selling Price (KES) *", min_value=0.0, step=1.0,
                                      value=edit_product.selling_price if edit_product else 0.0)

            c3, c4, c5 = st.columns(3)
            stock_qty = c3.number_input("Current Stock", min_value=0, step=1,
                                        value=edit_product.current_stock_qty if edit_product else 0)
            reorder_level = c4.number_input("Reorder Level", min_value=0, step=1,
                                            value=edit_product.reorder_level_qty if edit_product else 10)
            reorder_qty = c5.number_input("Reorder Qty", min_value=0, step=1,
                                          value=edit_product.reorder_qty if edit_product else 50)

            c6, c7 = st.columns(2)
            vat_applicable = c6.checkbox("VAT Applicable", value=edit_product.vat_applicable if edit_product else True)
            vat_rate = c7.number_input("VAT Rate %", min_value=0.0, max_value=100.0, step=0.5,
                                       value=edit_product.vat_rate_pct if edit_product else 16.0)

            barcode = st.text_input("Barcode (optional)", value=edit_product.barcode or "" if edit_product else "")

            label = f":material/edit: Update {edit_product.name}" if edit_product else "Add Product"
            submitted = st.form_submit_button(label, width="stretch", type="primary")

            if submitted:
                if not name or not sku:
                    st.error("Name and SKU are required.")
                else:
                    p = Product(
                        product_id=edit_product.product_id if edit_product else None,
                        business_id=biz_id,
                        sku=sku.strip(),
                        name=name.strip(),
                        description=description or None,
                        category=category.strip() or None,
                        cost_price_minor=int(round(cost * 100)),
                        selling_price_minor=int(round(selling * 100)),
                        vat_applicable=vat_applicable,
                        vat_rate_pct=vat_rate,
                        current_stock_qty=stock_qty,
                        reorder_level_qty=reorder_level,
                        reorder_qty=reorder_qty,
                        barcode=barcode.strip() or None,
                    )
                    if edit_product:
                        inv_mgr.update_product(p)
                        st.success(f"Updated {name}")
                    else:
                        pid = inv_mgr.create_product(p)
                        st.success(f"Created {name} (ID: {pid})")

                    # Clear editing state
                    if edit_id:
                        st.session_state.pop(f"editing_product_{edit_id}", None)
                    st.rerun()

# ============================================================================
# TAB 2: STOCK MOVEMENTS
# ============================================================================
with tab_stock:
    st.subheader("Stock Movements")

    movements = inv_mgr.get_stock_movement(biz_id, days=30)

    if not movements:
        st.info("No stock movements in the last 30 days.")
    else:
        col_f1, col_f2 = st.columns(2)
        txn_type_filter = col_f1.selectbox(
            "Filter by type",
            ["all", "purchase", "sale", "adjustment", "return", "damaged", "loss"],
            key="txn_filter"
        )
        days_filter = col_f2.slider("Days back", 7, 90, 30, 7, key="movement_days")

        if days_filter != 30:
            movements = inv_mgr.get_stock_movement(biz_id, days=days_filter)

        filtered_moves = movements if txn_type_filter == "all" else [
            m for m in movements if m.type == txn_type_filter
        ]

        st.caption(f"{len(filtered_moves)} movement(s)")

        type_icons = {
            "purchase": ":material/download:", "sale": ":material/shopping_cart:", "adjustment": ":material/build:",
            "return": ":material/undo:", "damaged": ":material/broken_image:", "loss": ":material/cancel:"
        }

        for m in filtered_moves[:50]:
            product = inv_mgr.get_product(m.product_id)
            pname = product.name if product else f"Product #{m.product_id}"
            icon = type_icons.get(m.type, ":material/inventory_2:")
            st.write(
                f"{icon} **{m.type.upper()}** — {pname} — "
                f"{m.quantity:+d} units — {m.created_at[:10]} — "
                f"*{m.notes or '—'}*"
            )

    # Quick Restock Form
    st.divider()
    st.subheader("Quick Restock")

    products_active = inv_mgr.list_products(biz_id, active_only=True, limit=500)

    # Check if we're restocking a specific product
    restock_pid = None
    for p in products_active:
        if st.session_state.get(f"restocking_{p.product_id}"):
            restock_pid = p.product_id
            break

    with st.form("restock_form", clear_on_submit=True):
        if restock_pid:
            product_opts = {f"{p.name} (Stock: {p.current_stock_qty})": p.product_id for p in products_active}
            default_idx = list(product_opts.values()).index(restock_pid) if restock_pid in product_opts.values() else 0
            selected = st.selectbox("Product", list(product_opts.keys()), index=default_idx)
        else:
            product_opts = {f"{p.name} (Stock: {p.current_stock_qty})": p.product_id for p in products_active}
            selected = st.selectbox("Product", list(product_opts.keys())) if product_opts else None

        qty = st.number_input("Quantity to add", min_value=1, step=1, value=1)
        notes = st.text_input("Notes (optional)", placeholder="e.g., supplier delivery")
        restock_submitted = st.form_submit_button(":material/download: Restock", width="stretch")

        if restock_submitted and selected:
            pid = product_opts[selected]
            success = inv_mgr.restock(
                product_id=pid,
                business_id=biz_id,
                quantity=qty,
                notes=notes or None,
                recorded_by=profile.get("phone", "system") if profile else "system",
            )
            if success:
                st.success(f"Added {qty} units")
                if restock_pid:
                    st.session_state.pop(f"restocking_{restock_pid}", None)
                st.rerun()
            else:
                st.error("Restock failed. Check product exists.")

# ============================================================================
# TAB 3: REORDER ALERTS
# ============================================================================
with tab_alerts:
    st.subheader("Reorder Alerts")

    alerts = inv_mgr.get_reorder_alerts(biz_id)

    if not alerts:
        st.success("All products are well-stocked! No reorder alerts.")
    else:
        st.warning(f"**{len(alerts)} product(s)** need reordering")

        for p in alerts:
            shortage = p.reorder_qty - p.current_stock_qty
            with st.container():
                col_a1, col_a2, col_a3 = st.columns([3, 2, 1])
                col_a1.write(f"**{p.name}** — {p.current_stock_qty} left (reorder at {p.reorder_level_qty})")
                col_a2.metric("Reorder Qty", p.reorder_qty)
                if col_a3.button(":material/download: Restock", key=f"alert_restock_{p.product_id}"):
                    st.session_state[f"restocking_{p.product_id}"] = True
                    st.rerun()

# ============================================================================
# TAB 4: VALUATION
# ============================================================================
with tab_valuation:
    st.subheader("Inventory Valuation")

    valuation = inv_mgr.get_inventory_valuation(biz_id)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Products", valuation["product_count"])
    k2.metric("Total Units", f"{valuation['total_units']:,}")
    k3.metric("Cost Value", f"KES {valuation['total_cost_value_minor']/100:,.2f}")
    k4.metric("Retail Value", f"KES {valuation['total_retail_value_minor']/100:,.2f}")

    potential_profit = valuation["total_retail_value_minor"] - valuation["total_cost_value_minor"]
    margin_pct = (potential_profit / valuation["total_retail_value_minor"] * 100) if valuation["total_retail_value_minor"] > 0 else 0
    st.metric("Potential Profit (if all sold)", f"KES {potential_profit/100:,.2f}", f"{margin_pct:.1f}% margin")

    st.divider()

    if valuation["by_category"]:
        st.subheader("By category")
        for cat, data in valuation["by_category"].items():
            cat_name = cat or "Uncategorized"
            st.write(
                f"**{cat_name}** — {data['count']} products, "
                f"{data['units']} units, "
                f"Cost: KES {data['cost_value_minor']/100:,.2f}"
            )
    else:
        st.info("No category data available. Add categories to your products.")

st.divider()
st.caption("**Tip:** Products flagged with a yellow dot need reordering. Use Restock to update stock levels after receiving new inventory.")
