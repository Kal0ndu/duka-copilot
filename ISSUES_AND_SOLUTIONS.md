# Duka Platform: Critical Issues & Solutions

**Created:** October 18, 2026  
**Status:** Action Items Detailed  
**Priority:** High

---

## Executive Summary

This document outlines 5 critical issues affecting the Duka platform and provides step-by-step solutions to resolve them. Each issue has a root cause analysis, current state assessment, and implementation roadmap.

---

## Issue 1: LLM Context Not Reaching the LLM

### Problem Statement
The LLM orchestrator is not receiving user business context, limiting its ability to make informed decisions and personalized responses.

### Root Cause
- **Current State:** `auth/user_context.py` computes and caches business context, but it's not injected into LLM prompts during orchestration
- **Gap:** No middleware to attach cached context to outbound LLM API calls
- **Impact:** LLM operates without business data (revenue, expenses, obligations, forecast, risks)

### Current Implementation
```python
# auth/user_context.py computes context:
- get() → Returns cached business metrics (30-min TTL)
- _compute() → Aggregates 30-day summary, health, obligations, forecast, risks
- Business data ready but NOT injected into LLM calls
```

### Solution Steps

#### 1. **Create LLM Request Wrapper** (NEW FILE)
Create `agent/llm_orchestrator.py` to inject context into every LLM call:

```python
# agent/llm_orchestrator.py
from auth.user_context import UserContext
from typing import Dict, Any, Optional

class LLMOrchestrator:
    """Wraps LLM requests to inject cached business context."""
    
    def __init__(self, user_id: int, business_id: int, db_path: str):
        self.user_id = user_id
        self.business_id = business_id
        self.context_mgr = UserContext(user_id, business_id, db_path)
    
    def build_system_prompt(self) -> str:
        """Build a system prompt with injected business context."""
        ctx = self.context_mgr.get()
        
        system = f"""You are an AI copilot for {ctx['business_summary']['name']}.
        
## Business Overview
- **Sector:** {ctx['business_summary'].get('sector', 'Unknown')}
- **Last Updated:** {ctx['generated_at']}

## Financial Summary (Last 30 Days)
- Revenue: KES {ctx['summary']['revenue_kes']:,.2f}
- Expenses: KES {ctx['summary']['expenses_kes']:,.2f}
- Net: KES {ctx['summary']['net_kes']:,.2f}
- Margin: {ctx['summary']['margin_pct']}%
- Current Balance: KES {ctx['summary']['opening_balance_kes']:,.2f}

## Health Status
- Status: {ctx['health']['status'].upper()}
- Days of Cash: {ctx['health']['days_of_cash']}
- Burn Rate: KES {ctx['health']['burn_rate_daily_kes']:,.2f}/day

## Upcoming Obligations (Next 14 Days)
"""
        for obl in ctx['obligations'][:5]:
            system += f"- {obl['label']}: KES {obl['amount_kes']:,.2f} due {obl['due_date']}\n"
        
        system += f"""
## Forecast (Next 30 Days)
- P10 End Balance: KES {ctx['forecast']['p10_end_kes']:,.2f}
- P50 End Balance: KES {ctx['forecast']['p50_end_kes']:,.2f}
- P90 End Balance: KES {ctx['forecast']['p90_end_kes']:,.2f}
- Shortfall Risk: {ctx['forecast']['shortfall_risk']}

## Active Risks
"""
        for risk in ctx['risks']:
            system += f"⚠️ {risk}\n"
        
        system += """
Use this context to provide business-specific, data-driven recommendations.
Always reference metrics when making suggestions. Be cautious with T2 (approval-required) tools."""
        return system
    
    def call_llm(self, user_message: str, model: str = "gemini-2.0-flash") -> str:
        """Call LLM with context-enriched system prompt."""
        import google.generativeai as genai
        
        system_prompt = self.build_system_prompt()
        client = genai.GenerativeModel(model, system_instruction=system_prompt)
        
        response = client.generate_content(user_message)
        return response.text
    
    def refresh_context(self) -> Dict[str, Any]:
        """Force-refresh business context (after data changes)."""
        return self.context_mgr.refresh()
```

#### 2. **Integrate into Agent Entry Point**
Modify the agent call site (likely in `main.py` or `app.py`):

```python
# Before: LLM called directly without context
# response = llm.generate_content(user_message)

# After: Use orchestrator
from agent.llm_orchestrator import LLMOrchestrator

orchestrator = LLMOrchestrator(
    user_id=session.user_id,
    business_id=session.business_id,
    db_path=config.DB_PATH
)
response = orchestrator.call_llm(user_message)
```

#### 3. **Add Context Refresh Hooks**
Refresh context when data changes:

```python
# In expense tracking, business setup, or tool execution modules
def record_transaction(...):
    # ... save transaction ...
    orchestrator.refresh_context()  # Invalidate and recompute

def update_business_profile(...):
    # ... update business ...
    orchestrator.refresh_context()
```

### Verification Checklist
- [ ] System prompt includes revenue, expenses, margin, balance, health status
- [ ] Forecast data (p10/p50/p90) in context
- [ ] Obligations list attached
- [ ] Risk flags visible to LLM
- [ ] Context updates after transactions/edits
- [ ] Test: LLM references actual business numbers in responses

### Timeline
- **Development:** 2-3 hours (wrapper + integration)
- **Testing:** 1 hour (end-to-end context injection)
- **Total:** ~4 hours

---

## Issue 2: Business Registration Not Persisting

### Problem Statement
Users must re-enter business details each login. Data is either lost or not retrieved from session.

### Root Cause Analysis

**Current Implementation:**
- `core/business_setup.py` → `register_business()` saves to `business` table
- `auth/session_manager.py` → JWT carries `business_id`
- **Gap:** No retrieval of business profile on login; no re-association with user

**Database State:**
- `business` table: Stores name, sector, country, currency, registration type
- `business_member` table: Links `(business_id, user_id, phone_hash)` with role
- **Issue:** After logout/login, no query to fetch user's businesses

### Current Flow
```
Register → Save to business table ✓
Login → Session created with business_id ✓
Logout → Session destroyed ✓
Re-login → business_id NOT restored (MISSING)
```

### Solution Steps

#### 1. **Create Business Retrieval Endpoint**
Add to `db/users.py`:

```python
def get_businesses_for_user(db_path: str, user_id: int, phone_hash: str) -> List[Dict]:
    """Retrieve all businesses associated with a user via business_member."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT 
                    b.business_id,
                    b.public_ref,
                    b.name_token AS name,
                    b.sector,
                    b.sub_sector,
                    b.country_code,
                    b.currency_code,
                    b.timezone,
                    b.registration_type,
                    b.employee_count,
                    b.start_date,
                    bm.role,
                    b.created_at,
                    b.updated_at
                FROM business_member bm
                JOIN business b ON bm.business_id = b.business_id
                WHERE (bm.user_id = ? OR bm.phone_hash = ?)
                  AND b.status = 'active'
                ORDER BY b.updated_at DESC
            """, (user_id, phone_hash))
            
            rows = cursor.fetchall()
            return [
                {
                    "business_id": row["business_id"],
                    "name": row["name"],
                    "sector": row["sector"],
                    "sub_sector": row["sub_sector"],
                    "role": row["role"],
                    "country_code": row["country_code"],
                    "currency_code": row["currency_code"],
                    "timezone": row["timezone"],
                    "registration_type": row["registration_type"],
                    "employee_count": row["employee_count"],
                    "start_date": row["start_date"],
                    "public_ref": row["public_ref"],
                }
                for row in rows
            ]
    except sqlite3.OperationalError:
        return []
```

#### 2. **Modify Login Flow**
Update `auth/session_manager.py` or login endpoint:

```python
def handle_login(phone_hash: str, password_hash: str, db_path: str):
    """Login user and return list of associated businesses."""
    from db.users import get_user_by_phone, get_businesses_for_user
    
    # 1. Verify credentials
    user = get_user_by_phone(db_path, phone_hash)
    if not user or not verify_password(password_hash, user.password_hash):
        return {"error": "Invalid credentials"}
    
    # 2. Fetch all businesses for this user
    businesses = get_businesses_for_user(db_path, user.user_id, phone_hash)
    
    if not businesses:
        return {
            "user": {
                "user_id": user.user_id,
                "display_name": user.display_name,
                "phone_hash": phone_hash,
            },
            "businesses": [],
            "message": "No businesses found. Please register a new business.",
        }
    
    # 3. For single business, auto-select; for multiple, let user choose
    selected_business = businesses[0]  # Or prompt user
    
    # 4. Create session
    session_token = create_session(
        user_id=user.user_id,
        business_id=selected_business["business_id"],
        display_name=user.display_name,
        role="owner",
        phone_hash=phone_hash,
    )
    
    return {
        "token": session_token,
        "user": {
            "user_id": user.user_id,
            "display_name": user.display_name,
        },
        "business": selected_business,
        "businesses": businesses,  # For switching
    }
```

#### 3. **Add Business Selection UI**
When user has multiple businesses:

```python
# In session or API response
def select_business(user_id: int, business_id: int, db_path: str) -> str:
    """Switch to a different business and return new session token."""
    from auth.session_manager import create_session
    from db.users import get_user_by_id, get_businesses_for_user
    
    user = get_user_by_id(db_path, user_id)
    businesses = get_businesses_for_user(db_path, user_id, user.phone_hash)
    
    selected = next((b for b in businesses if b["business_id"] == business_id), None)
    if not selected:
        raise ValueError("Business not found or access denied")
    
    # Create new session for selected business
    token = create_session(
        user_id=user_id,
        business_id=business_id,
        display_name=user.display_name,
        role="owner",
        phone_hash=user.phone_hash,
    )
    return token
```

#### 4. **Fix Registration → Membership Association**
Ensure `register_business()` creates `business_member` entry:

```python
# In core/business_setup.py, register_business() method

def register_business(self, user_id: int, phone_hash: str, name: str, sector: str, ...):
    """Register business AND link to user."""
    # ... existing code to insert into business table ...
    
    business_id = cursor.lastrowid
    
    # NEW: Link user to business
    cursor.execute("""
        INSERT INTO business_member (business_id, user_id, phone_hash, role)
        VALUES (?, ?, ?, 'owner')
    """, (business_id, user_id, phone_hash))
    
    # Update business.owner_user_id
    cursor.execute("""
        UPDATE business SET owner_user_id = ?, owner_phone_hash = ? WHERE business_id = ?
    """, (user_id, phone_hash, business_id))
    
    conn.commit()
    return business_id
```

### Database Schema Check
Run this to ensure `business_member` table exists:
```sql
SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='business_member';
```
If 0, apply this migration:
```sql
CREATE TABLE IF NOT EXISTS business_member (
  business_id INTEGER NOT NULL REFERENCES business(business_id),
  user_id INTEGER NOT NULL REFERENCES app_user(user_id),
  phone_hash TEXT NOT NULL REFERENCES app_user(phone_hash),
  role TEXT NOT NULL CHECK (role IN ('owner','manager','accountant','viewer')),
  PRIMARY KEY (business_id, user_id),
  UNIQUE (business_id, phone_hash)
);
```

### Verification Checklist
- [ ] Register business → Creates entry in `business_member`
- [ ] Login → Retrieves all associated businesses
- [ ] Single business → Auto-selected, session created
- [ ] Multiple businesses → User prompted to select
- [ ] Business switch → New session token issued
- [ ] Logout/re-login → Business data restored

### Timeline
- **Coding:** 3-4 hours (endpoints, login flow refactor)
- **Testing:** 2 hours (registration → login → retrieval flow)
- **Total:** ~6 hours

---

## Issue 3: Expenses Not Tracked for Forecast

### Problem Statement
Expense entries are not feeding into the forecast model, so forecasts ignore expense patterns and can't predict cash shortfalls accurately.

### Root Cause Analysis

**Current State:**
- Expenses are saved in `recurring_expense` table (owner-entered recurring obligations)
- `transaction_ledger` contains historical transactions from statements (past data)
- **Gap:** Forecast uses only `transaction_ledger` historical data; doesn't incorporate:
  - Future recurring expenses (rent, salaries)
  - Expense patterns inferred from categories
  - One-time expenses

**In `core/forecaster.py`:**
```python
def forecast(daily_flows, obligations, opening_balance, ...):
    # Uses obligations (list of {due_date, amount_minor, label})
    # BUT obligations only come from:
    # - obligation table (detected from statements)
    # - recurring_expense table (if mapped)
    # - standing_order table
    # - scheduled_payment (awaiting authorization)
    
    # MISSING: Future recurring_expense instances not pre-generated
```

### Current Data Flow
```
Transaction Ledger ──→ Categorize → Compute daily inflows/outflows
Obligations table   ──→ Filter next 14 days → Add to forecast
Recurring_expense   ←─ NOT pulled into obligations
Standing_order      ──→ Add to forecast ✓
Forecast computes   → balance path
```

### Solution Steps

#### 1. **Extend Obligations Query**
In `auth/user_context.py`, modify `_obligations()` to include recurring expenses:

```python
def _obligations(self) -> List[Dict[str, Any]]:
    """Merge obligations from all sources: detected, owner-entered, standing orders."""
    from datetime import datetime, timedelta
    
    sources = [
        ("detected", """SELECT label, amount_minor, next_due, cadence FROM obligation
                        WHERE business_id = ? AND active = 1
                          AND next_due <= date('now', '+14 days')"""),
        
        ("owner_entered", """SELECT description AS label, amount_minor, next_due, cadence
                             FROM recurring_expense
                             WHERE business_id = ? AND active = 1
                               AND next_due <= date('now', '+14 days')"""),
        
        # NEW: Generate future instances of recurring_expense
        ("recurring_instances", self._generate_recurring_instances()),
        
        ("standing_order", """SELECT label, amount_minor, next_due, cadence FROM standing_order
                              WHERE business_id = ? AND status = 'active'
                                AND next_due <= date('now', '+14 days')"""),
    ]
    
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    out: List[Dict[str, Any]] = []
    
    for source, sql in sources[:3]:  # First 3 from DB queries
        if isinstance(sql, str):  # Not a generated list
            try:
                rows = conn.execute(sql, (self.business_id,)).fetchall()
            except sqlite3.OperationalError:
                continue
            out.extend([...])
        else:  # Generated instances (list)
            out.extend(sql)
    
    conn.close()
    return sorted(out, key=lambda o: o["due_date"] or "")

def _generate_recurring_instances(self) -> List[Dict[str, Any]]:
    """Generate future instances of recurring expenses for next 14 days."""
    from datetime import datetime, timedelta
    import sqlite3
    
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    
    # Get all active recurring expenses
    expenses = conn.execute("""
        SELECT expense_id, description, amount_minor, cadence, 
               day_of_month, next_due, is_variable, variable_formula
        FROM recurring_expense
        WHERE business_id = ? AND active = 1
    """, (self.business_id,)).fetchall()
    
    instances = []
    today = datetime.now().date()
    horizon = today + timedelta(days=14)
    
    for exp in expenses:
        next_due = datetime.strptime(exp["next_due"], "%Y-%m-%d").date()
        
        while next_due <= horizon:
            if next_due >= today:
                instances.append({
                    "label": exp["description"],
                    "amount_kes": round(exp["amount_minor"] / 100.0, 2),
                    "due_date": next_due.strftime("%Y-%m-%d"),
                    "frequency": exp["cadence"],
                    "source": "recurring_expense",
                })
            
            # Calculate next occurrence
            next_due = self._calculate_next_due(next_due, exp["cadence"])
    
    conn.close()
    return instances

def _calculate_next_due(self, current_date, cadence: str):
    """Compute next due date based on cadence."""
    from datetime import timedelta
    
    if cadence == "daily":
        return current_date + timedelta(days=1)
    elif cadence == "weekly":
        return current_date + timedelta(weeks=1)
    elif cadence == "biweekly":
        return current_date + timedelta(weeks=2)
    elif cadence == "monthly":
        next_month = current_date.replace(day=1) + timedelta(days=32)
        return next_month.replace(day=current_date.day)
    elif cadence == "quarterly":
        return current_date + timedelta(days=91)
    elif cadence == "annual":
        return current_date + timedelta(days=365)
    else:
        return current_date
```

#### 2. **Create Recurring Expense Instance Tracking Table**
Ensure instances are tracked:

```sql
-- If not exists, add to schema.sql or run migration:
CREATE TABLE IF NOT EXISTS recurring_expense_instance (
  instance_id INTEGER PRIMARY KEY,
  expense_id INTEGER NOT NULL REFERENCES recurring_expense(expense_id),
  due_date TEXT NOT NULL,
  expected_amount_minor INTEGER NOT NULL,
  matched_txn_id INTEGER REFERENCES transaction_ledger(txn_id),
  actual_amount_minor INTEGER,
  status TEXT NOT NULL DEFAULT 'expected' CHECK (status IN (
    'expected','paid','late','missed','skipped'
  )),
  paid_date TEXT,
  notes TEXT,
  UNIQUE (expense_id, due_date)
);
```

#### 3. **Update Forecast to Use Merged Obligations**
No changes needed in `core/forecaster.py` — it already accepts obligations list. Just ensure the obligations passed include recurring expenses.

#### 4. **Add Expense Category Patterns** (Optional Refinement)
If forecast should predict variable expenses based on historical patterns:

```python
def _infer_expense_patterns(self) -> Dict[str, Dict]:
    """Analyze transaction history to identify expense trends by category."""
    conn = sqlite3.connect(self.db_path)
    
    # Group by category and weekday to find patterns
    patterns = conn.execute("""
        SELECT 
            c.code,
            c.name,
            CAST(strftime('%w', t.local_date) AS INTEGER) AS weekday,
            AVG(t.amount_minor) AS avg_amount,
            COUNT(*) AS frequency
        FROM transaction_ledger t
        LEFT JOIN category c ON t.category_id = c.category_id
        WHERE t.business_id = ? AND t.direction = 'out' AND t.voided = 0
              AND t.local_date >= date('now', '-60 days')
        GROUP BY c.code, weekday
    """, (self.business_id,)).fetchall()
    
    result = {}
    for row in patterns:
        cat_code = row[0] or "unknown"
        if cat_code not in result:
            result[cat_code] = {}
        result[cat_code][row[2]] = {"avg": row[3], "freq": row[4]}
    
    return result
```

### Verification Checklist
- [ ] Recurring expenses pull into `_obligations()` list
- [ ] Future instances generated for all recurring types (daily/weekly/monthly/etc.)
- [ ] Forecast receives merged obligations (detected + recurring + standing orders)
- [ ] p10/p50/p90 balances adjust downward when recurring expenses included
- [ ] Shortfall detection catches expense-driven shortfalls
- [ ] Manual test: Add monthly rent expense, verify forecast drops on due date

### Timeline
- **Coding:** 2-3 hours (obligation merge, instance generation)
- **Testing:** 1-2 hours (forecast accuracy with recurring expenses)
- **Total:** ~4 hours

---

## Issue 4: Audit Data is Hardcoded

### Problem Statement
Audit logs contain fake/hardcoded entries instead of actual system events.

### Root Cause Analysis

**Current State:**
- `db/audit.py` has full implementation: hash-chained, immutable logging
- **Gap:** Audit events are not triggered when actions occur
- **Missing:** Integration of `log_event()` calls in business logic

**Where Events SHOULD be logged but aren't:**
```
1. User login → No audit event
2. Business registered → No audit event
3. Transaction ingested → No audit event
4. Transaction categorized → No audit event
5. Expense added → No audit event
6. Forecast run → No audit event
7. Tool called (T2 actions) → No audit event
8. Approval given → No audit event
9. Payment executed → No audit event
10. Data modified → No audit event
```

### Current Implementation
```python
# db/audit.py
def log_event(db_path, actor, event_type, *, business_id=None, ...):
    """Function exists but IS NOT CALLED anywhere in codebase"""
```

### Solution Steps

#### 1. **Create Audit Service Wrapper**
New file: `services/audit_service.py`:

```python
"""Centralized audit logging for all business events."""
import sqlite3
from typing import Optional, Dict, Any
from db.audit import log_event
from core.config import config


class AuditService:
    """Wrapper around db.audit to log events throughout the app."""
    
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
    
    # ---- Authentication Events ----
    def log_login(self, user_id: int, phone_hash: str, business_id: Optional[int] = None):
        log_event(
            self.db_path,
            actor="owner",  # or "system" if auto-login
            event_type="login",
            business_id=business_id,
            details={"user_id": user_id, "phone_hash": phone_hash[:8]}
        )
    
    def log_logout(self, user_id: int, business_id: Optional[int] = None):
        log_event(
            self.db_path,
            actor="owner",
            event_type="logout",
            business_id=business_id,
            details={"user_id": user_id}
        )
    
    def log_session_created(self, user_id: int, business_id: int, role: str):
        log_event(
            self.db_path,
            actor="system",
            event_type="session_created",
            business_id=business_id,
            details={"user_id": user_id, "role": role}
        )
    
    # ---- Business Registration ----
    def log_business_registered(self, user_id: int, business_id: int, 
                               name: str, sector: str):
        log_event(
            self.db_path,
            actor="owner",
            event_type="business_registered",
            business_id=business_id,
            entity_type="business",
            entity_id=business_id,
            details={
                "name": name,
                "sector": sector,
                "registered_by": user_id
            }
        )
    
    # ---- Transaction/Ingestion Events ----
    def log_statement_uploaded(self, business_id: int, file_id: int, 
                              filename: str, row_count: int, uploaded_by: int):
        log_event(
            self.db_path,
            actor="owner",
            event_type="statement_uploaded",
            business_id=business_id,
            entity_type="source_file",
            entity_id=file_id,
            details={
                "filename": filename,
                "row_count": row_count,
                "uploaded_by": uploaded_by
            }
        )
    
    def log_transactions_ingested(self, business_id: int, file_id: int,
                                 rows_loaded: int, rows_rejected: int):
        log_event(
            self.db_path,
            actor="system",
            event_type="transactions_ingested",
            business_id=business_id,
            entity_type="source_file",
            entity_id=file_id,
            details={
                "rows_loaded": rows_loaded,
                "rows_rejected": rows_rejected
            }
        )
    
    def log_transaction_categorized(self, business_id: int, txn_id: int,
                                   category: str, confidence: float, 
                                   method: str = "rule"):
        log_event(
            self.db_path,
            actor="system" if method != "owner" else "owner",
            event_type="transaction_categorized",
            business_id=business_id,
            entity_type="transaction",
            entity_id=txn_id,
            details={
                "category": category,
                "confidence": confidence,
                "method": method
            }
        )
    
    # ---- Expense Events ----
    def log_recurring_expense_added(self, business_id: int, expense_id: int,
                                   description: str, amount_minor: int, cadence: str):
        log_event(
            self.db_path,
            actor="owner",
            event_type="expense_added",
            business_id=business_id,
            entity_type="recurring_expense",
            entity_id=expense_id,
            details={
                "description": description,
                "amount_kes": amount_minor / 100,
                "cadence": cadence
            }
        )
    
    def log_recurring_expense_paid(self, business_id: int, expense_id: int,
                                  txn_id: int, actual_amount: int):
        log_event(
            self.db_path,
            actor="system",
            event_type="expense_paid",
            business_id=business_id,
            entity_type="recurring_expense",
            entity_id=expense_id,
            details={
                "matched_txn_id": txn_id,
                "actual_amount_kes": actual_amount / 100
            }
        )
    
    # ---- Forecast Events ----
    def log_forecast_computed(self, business_id: int, run_id: int,
                             horizon_days: int, shortfalls_detected: int):
        log_event(
            self.db_path,
            actor="system",
            event_type="forecast_computed",
            business_id=business_id,
            entity_type="forecast_run",
            entity_id=run_id,
            details={
                "horizon_days": horizon_days,
                "shortfalls_detected": shortfalls_detected
            }
        )
    
    def log_shortfall_alert(self, business_id: int, alert_id: int,
                           gap_minor: int, probability_bp: int):
        log_event(
            self.db_path,
            actor="system",
            event_type="shortfall_alert",
            business_id=business_id,
            entity_type="alert",
            entity_id=alert_id,
            details={
                "gap_kes": gap_minor / 100,
                "probability_bp": probability_bp
            }
        )
    
    # ---- Tool & Approval Events ----
    def log_tool_called(self, business_id: int, user_id: int, 
                       tool_name: str, tier: str, args_summary: Dict):
        log_event(
            self.db_path,
            actor="owner",
            event_type="tool_called",
            business_id=business_id,
            tool=tool_name,
            tier=tier,
            details={
                "user_id": user_id,
                "args": args_summary
            }
        )
    
    def log_approval_requested(self, business_id: int, action_id: int,
                              kind: str, amount_minor: int):
        log_event(
            self.db_path,
            actor="agent",
            event_type="approval_requested",
            business_id=business_id,
            entity_type="proposed_action",
            entity_id=action_id,
            decision="pending",
            details={
                "kind": kind,
                "amount_kes": amount_minor / 100
            }
        )
    
    def log_approval_given(self, business_id: int, action_id: int,
                          decided_by: int, decision: str):
        log_event(
            self.db_path,
            actor="owner",
            event_type="approval_given",
            business_id=business_id,
            entity_type="proposed_action",
            entity_id=action_id,
            decision=decision,
            details={
                "decided_by": decided_by,
                "decision": decision
            }
        )
    
    def log_action_executed(self, business_id: int, action_id: int,
                           kind: str, result_summary: str):
        log_event(
            self.db_path,
            actor="system",
            event_type="action_executed",
            business_id=business_id,
            entity_type="proposed_action",
            entity_id=action_id,
            details={
                "kind": kind,
                "result": result_summary
            }
        )


# Singleton instance
_audit_service: Optional[AuditService] = None

def get_audit_service() -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
```

#### 2. **Wire Audit into Key Modules**

**In `auth/session_manager.py` (login/logout):**
```python
def create_session(...):
    # ... existing code ...
    from services.audit_service import get_audit_service
    audit = get_audit_service()
    audit.log_session_created(user_id, business_id, role)
    return token

def revoke_session(db_path, token, reason='logout'):
    # ... decode token ...
    session = decode_session(token)
    from services.audit_service import get_audit_service
    audit = get_audit_service()
    audit.log_logout(session.user_id, session.business_id)
    # ... existing code ...
```

**In `core/business_setup.py` (business registration):**
```python
def register_business(self, user_id: int, phone_hash: str, ...):
    # ... existing code to insert business ...
    business_id = cursor.lastrowid
    
    from services.audit_service import get_audit_service
    audit = get_audit_service()
    audit.log_business_registered(user_id, business_id, name, sector)
    
    return business_id
```

**In expense tracking/recurring_expense (add/update/delete):**
```python
def add_recurring_expense(self, business_id: int, ...):
    # ... existing code ...
    expense_id = cursor.lastrowid
    
    from services.audit_service import get_audit_service
    audit = get_audit_service()
    audit.log_recurring_expense_added(
        business_id, expense_id, description, amount_minor, cadence
    )
    
    return expense_id
```

**In forecaster (after compute):**
```python
def forecast(self, ...):
    # ... existing forecast logic ...
    result = ForecastResult(...)
    
    from services.audit_service import get_audit_service
    audit = get_audit_service()
    shortfalls = self.detect_shortfalls(result)
    audit.log_forecast_computed(
        business_id, run_id, horizon_days, len(shortfalls)
    )
    
    return result
```

#### 3. **Create Audit Query Endpoints**
Add to `db/audit.py`:

```python
def get_events_for_business(db_path: str, business_id: int, 
                           event_type: Optional[str] = None,
                           limit: int = 50) -> List[AuditEvent]:
    """Retrieve audit events for a business."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if event_type:
                rows = conn.execute("""
                    SELECT * FROM audit_log 
                    WHERE business_id = ? AND event_type = ?
                    ORDER BY seq DESC LIMIT ?
                """, (business_id, event_type, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM audit_log 
                    WHERE business_id = ?
                    ORDER BY seq DESC LIMIT ?
                """, (business_id, limit)).fetchall()
        
        events = []
        for r in rows:
            details = json.loads(r["details_json"]) if r["details_json"] else {}
            events.append(AuditEvent(
                seq=r["seq"], ts=r["ts"], business_id=r["business_id"],
                actor=r["actor"], event_type=r["event_type"], tool=r["tool"],
                tier=r["tier"], decision=r["decision"], 
                entity_type=r["entity_type"], entity_id=r["entity_id"],
                details=details, prev_hash=r["prev_hash"], hash=r["hash"]
            ))
        return events
    except sqlite3.OperationalError:
        return []
```

### Verification Checklist
- [ ] Login event logged to audit_log
- [ ] Business registration event logged
- [ ] Statement upload event logged
- [ ] Transaction categorization events logged
- [ ] Recurring expense addition logged
- [ ] Forecast computation logged
- [ ] Tool calls logged with tier
- [ ] Approvals and executions logged
- [ ] Audit chain integrity verified (hash-chaining intact)
- [ ] Test: Run `verify_audit(db_path)` → returns `valid=True`

### Timeline
- **Coding:** 3-4 hours (audit service + integration points)
- **Testing:** 1-2 hours (trace events through workflows)
- **Total:** ~5-6 hours

---

## Issue 5: Working Capital Missing Details

### Problem Statement
Working capital feature lacks detailed breakdown for users to understand and manage liquidity.

### Root Cause Analysis

**Current State:**
- Forecast computes p10/p50/p90 end balance (30-day horizon)
- Health metrics show days of cash and burn rate (summary only)
- **Missing Details:**
  - Weekly cash flow progression
  - Category-wise expense breakdown (rent, salaries, supplies, etc.)
  - Seasonality/weekday patterns
  - Cash buffer adequacy analysis
  - Debt service capacity
  - Receivables aging
  - Payables breakdown

### Required Data for Full Working Capital Analysis
```
1. Liquidity Position
   - Current cash balance
   - Days of cash at current burn
   - Weekly forecast progression
   - Safety buffer threshold vs. actual

2. Cash Inflows
   - Daily average (by weekday)
   - Seasonal patterns (monthly, quarterly)
   - Customer receivables (aging)
   - Payment terms impact

3. Cash Outflows
   - By category (rent, salaries, COGS, etc.)
   - Fixed vs. variable
   - Upcoming obligations (next 30/60/90 days)
   - Seasonal spikes

4. Working Capital Metrics
   - Operating cycle (Days Inventory + Days Receivable - Days Payable)
   - Cash conversion cycle
   - Debt service ratio
   - Payables coverage

5. Stress Scenarios
   - 20% revenue drop
   - 10% expense increase
   - Delayed receivables
   - Early obligation payment
```

### Solution Steps

#### 1. **Create Working Capital Service**
New file: `core/working_capital.py` (comprehensive version):

```python
"""Working capital analysis and recommendations."""
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
import pandas as pd
from core.config import config


@dataclass
class WorkingCapitalSnapshot:
    """Complete working capital position."""
    business_id: int
    as_of_date: str
    
    # Liquidity
    current_balance_kes: float
    days_of_cash: int
    safety_buffer_kes: float
    buffer_coverage: float  # Ratio of balance to buffer (>1 = safe)
    
    # Inflows (30 days)
    inflow_daily_avg_kes: float
    inflow_expected_30d_kes: float
    receivables_outstanding_kes: float
    receivables_aging_days: int
    
    # Outflows (30 days)
    outflow_daily_avg_kes: float
    outflow_expected_30d_kes: float
    obligations_due_30d_kes: float
    
    # Metrics
    operating_cycle_days: int
    cash_conversion_cycle_days: int
    debt_service_ratio: float  # (Operating cash flow / Debt payments)
    
    # Breakdown
    expense_by_category: Dict[str, float]
    obligations_by_kind: Dict[str, float]
    
    # Stress scenarios
    scenarios: Dict[str, Dict[str, float]]
    
    # Recommendations
    recommendations: List[str]
    risk_flags: List[str]


class WorkingCapitalAnalyzer:
    """Analyze working capital position and provide insights."""
    
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
    
    def analyze(self, business_id: int) -> WorkingCapitalSnapshot:
        """Comprehensive working capital analysis."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        as_of = datetime.now().strftime("%Y-%m-%d")
        
        # Collect all components
        liquidity = self._liquidity_position(conn, business_id)
        inflows = self._inflow_analysis(conn, business_id)
        outflows = self._outflow_analysis(conn, business_id)
        metrics = self._compute_metrics(conn, business_id, liquidity, inflows, outflows)
        expenses_by_cat = self._expenses_by_category(conn, business_id)
        obligations_by_kind = self._obligations_by_kind(conn, business_id)
        scenarios = self._stress_scenarios(liquidity, inflows, outflows)
        recommendations = self._generate_recommendations(
            liquidity, inflows, outflows, metrics, expenses_by_cat
        )
        risk_flags = self._identify_risks(liquidity, metrics, obligations_by_kind)
        
        conn.close()
        
        return WorkingCapitalSnapshot(
            business_id=business_id,
            as_of_date=as_of,
            current_balance_kes=liquidity["balance"],
            days_of_cash=liquidity["days_of_cash"],
            safety_buffer_kes=liquidity["buffer"],
            buffer_coverage=liquidity["balance"] / max(1, liquidity["buffer"]),
            inflow_daily_avg_kes=inflows["daily_avg"],
            inflow_expected_30d_kes=inflows["expected_30d"],
            receivables_outstanding_kes=inflows["receivables"],
            receivables_aging_days=inflows["aging_days"],
            outflow_daily_avg_kes=outflows["daily_avg"],
            outflow_expected_30d_kes=outflows["expected_30d"],
            obligations_due_30d_kes=outflows["obligations_30d"],
            operating_cycle_days=metrics["operating_cycle"],
            cash_conversion_cycle_days=metrics["ccc"],
            debt_service_ratio=metrics["debt_service_ratio"],
            expense_by_category=expenses_by_cat,
            obligations_by_kind=obligations_by_kind,
            scenarios=scenarios,
            recommendations=recommendations,
            risk_flags=risk_flags,
        )
    
    def _liquidity_position(self, conn: sqlite3.Connection, business_id: int) -> Dict:
        """Current cash position and runway."""
        # Current balance
        bal_row = conn.execute("""
            SELECT balance_after_minor FROM transaction_ledger
            WHERE business_id = ? AND voided = 0 AND balance_after_minor IS NOT NULL
            ORDER BY ts DESC LIMIT 1
        """, (business_id,)).fetchone()
        balance = bal_row[0] / 100 if bal_row else 0
        
        # Daily outflow (30-day avg)
        expense_row = conn.execute("""
            SELECT SUM(CASE WHEN direction='out' THEN amount_minor + fee_minor ELSE 0 END) AS total
            FROM transaction_ledger
            WHERE business_id = ? AND voided = 0 AND local_date >= date('now', '-30 days')
        """, (business_id,)).fetchone()
        total_30d = expense_row[0] or 0
        daily_outflow = (total_30d / 30) / 100
        
        buffer = config.SAFETY_BUFFER_MINOR / 100
        days_of_cash = int(balance / daily_outflow) if daily_outflow > 0 else 999
        
        return {
            "balance": balance,
            "daily_outflow": daily_outflow,
            "days_of_cash": days_of_cash,
            "buffer": buffer,
        }
    
    def _inflow_analysis(self, conn: sqlite3.Connection, business_id: int) -> Dict:
        """Revenue and receivables."""
        # Daily inflow (30-day avg)
        inflow_row = conn.execute("""
            SELECT SUM(CASE WHEN direction='in' THEN amount_minor ELSE 0 END) AS total
            FROM transaction_ledger
            WHERE business_id = ? AND voided = 0 AND local_date >= date('now', '-30 days')
        """, (business_id,)).fetchone()
        total_30d = inflow_row[0] or 0
        daily_avg = (total_30d / 30) / 100
        expected_30d = (total_30d / 100)
        
        # Receivables (if tracked)
        receivables = 0  # TODO: Query from invoice/sale tables if implemented
        aging_days = 0
        
        return {
            "daily_avg": daily_avg,
            "expected_30d": expected_30d,
            "receivables": receivables,
            "aging_days": aging_days,
        }
    
    def _outflow_analysis(self, conn: sqlite3.Connection, business_id: int) -> Dict:
        """Operating outflows and obligations."""
        # Daily outflow (30-day avg)
        outflow_row = conn.execute("""
            SELECT SUM(CASE WHEN direction='out' THEN amount_minor + fee_minor ELSE 0 END) AS total
            FROM transaction_ledger
            WHERE business_id = ? AND voided = 0 AND local_date >= date('now', '-30 days')
        """, (business_id,)).fetchone()
        total_30d = outflow_row[0] or 0
        daily_avg = (total_30d / 30) / 100
        expected_30d = (total_30d / 100)
        
        # Obligations (next 30 days)
        obl_row = conn.execute("""
            SELECT COALESCE(SUM(amount_minor), 0) AS total
            FROM obligation
            WHERE business_id = ? AND active = 1 AND next_due <= date('now', '+30 days')
        """, (business_id,)).fetchone()
        obligations_30d = (obl_row[0] / 100) if obl_row else 0
        
        return {
            "daily_avg": daily_avg,
            "expected_30d": expected_30d,
            "obligations_30d": obligations_30d,
        }
    
    def _compute_metrics(self, conn, business_id, liquidity, inflows, outflows) -> Dict:
        """Operational and financial metrics."""
        # Operating cycle = Days Inventory Outstanding + Days Sales Outstanding
        # (approximated from category patterns)
        dio = 0  # TODO: From inventory table if available
        dso = max(0, inflows["aging_days"])
        dpo = 0  # TODO: From payables if available
        
        ccc = dio + dso - dpo  # Cash Conversion Cycle
        
        # Debt service ratio
        debt_payments = outflows["obligations_30d"]
        operating_cf = inflows["expected_30d"] - outflows["expected_30d"]
        debt_service_ratio = operating_cf / max(1, debt_payments) if debt_payments > 0 else 0
        
        return {
            "operating_cycle": dio + dso,
            "ccc": ccc,
            "debt_service_ratio": debt_service_ratio,
        }
    
    def _expenses_by_category(self, conn, business_id) -> Dict[str, float]:
        """Breakdown of expenses by category (30 days)."""
        rows = conn.execute("""
            SELECT c.name, SUM(t.amount_minor + t.fee_minor) AS total
            FROM transaction_ledger t
            LEFT JOIN category c ON t.category_id = c.category_id
            WHERE t.business_id = ? AND t.direction = 'out' AND t.voided = 0
                  AND t.local_date >= date('now', '-30 days')
            GROUP BY c.name
            ORDER BY total DESC
        """, (business_id,)).fetchall()
        
        return {row[0] or "Unclassified": row[1] / 100 for row in rows}
    
    def _obligations_by_kind(self, conn, business_id) -> Dict[str, float]:
        """Breakdown of obligations by type (next 30 days)."""
        rows = conn.execute("""
            SELECT kind, SUM(amount_minor) AS total
            FROM obligation
            WHERE business_id = ? AND active = 1 AND next_due <= date('now', '+30 days')
            GROUP BY kind
            ORDER BY total DESC
        """, (business_id,)).fetchall()
        
        return {row[0]: row[1] / 100 for row in rows}
    
    def _stress_scenarios(self, liquidity, inflows, outflows) -> Dict[str, Dict]:
        """Test working capital under adverse scenarios."""
        base_cf = inflows["expected_30d"] - outflows["expected_30d"]
        base_balance = liquidity["balance"]
        
        scenarios = {
            "revenue_drop_20pct": {
                "inflow_reduction_kes": inflows["expected_30d"] * 0.2,
                "resulting_cf_kes": (inflows["expected_30d"] * 0.8) - outflows["expected_30d"],
                "balance_end_kes": base_balance + ((inflows["expected_30d"] * 0.8) - outflows["expected_30d"]),
                "buffer_breach": base_balance + ((inflows["expected_30d"] * 0.8) - outflows["expected_30d"]) < liquidity["buffer"],
            },
            "expense_increase_10pct": {
                "outflow_increase_kes": outflows["expected_30d"] * 0.1,
                "resulting_cf_kes": inflows["expected_30d"] - (outflows["expected_30d"] * 1.1),
                "balance_end_kes": base_balance + (inflows["expected_30d"] - (outflows["expected_30d"] * 1.1)),
                "buffer_breach": base_balance + (inflows["expected_30d"] - (outflows["expected_30d"] * 1.1)) < liquidity["buffer"],
            },
            "receivables_delayed_15d": {
                "delayed_amount_kes": inflows["receivables"],
                "resulting_cf_kes": base_cf - inflows["receivables"],
                "balance_end_kes": base_balance - inflows["receivables"],
                "buffer_breach": (base_balance - inflows["receivables"]) < liquidity["buffer"],
            },
        }
        
        return scenarios
    
    def _generate_recommendations(self, liquidity, inflows, outflows, metrics, 
                                 expenses_by_cat) -> List[str]:
        """Generate actionable recommendations."""
        recs = []
        
        if liquidity["days_of_cash"] < 7:
            recs.append("🚨 CRITICAL: Less than 7 days of cash. Consider short-term financing urgently.")
        elif liquidity["days_of_cash"] < 14:
            recs.append("⚠️ WARNING: Only 14 days of cash. Prioritize receivables collection and defer non-essential spending.")
        
        if liquidity["buffer_coverage"] < 1:
            recs.append(f"⚠️ Buffer Alert: Balance is {(1 - liquidity['buffer_coverage']) * 100:.0f}% below safety threshold.")
        
        # Top expense
        if expenses_by_cat:
            top_cat = max(expenses_by_cat, key=expenses_by_cat.get)
            top_amount = expenses_by_cat[top_cat]
            if top_amount > outflows["expected_30d"] * 0.3:
                recs.append(f"💡 {top_cat} is {(top_amount / outflows['expected_30d'] * 100):.0f}% of expenses. Review negotiation opportunities.")
        
        debt_ratio = metrics["debt_service_ratio"]
        if debt_ratio < 1.2:
            recs.append(f"💡 Debt Service Ratio is {debt_ratio:.1f}. Limited headroom for additional debt. Focus on profitability.")
        
        # Receivables aging
        if metrics["dso"] > 30:
            recs.append(f"📊 Receivables age {metrics['dso']} days. Implement faster collection to improve cash flow.")
        
        recs.append("📈 Scenario: 20% revenue drop would breach buffer. Build additional reserves.")
        
        return recs
    
    def _identify_risks(self, liquidity, metrics, obligations) -> List[str]:
        """Identify financial risks."""
        risks = []
        
        if liquidity["days_of_cash"] < 14:
            risks.append("Liquidity Risk: Limited runway")
        
        if metrics["debt_service_ratio"] < 1:
            risks.append("Solvency Risk: Not enough cashflow to cover debt")
        
        if "rent" in obligations and obligations["rent"] > liquidity["daily_outflow"] * 5:
            risks.append("Fixed Cost Risk: Rent is >5x daily outflow (inflexible burden)")
        
        return risks
```

#### 2. **Create Working Capital Endpoint**
Add to API or Streamlit app:

```python
# In main app
from core.working_capital import WorkingCapitalAnalyzer

@app.route("/api/working-capital/<business_id>")
def get_working_capital(business_id):
    """Return comprehensive working capital analysis."""
    analyzer = WorkingCapitalAnalyzer()
    snapshot = analyzer.analyze(business_id)
    
    return {
        "business_id": business_id,
        "as_of_date": snapshot.as_of_date,
        "liquidity": {
            "current_balance_kes": snapshot.current_balance_kes,
            "days_of_cash": snapshot.days_of_cash,
            "safety_buffer_kes": snapshot.safety_buffer_kes,
            "buffer_coverage": snapshot.buffer_coverage,
        },
        "inflows": {
            "daily_avg_kes": snapshot.inflow_daily_avg_kes,
            "expected_30d_kes": snapshot.inflow_expected_30d_kes,
            "receivables_kes": snapshot.receivables_outstanding_kes,
        },
        "outflows": {
            "daily_avg_kes": snapshot.outflow_daily_avg_kes,
            "expected_30d_kes": snapshot.outflow_expected_30d_kes,
            "obligations_due_30d_kes": snapshot.obligations_due_30d_kes,
        },
        "metrics": {
            "operating_cycle_days": snapshot.operating_cycle_days,
            "cash_conversion_cycle_days": snapshot.cash_conversion_cycle_days,
            "debt_service_ratio": snapshot.debt_service_ratio,
        },
        "expense_breakdown": snapshot.expense_by_category,
        "obligations_breakdown": snapshot.obligations_by_kind,
        "stress_scenarios": snapshot.scenarios,
        "recommendations": snapshot.recommendations,
        "risk_flags": snapshot.risk_flags,
    }
```

#### 3. **Create Dashboard/UI Components**
Display working capital in Streamlit:

```python
# In Streamlit app
import streamlit as st
from core.working_capital import WorkingCapitalAnalyzer

st.header("💰 Working Capital Overview")

analyzer = WorkingCapitalAnalyzer()
snapshot = analyzer.analyze(st.session_state.business_id)

# Liquidity Panel
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Current Balance", f"KES {snapshot.current_balance_kes:,.0f}")
with col2:
    st.metric("Days of Cash", snapshot.days_of_cash, delta=snapshot.days_of_cash - 14)
with col3:
    st.metric("Safety Buffer", f"KES {snapshot.safety_buffer_kes:,.0f}")
with col4:
    coverage_color = "🟢" if snapshot.buffer_coverage > 1 else "🔴"
    st.metric("Buffer Coverage", f"{coverage_color} {snapshot.buffer_coverage:.1f}x")

# Cash Flow
col1, col2 = st.columns(2)
with col1:
    st.subheader("30-Day Inflows")
    st.write(f"Daily Avg: KES {snapshot.inflow_daily_avg_kes:,.0f}")
    st.write(f"Expected Total: KES {snapshot.inflow_expected_30d_kes:,.0f}")
with col2:
    st.subheader("30-Day Outflows")
    st.write(f"Daily Avg: KES {snapshot.outflow_daily_avg_kes:,.0f}")
    st.write(f"Expected Total: KES {snapshot.outflow_expected_30d_kes:,.0f}")

# Expense Breakdown
st.subheader("Expense Breakdown (Last 30 Days)")
st.bar_chart(snapshot.expense_by_category)

# Obligations
st.subheader("Obligations by Type (Next 30 Days)")
st.bar_chart(snapshot.obligations_by_kind)

# Stress Scenarios
st.subheader("📊 Stress Scenarios")
for scenario, result in snapshot.scenarios.items():
    with st.expander(scenario.replace("_", " ").title()):
        st.write(f"Impact: KES {result['resulting_cf_kes']:,.0f}")
        status = "🔴 BREACH" if result["buffer_breach"] else "🟢 SAFE"
        st.write(f"Buffer Status: {status}")

# Recommendations
st.subheader("💡 Recommendations")
for rec in snapshot.recommendations:
    st.write(rec)

# Risks
if snapshot.risk_flags:
    st.subheader("⚠️ Risk Flags")
    for risk in snapshot.risk_flags:
        st.warning(risk)
```

### Verification Checklist
- [ ] Working capital analyzer computes all metrics
- [ ] Liquidity position accurate (balance, days of cash, buffer)
- [ ] Inflow/outflow analysis for 30 days
- [ ] Expense breakdown by category complete
- [ ] Obligations breakdown by kind
- [ ] Stress scenarios calculated (revenue drop, expense increase, receivable delay)
- [ ] Recommendations generated based on metrics
- [ ] Risk flags identified
- [ ] Dashboard displays all data clearly
- [ ] Test: Run analyzer for a known business, verify numbers match ledger sums

### Timeline
- **Coding:** 4-5 hours (analyzer logic + breakdown queries + scenarios)
- **UI/Dashboard:** 2-3 hours (Streamlit components)
- **Testing:** 2 hours (verify metrics accuracy, scenario outcomes)
- **Total:** ~8-10 hours

---

## Implementation Roadmap

### Phase 1: Critical (Week 1)
- **Issue #2** (Business Registration Persistence) — 6 hrs
  - Creates revenue-blocking bug fix
  - Enables user retention
  - High ROI

- **Issue #4** (Audit Data) — 5-6 hrs
  - Compliance requirement
  - Foundation for Issue #1 (context injection)
  - Must have for production

### Phase 2: Core (Week 2)
- **Issue #1** (LLM Context) — 4 hrs
  - Requires Issue #4 in place
  - Dramatically improves LLM quality
  - Multiplier for all other features

- **Issue #3** (Expenses in Forecast) — 4 hrs
  - Leverages Issue #2 persistence
  - Makes forecasts actionable
  - Directly supports working capital

### Phase 3: Enhanced (Week 3)
- **Issue #5** (Working Capital Details) — 8-10 hrs
  - Comprehensive feature for SME liquidity management
  - Depends on Issues #1-4
  - High user value but not blocking

### Total Time Estimate: **30-40 hours** (4-5 developer-weeks)

---

## Testing Strategy

### Unit Tests (Per Issue)
```bash
# Issue 1: LLM Context
pytest tests/test_llm_orchestrator.py

# Issue 2: Business Persistence
pytest tests/test_business_retrieval.py

# Issue 3: Expense Tracking
pytest tests/test_forecast_expenses.py

# Issue 4: Audit Logging
pytest tests/test_audit_integration.py

# Issue 5: Working Capital
pytest tests/test_working_capital.py
```

### Integration Tests
```bash
# End-to-end registration → login → forecast → working capital
pytest tests/integration/test_full_workflow.py
```

### Manual Testing Checklist
- [ ] Register business → Verify in DB
- [ ] Logout/Re-login → Business data restored
- [ ] Add recurring expense → Appears in forecast
- [ ] Forecast updated → Includes expense obligations
- [ ] Check audit log → Contains registration, login, expense events
- [ ] LLM request → References business context in response
- [ ] Working capital dashboard → All metrics populated

---

## Success Criteria

| Issue | Success Criterion |
|-------|-------------------|
| #1 LLM Context | LLM references actual business metrics in 100% of responses |
| #2 Business Persistence | Business data restored on re-login; no re-entry required |
| #3 Expenses in Forecast | Forecast p10/p50/p90 includes recurring expenses; shortfalls detected |
| #4 Audit Data | All business events logged to audit_log; chain integrity verified |
| #5 Working Capital | Dashboard displays liquidity, cash flow, expense breakdown, stress scenarios |

---

## Next Steps

1. **Prioritize**: Start with Issue #2 (persistence) — most critical for retention
2. **Communicate**: Share this roadmap with team; align on priorities
3. **Assign**: Distribute tasks across developers
4. **Build**: Follow Phase 1 → Phase 2 → Phase 3 sequence
5. **Review**: Checkpoint after each phase before proceeding
6. **Deploy**: Roll out incrementally; monitor audit logs and user feedback

---

**Document Version:** 1.0  
**Last Updated:** 2026-10-18  
**Author:** Kiro Analysis  
**Status:** Ready for Implementation
