"""Business Setup — Register and configure your business."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth

from core.business_setup import BusinessSetup

st.set_page_config(page_title="Business Setup — Duka", page_icon=":material/storefront:")
# ---- Authentication Gate ----
require_auth()


st.title("Business Setup")
st.caption("Register your business and customize financial tracking.")

setup = BusinessSetup()

# Check if business already set up
business_id = st.session_state.get("business_id")

if business_id:
    profile = setup.get_business_profile(business_id)
    if profile:
        st.success(f"✓ Registered: **{profile.name_token}** ({profile.sector})")

    tab1, tab2, tab3, tab4 = st.tabs([
        "Recurring Expenses",
        "Categories",
        ":material/flag: Financial goals",
        "Settings",
    ])

    # Tab 1: Recurring Expenses
    with tab1:
        st.subheader("Recurring Expenses")
        st.caption("Add rent, salary, utilities, and other regular payments.")

        with st.form("add_recurring"):
            col1, col2 = st.columns(2)

            with col1:
                exp_type = st.selectbox("Type", [
                    "rent", "salary", "utilities", "insurance",
                    "supplier_credit", "loan_repayment", "tax",
                    "maintenance", "service_subscription", "other",
                ], format_func=lambda x: x.replace("_", " ").title())
                description = st.text_input("Description", placeholder="e.g., Monthly shop rent")

            with col2:
                amount = st.number_input("Amount (KES)", value=50000, min_value=0, step=1000)
                cadence = st.selectbox("Frequency", [
                    "daily", "weekly", "biweekly", "monthly", "quarterly", "annual",
                ], format_func=lambda x: x.title())

            day = st.number_input("Day of month (if monthly/quarterly)", value=1, min_value=1, max_value=31)
            is_variable = st.checkbox("Variable amount?")

            if st.form_submit_button(":material/add: Add Expense"):
                expense_id = setup.add_recurring_expense(
                    business_id=business_id,
                    expense_type=exp_type,
                    description=description,
                    amount_minor=int(amount * 100),
                    cadence=cadence,
                    day_of_month=day if cadence in ("monthly", "quarterly") else None,
                    is_variable=is_variable,
                )
                st.success(f"✓ Added: {description} (KES {amount:,.0f})")
                st.rerun()

        st.divider()

        expenses = setup.get_recurring_expenses(business_id)
        if expenses:
            st.write(f"**{len(expenses)} active recurring expenses**")
            for exp in expenses:
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                with col1:
                    st.write(f"**{exp['description']}**")
                with col2:
                    st.write(f"KES {exp['amount_minor']/100:,.0f}")
                with col3:
                    st.write(f"{exp['cadence']}")
                with col4:
                    st.write(f"Next: {exp['next_due'][:10] if exp['next_due'] else '—'}")
        else:
            st.info("No recurring expenses yet. Add your first one above.")

    # Tab 2: Categories
    with tab2:
        st.subheader("Category Configuration")
        st.caption("Customize how expenses are tracked for your business.")

        import sqlite3
        from core.config import config as cfg

        conn = sqlite3.connect(cfg.DB_PATH)
        conn.row_factory = sqlite3.Row
        categories = conn.execute(
            "SELECT category_id, code, name, kind FROM category WHERE kind IN ('cogs','opex','tax','personal') ORDER BY sort_order"
        ).fetchall()
        conn.close()

        configs = setup.get_category_configs(business_id)
        configured_ids = {c["global_category_id"]: c for c in configs}

        for cat in categories:
            cat_id = cat["category_id"]
            existing = configured_ids.get(cat_id, {})

            with st.expander(f"{cat['name']} ({cat['kind']})"):
                col1, col2 = st.columns(2)
                with col1:
                    display = st.text_input(
                        "Display name", value=existing.get("display_name", cat["name"]),
                        key=f"disp_{cat_id}"
                    )
                with col2:
                    budget = st.number_input(
                        "Monthly budget (KES)", value=existing.get("monthly_budget_minor", 0) // 100,
                        min_value=0, step=1000, key=f"budget_{cat_id}"
                    )
                keywords = st.text_input(
                    "Auto-categorize keywords (comma-separated)",
                    value=existing.get("auto_categorize_keywords", ""),
                    key=f"kw_{cat_id}"
                )
                if st.button("Save", key=f"save_{cat_id}"):
                    setup.configure_category(
                        business_id=business_id,
                        global_category_id=cat_id,
                        display_name=display if display != cat["name"] else None,
                        monthly_budget_minor=int(budget * 100) if budget > 0 else None,
                        auto_categorize_keywords=keywords if keywords else None,
                    )
                    st.success("✓ Saved")
                    st.rerun()

    # Tab 3: Financial Goals
    with tab3:
        st.subheader("Financial Goals")
        st.caption("Set targets for your business.")

        existing_goals = setup.get_financial_goals(business_id)
        goal_map = {g["goal_type"]: g for g in existing_goals}

        with st.form("goals_form"):
            col1, col2 = st.columns(2)
            with col1:
                revenue_target = st.number_input(
                    "Monthly revenue target (KES)",
                    value=goal_map.get("revenue_target", {}).get("target_value_minor", 500000) // 100,
                    min_value=0, step=50000,
                )
                margin_target = st.slider(
                    "Gross margin target (%)",
                    value=goal_map.get("margin_target", {}).get("target_value_minor", 30),
                    min_value=0, max_value=80,
                )
            with col2:
                buffer_target = st.number_input(
                    "Cash buffer target (KES)",
                    value=goal_map.get("cash_buffer", {}).get("target_value_minor", 200000) // 100,
                    min_value=0, step=10000,
                )
                personal_limit = st.slider(
                    "Personal withdrawal limit (% of revenue)",
                    value=goal_map.get("personal_limit", {}).get("target_value_minor", 25),
                    min_value=0, max_value=50,
                )

            if st.form_submit_button(":material/save: Save Goals"):
                setup.set_financial_goals(
                    business_id=business_id,
                    revenue_target=int(revenue_target * 100),
                    margin_target=margin_target,
                    buffer_target=int(buffer_target * 100),
                    personal_limit_pct=personal_limit,
                )
                st.success("✓ Goals saved")
                st.rerun()

    # Tab 4: Settings
    with tab4:
        st.subheader("Business Settings")
        if profile:
            st.write(f"**Name:** {profile.name_token}")
            st.write(f"**Sector:** {profile.sector}")
            st.write(f"**Country:** {profile.country_code}")
            st.write(f"**Currency:** {profile.currency_code}")
            st.write(f"**Timezone:** {profile.timezone}")
            st.write(f"**Employees:** {profile.employee_count}")
            st.write(f"**Status:** {profile.status}")

else:
    st.info("Let's set up your business profile to get started.")

    with st.form("business_registration"):
        col1, col2 = st.columns(2)

        with col1:
            business_name = st.text_input("Business Name", placeholder="e.g., Mama Jane's Grocery")
            sector = st.selectbox("Business Type", [
                "grocery", "kiosk", "salon", "transport",
                "restaurant", "retail", "agri", "services", "other",
            ], format_func=lambda x: x.title())

        with col2:
            sub_sector = st.text_input("Sub-sector (optional)", placeholder="e.g., organic grocery")
            country = st.selectbox("Country", ["KE", "TZ", "UG"], format_func=lambda x: {
                "KE": "Kenya", "TZ": "Tanzania", "UG": "Uganda",
            }.get(x, x))

        col3, col4 = st.columns(2)
        with col3:
            revenue_estimate = st.number_input(
                "Estimated monthly revenue (KES)", value=500000, min_value=0, step=50000,
            )
        with col4:
            employee_count = st.number_input("Number of employees", value=1, min_value=0, max_value=1000)

        if st.form_submit_button(":material/rocket_launch: Create business"):
            biz_id = setup.register_business(
                name=business_name,
                sector=sector,
                sub_sector=sub_sector if sub_sector else None,
                country_code=country,
                revenue_estimate_minor=int(revenue_estimate * 100),
                employee_count=employee_count,
            )

            st.session_state.business_id = biz_id
            st.session_state.business_name = business_name
            st.success(f"✓ Business created: **{business_name}**")
            st.rerun()
