"""Business Setup — Register and configure your business."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.auth_ui import require_auth, activate_business
from auth.middleware import get_business_id, get_user_id

from core.business_setup import BusinessSetup
from app.expense_ui import render_add_form, render_expense_list

st.set_page_config(page_title="Business Setup — Duka Copilot", page_icon=":material/storefront:")
# ---- Authentication Gate ----
require_auth()


st.title("Business setup", icon=":material/storefront:")
st.caption("Register your business and customize financial tracking.")

setup = BusinessSetup()

SECTORS = ["grocery", "kiosk", "salon", "transport", "restaurant", "retail", "agri", "services", "other"]
COUNTRIES = {"KE": "Kenya", "TZ": "Tanzania", "UG": "Uganda"}
REGISTRATION_TYPES = ["informal", "sole_proprietor", "partnership", "company"]

# The business comes from the signed session, which login fills from the
# database, so a returning owner lands here already set up.
business_id = get_business_id()

if business_id:
    profile = setup.get_business_profile(business_id)
    if profile:
        st.success(f"Registered: **{profile.name_token}** ({profile.sector})")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Recurring Expenses",
        "Categories",
        ":material/flag: Financial goals",
        "Settings",
        ":material/shield_lock: Owner rules & PIN",
    ])

    # Tab 1: Recurring Expenses
    with tab1:
        st.subheader("Recurring expenses")
        st.caption("Add rent, salary, utilities and other regular payments. Enter when you last paid "
                   "and how often it repeats; Duka Copilot works out the next due date and counts down to it.")

        render_add_form(setup, business_id, prefix="bs_add")
        st.divider()
        render_expense_list(setup, business_id, prefix="bs_list")

    # Tab 2: Categories
    with tab2:
        st.subheader("Category configuration")
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
                        monthly_budget_minor=int(round(budget * 100)) if budget > 0 else None,
                        auto_categorize_keywords=keywords if keywords else None,
                    )
                    st.success("Saved")
                    st.rerun()

    # Tab 3: Financial Goals
    with tab3:
        st.subheader("Financial goals")
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
                    revenue_target=int(round(revenue_target * 100)),
                    margin_target=margin_target,
                    buffer_target=int(round(buffer_target * 100)),
                    personal_limit_pct=personal_limit,
                )
                st.success("Goals saved")
                st.rerun()

    # Tab 4: Settings
    with tab4:
        st.subheader("Business settings")
        st.caption("Your setup is saved. Change any of these details whenever you need to.")
        if profile:
            with st.form("edit_business_profile"):
                col1, col2 = st.columns(2)
                with col1:
                    new_name = st.text_input("Business Name", value=profile.name_token)
                    new_sector = st.selectbox(
                        "Business Type", SECTORS,
                        index=SECTORS.index(profile.sector) if profile.sector in SECTORS else len(SECTORS) - 1,
                        format_func=lambda x: x.title(),
                    )
                    new_registration = st.selectbox(
                        "Registration", REGISTRATION_TYPES,
                        index=REGISTRATION_TYPES.index(profile.registration_type)
                        if profile.registration_type in REGISTRATION_TYPES else 0,
                        format_func=lambda x: x.replace("_", " ").title(),
                    )
                with col2:
                    new_sub_sector = st.text_input("Sub-sector (optional)", value=profile.sub_sector or "")
                    country_codes = list(COUNTRIES)
                    new_country = st.selectbox(
                        "Country", country_codes,
                        index=country_codes.index(profile.country_code) if profile.country_code in COUNTRIES else 0,
                        format_func=lambda x: COUNTRIES.get(x, x),
                    )
                    new_employees = st.number_input(
                        "Number of employees", value=int(profile.employee_count), min_value=0, max_value=1000,
                    )

                st.caption(f"Currency: {profile.currency_code} · Timezone: {profile.timezone} · Status: {profile.status}")

                if st.form_submit_button(":material/save: Save changes"):
                    if not new_name.strip():
                        st.error("Business name can't be empty.")
                    else:
                        setup.update_business_profile(
                            business_id=business_id,
                            name=new_name.strip(),
                            sector=new_sector,
                            sub_sector=new_sub_sector.strip() or None,
                            country_code=new_country,
                            employee_count=int(new_employees),
                            registration_type=new_registration,
                        )
                        activate_business(business_id)  # refresh cached context with the new details
                        st.success("Business details updated")
                        st.rerun()

    # Tab 5: the owner's rules for the assistant (caps, payees, PIN, language)
    with tab5:
        from core.owner_settings import (
            OwnerPin, PinError, WEEKDAYS, add_payee, list_payees, load_settings,
            needs_pin, remove_payee, save_settings,
        )
        from auth.middleware import get_user_id as _uid

        pins = OwnerPin()
        rules = load_settings(pins.db_path, business_id)

        st.subheader("Owner PIN")
        st.caption(
            "Your Duka Copilot PIN approves what the assistant proposes and protects your caps and payees. "
            "It is stored only as a salted hash. Three wrong tries lock approvals for 15 minutes."
        )
        has_pin = pins.is_set(business_id)
        with st.form("owner_pin_form"):
            current_pin = st.text_input("Current PIN", type="password", max_chars=6) if has_pin else None
            col1, col2 = st.columns(2)
            new_pin = col1.text_input("New PIN (4-6 digits)", type="password", max_chars=6)
            confirm_pin = col2.text_input("Repeat new PIN", type="password", max_chars=6)
            if st.form_submit_button(":material/pin: " + ("Change PIN" if has_pin else "Set PIN")):
                if new_pin != confirm_pin:
                    st.error("The two PINs don't match.")
                else:
                    try:
                        pins.set_pin(business_id, new_pin, current_pin)
                        st.success("PIN saved")
                    except PinError as e:
                        st.error(str(e))

        st.divider()
        st.subheader("Limits and preferences")
        st.caption("The assistant reads these rules but can never change them. Changing a cap needs your PIN.")
        with st.form("owner_rules_form"):
            col1, col2, col3 = st.columns(3)
            per_txn = col1.number_input("Per-payment cap (KES)", min_value=1,
                                        value=rules.per_txn_cap_minor // 100, step=1000)
            daily = col2.number_input("Daily cap (KES)", min_value=1,
                                      value=rules.daily_cap_minor // 100, step=1000)
            loan_cap = col3.number_input("Loan cap (KES)", min_value=1,
                                         value=rules.loan_cap_minor // 100, step=5000)
            col4, col5, col6 = st.columns(3)
            buffer = col4.number_input("Safety buffer (KES)", min_value=0,
                                       value=rules.safety_buffer_minor // 100, step=500,
                                       help="Forecast alerts fire when the low estimate drops below this.")
            payday_options = [None] + list(range(7))
            payday = col5.selectbox(
                "Staff payday", payday_options,
                index=payday_options.index(rules.payday_weekday),
                format_func=lambda d: "No fixed payday" if d is None else WEEKDAYS[d],
                help="Evening transfers on this day are counted as wages, not family transfers.",
            )
            language = col6.selectbox("Assistant language", ["en", "sw"], index=["en", "sw"].index(rules.language),
                                      format_func=lambda x: {"en": "English", "sw": "Kiswahili"}[x])
            rules_pin = st.text_input("Your PIN (needed only when you change a cap)", type="password", max_chars=6)
            if st.form_submit_button(":material/save: Save rules"):
                from dataclasses import replace
                new_rules = replace(
                    rules, per_txn_cap_minor=int(per_txn) * 100, daily_cap_minor=int(daily) * 100,
                    loan_cap_minor=int(loan_cap) * 100, safety_buffer_minor=int(buffer) * 100,
                    payday_weekday=payday, language=language,
                )
                try:
                    changed = save_settings(pins.db_path, new_rules, user_id=_uid(), pin=rules_pin or None)
                    st.success("Rules saved" if changed else "Nothing changed.")
                    if changed:
                        st.rerun()
                except (ValueError, PinError) as e:
                    st.error(str(e))

        st.divider()
        st.subheader("Verified payees")
        st.caption(
            "The assistant can only propose payments to these names, spelled exactly. Look-alike names are refused."
        )
        payees = list_payees(pins.db_path, business_id)
        if payees:
            for p in payees:
                col1, col2 = st.columns([4, 1])
                col1.markdown(f"**{p['name']}** · payee #{p['payee_id']}")
                if col2.button("Remove", key=f"rm_payee_{p['payee_id']}"):
                    st.session_state["_remove_payee"] = p["payee_id"]
            if st.session_state.get("_remove_payee"):
                with st.form("remove_payee_form"):
                    rm_pin = st.text_input(f"PIN to remove payee #{st.session_state['_remove_payee']}",
                                           type="password", max_chars=6)
                    if st.form_submit_button("Confirm remove"):
                        try:
                            remove_payee(pins.db_path, business_id, st.session_state.pop("_remove_payee"), rm_pin)
                            st.rerun()
                        except PinError as e:
                            st.error(str(e))
        else:
            st.info("No verified payees yet.")
        with st.form("add_payee_form", clear_on_submit=True):
            col1, col2, col3 = st.columns([3, 2, 2], vertical_alignment="bottom")
            payee_name = col1.text_input("Payee name", placeholder="e.g. SOKO SUPPLIES")
            payee_kind = col2.selectbox("Type", ["supplier", "landlord", "utility", "employee", "lender", "other_business"],
                                        format_func=lambda x: x.replace("_", " ").title())
            payee_pin = col3.text_input("Your PIN", type="password", max_chars=6)
            if st.form_submit_button(":material/person_add: Add payee"):
                try:
                    add_payee(pins.db_path, business_id, payee_name, payee_pin, kind=payee_kind, user_id=_uid())
                    st.success(f"Added {payee_name.upper()}")
                    st.rerun()
                except (ValueError, PinError) as e:
                    st.error(str(e))

else:
    st.info("Let's set up your business profile to get started.")

    with st.form("business_registration"):
        col1, col2 = st.columns(2)

        with col1:
            business_name = st.text_input("Business Name", placeholder="e.g., Mama Jane's Grocery")
            sector = st.selectbox("Business Type", SECTORS, format_func=lambda x: x.title())

        with col2:
            sub_sector = st.text_input("Sub-sector (optional)", placeholder="e.g., organic grocery")
            country = st.selectbox("Country", list(COUNTRIES), format_func=lambda x: COUNTRIES.get(x, x))

        col3, col4 = st.columns(2)
        with col3:
            revenue_estimate = st.number_input(
                "Estimated monthly revenue (KES)", value=500000, min_value=0, step=50000,
            )
        with col4:
            employee_count = st.number_input("Number of employees", value=1, min_value=0, max_value=1000)

        if st.form_submit_button(":material/rocket_launch: Create business"):
            if not business_name.strip():
                st.error("Please enter your business name.")
                st.stop()
            biz_id = setup.register_business(
                name=business_name.strip(),
                sector=sector,
                sub_sector=sub_sector if sub_sector else None,
                country_code=country,
                revenue_estimate_minor=int(round(revenue_estimate * 100)),
                employee_count=employee_count,
                owner_user_id=get_user_id(),
            )

            # Saved to the database against this user, and the session now
            # carries the business, so setup never has to be repeated.
            activate_business(biz_id)
            st.session_state.business_name = business_name
            st.success(f"Business created: **{business_name}**")
            st.rerun()
