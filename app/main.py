"""Duka Copilot — Streamlit entry point: page navigation and the shared sidebar.

Every page lives in app/app_pages/ and keeps its old URL (url_path), so
bookmarks such as /POS_Dashboard still work. Logged-out visitors see the
welcome page with no menu; each business page also checks login itself.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth_ui import render_logout_button, validate_and_refresh_session
from auth.middleware import get_business_id, get_user_id
from core.config import config

st.set_page_config(
    page_title="Duka Copilot — Micro-Business CFO",
    page_icon=":material/storefront:",
    layout="wide",
    initial_sidebar_state="expanded",
)

logged_in = validate_and_refresh_session()


def _page(file: str, title: str, icon: str, url: str, visibility: str = "visible") -> st.Page:
    return st.Page(f"app_pages/{file}", title=title, icon=icon, url_path=url, visibility=visibility)


home = st.Page("app_pages/home.py", title="Assistant", icon=":material/forum:",
               default=logged_in, url_path=None if logged_in else "assistant")
# Account pages stay reachable for redirects but are not in the menu once logged in.
account_visibility = "hidden" if logged_in else "visible"
welcome = st.Page("app_pages/welcome.py", title="Welcome", icon=":material/storefront:",
                  default=not logged_in, url_path=None if not logged_in else "welcome",
                  visibility=account_visibility)
login = _page("Login.py", "Log in", ":material/login:", "Login", account_visibility)
signup = _page("Sign_Up.py", "Sign up", ":material/person_add:", "Sign_Up", account_visibility)

sections = {
    "": [home],
    "Money in & out": [
        _page("1_Upload_Statement.py", "Statements", ":material/upload_file:", "Upload_Statement"),
        _page("2_Analytics.py", "Analytics", ":material/analytics:", "Analytics"),
        _page("7_Financial_Health.py", "Financial health", ":material/monitor_heart:", "Financial_Health"),
        _page("4_Party_Intelligence.py", "Customers & suppliers", ":material/groups:", "Party_Intelligence"),
    ],
    "Sell": [
        _page("8_POS_Dashboard.py", "Point of sale", ":material/point_of_sale:", "POS_Dashboard"),
        _page("9_Invoicing.py", "Invoices & quotes", ":material/receipt_long:", "Invoicing"),
        _page("10_Inventory.py", "Inventory", ":material/inventory_2:", "Inventory"),
        _page("11_Tax_Reports.py", "Tax reports", ":material/account_balance:", "Tax_Reports"),
    ],
    "Bills & payments": [
        _page("4_Expenses_Setup.py", "Recurring expenses", ":material/event_repeat:", "Expenses_Setup"),
        _page("5_Expense_Tracking.py", "Spending vs budget", ":material/donut_large:", "Expense_Tracking"),
        _page("12_Standing_Orders.py", "Standing orders", ":material/schedule_send:", "Standing_Orders"),
        _page("13_Approvals.py", "Approvals", ":material/verified_user:", "Approvals"),
    ],
    "Plan ahead": [
        _page("3_Cashflow_Forecast.py", "Cashflow forecast", ":material/trending_up:", "Cashflow_Forecast"),
        _page("5_Working_Capital.py", "Working capital", ":material/currency_exchange:", "Working_Capital"),
        _page("6_Spending_Advisor.py", "Spending advisor", ":material/lightbulb:", "Spending_Advisor"),
        _page("3_Financing.py", "Financing", ":material/savings:", "Financing"),
    ],
    "Settings": [
        _page("0_Business_Setup.py", "Business setup", ":material/storefront:", "Business_Setup"),
        _page("7_Audit_and_Compliance.py", "Audit & compliance", ":material/policy:", "Audit_and_Compliance"),
    ],
}
if logged_in:
    from auth.rbac import is_admin
    if is_admin(config.DB_PATH, get_user_id()):
        sections["Settings"].append(
            _page("14_Admin_Security.py", "Security (admin)", ":material/admin_panel_settings:", "Admin_Security"))
    sections["Account"] = [login, signup, welcome]
    page = st.navigation(sections, position="sidebar")
else:
    every_page = [welcome, login, signup] + [p for group in sections.values() for p in group]
    page = st.navigation(every_page, position="hidden")

# ---- shared sidebar (below the menu) ----
if logged_in:
    with st.sidebar:
        st.logo("https://img.icons8.com/color/96/shop.png", size="medium")
        from app.session_helpers import SessionManager
        profile = SessionManager.get_profile()
        if profile:
            demo = profile.get("source") != "ledger"
            with st.container(horizontal=True, gap="small"):
                st.badge(profile.get("name", "Your business"), icon=":material/storefront:", color="primary")
                if demo:
                    st.badge("Demo data", icon=":material/science:", color="orange")
        elif get_business_id():
            st.caption("No statement saved yet.")

        business_id = get_business_id()
        if business_id:
            try:
                from core.standing_orders import StandingOrderService
                due = [p for p in StandingOrderService().open_payments(business_id)
                       if p["status"] in ("pending", "notified", "failed")]
            except Exception:
                due = []
            try:
                from core.approvals import ApprovalService
                waiting = ApprovalService().list_actions(business_id, ["PENDING_APPROVAL"])
            except Exception:
                waiting = []
            if due:
                urgent = sum(1 for p in due if p["priority_band"] in ("critical", "high"))
                st.page_link(sections["Bills & payments"][2],
                             label=f"{len(due)} payment(s) to authorize" + (f" · {urgent} urgent" if urgent else ""),
                             icon=":material/notifications_active:")
            if waiting:
                st.page_link(sections["Bills & payments"][3], label=f"{len(waiting)} request(s) need your PIN",
                             icon=":material/verified_user:")
    render_logout_button()

page.run()
