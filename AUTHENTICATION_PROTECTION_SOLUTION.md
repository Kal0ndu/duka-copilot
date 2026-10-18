# Authentication Protection Strategy — Complete Solution

## Problem Statement

Currently, users can potentially access app pages without logging in first. We need to enforce authentication at:
1. **Application Entry** — main.py
2. **Each Protected Page** — all dashboard pages
3. **Session State** — ensure auth token is always valid

---

## Current Authentication Architecture

### What's Already in Place ✅

**1. Auth UI Module** (`app/auth_ui.py`)
```python
def require_auth():
    """Gate: if not authenticated, show login prompt and stop rendering."""
    if not check_auth():
        st.warning("🔐 Please log in to access Duka.")
        st.markdown("[Log In](Login)  |  [Sign Up](Sign_Up)")
        st.stop()

def check_auth():
    """Return True if user is authenticated, False otherwise."""
    token = st.session_state.get("auth_token")
    if not token:
        return False
    session = decode_session(token)
    if not session:
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        return False
    return True
```

**2. Auth Middleware** (`auth/middleware.py`)
```python
def require_auth(page_func: Callable = None, *, redirect: bool = True):
    """Decorator: require authentication to view a page."""
    # Can be used as @require_auth decorator on page functions
```

**3. Session Management** (`auth/session_manager.py`)
```python
def create_session(user_id, business_id, display_name, role, phone_hash):
    """Create JWT session token."""
    # Returns signed JWT token with TTL

def decode_session(token):
    """Decode and verify JWT token."""
    # Returns session data if valid, None if expired/invalid
```

---

## Implementation Strategy

### Tier 1: Entry Point Protection (app/main.py) ✅ ALREADY DONE

The main.py file already has:
```python
from app.auth_ui import require_auth, render_logout_button, check_auth

# At the TOP of the page:
require_auth()  # ← This blocks rendering until user logs in
```

✅ **Status:** Users cannot access main.py without logging in.

---

### Tier 2: Page Protection (All Dashboard Pages)

**Currently implemented:**
- ✅ `8_POS_Dashboard.py`
- ✅ `9_Invoicing.py`
- ⚠️ Others may not have protection

**Action Required:** Add auth check to EVERY page:

```python
# At the TOP of each page (right after imports):
st.set_page_config(...)

from app.auth_ui import require_auth, check_auth

require_auth()  # ← Blocks rendering if not logged in
```

**Pages to protect:**
```
app/pages/
├── 0_Business_Setup.py          [ADD require_auth()]
├── 1_Upload_Statement.py        [ADD require_auth()]
├── 2_Analytics.py               [ADD require_auth()]
├── 3_Cashflow_Forecast.py       [ADD require_auth()]
├── 3_Financing.py               [ADD require_auth()]
├── 4_Party_Intelligence.py      [ADD require_auth()]
├── 5_Working_Capital.py         [ADD require_auth()]
├── 6_Spending_Advisor.py        [ADD require_auth()]
├── 7_Audit_and_Compliance.py    [ADD require_auth()]
├── 7_Financial_Health.py        [ADD require_auth()]
├── 8_POS_Dashboard.py           [✅ Has require_auth()]
├── 9_Invoicing.py               [✅ Has require_auth()]
├── 10_Inventory.py              [ADD require_auth()]
└── 11_Tax_Reports.py            [ADD require_auth()]
```

---

### Tier 3: Session Validation Middleware

**Current Implementation:**
```python
# auth/middleware.py
def load_user_context():
    """Load user context from auth token at app startup."""
    if not check_auth():
        return
    # Load user's business data into session
    st.session_state["business_id"] = ...
    st.session_state["user_profile"] = ...
```

**Enhancement Needed:**
Add periodic token refresh to prevent stale sessions:

```python
def validate_and_refresh_session():
    """Check if auth token is still valid; refresh if needed."""
    token = st.session_state.get("auth_token")
    
    if not token:
        return False  # Not logged in
    
    session = decode_session(token)
    
    if not session:
        # Token expired or invalid
        st.session_state.pop("auth_token", None)
        st.session_state.pop("auth_user", None)
        st.session_state.pop("business_id", None)
        return False
    
    # Token valid
    return True
```

---

### Tier 4: Public Pages (No Auth Required)

**Pages that should NOT require auth:**
```
app/pages/
├── Login.py              (user needs to log in)
├── Sign_Up.py            (user needs to sign up)
├── Reset_Password.py     (if exists)
└── Terms_and_Conditions (if exists)
```

**These pages do NOT get `require_auth()`**

---

## Implementation Checklist

### Phase 1: Immediate Protection (Next 15 minutes)

- [ ] Add `require_auth()` to all pages missing it
- [ ] Verify each page at top of file has:
  ```python
  from app.auth_ui import require_auth
  require_auth()
  ```
- [ ] Test: Try accessing pages without login (should redirect to login)
- [ ] Test: Log in and verify all pages now accessible

### Phase 2: Session Security (Next 30 minutes)

- [ ] Add session validation to middleware
- [ ] Implement token refresh on page load
- [ ] Add session timeout (default 24 hours)
- [ ] Test: Session expires after timeout
- [ ] Test: Session clears on logout

### Phase 3: Error Handling (Next 30 minutes)

- [ ] Catch auth errors and show friendly messages
- [ ] Handle network errors during auth
- [ ] Prevent redirect loops
- [ ] Test: Try accessing API directly (should fail)

---

## Code Template for Page Protection

**Copy-paste this at the TOP of each page that needs protection:**

```python
"""Page X: [Your Page Title] — [Description]."""
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ---- Authentication Gate ----
from app.auth_ui import require_auth, check_auth, render_logout_button

st.set_page_config(page_title="[Title]", page_icon="[ICON]", layout="wide")

# BLOCK rendering if not logged in
require_auth()

# ---- Now safe to access session state ----
from app.session_helpers import SessionManager

SessionManager.init_session()
profile = SessionManager.get_profile()
biz_id = profile.get("business_id", 1) if profile else 1

# Rest of page code...
```

---

## Authentication Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    User Visits App                       │
└─────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────┐
│         main.py: require_auth() called                  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Check: st.session_state.get("auth_token")?       │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           ↓
         ┌─────────────────┴─────────────────┐
         ↓                                     ↓
    [Token Found]                       [No Token]
         ↓                                     ↓
  [Verify Token]                    [Show Login Page]
         ↓                                     ↓
  ┌──────────────────┐                [st.stop()]
  │ Valid? → Continue│
  │ Expired? → Clear │
  │ Invalid? → Clear │
  └──────────────────┘
         ↓
  [Load User Context]
         ↓
  [Render Page with require_auth()]
         ↓
         ↓
  ┌──────────────────────────────────────────────┐
  │ User Logs Out: Clear token & redirect to Login
  └──────────────────────────────────────────────┘
```

---

## Security Considerations

### 1. Token Storage ✅
- Tokens stored in `st.session_state` (in-memory, secure)
- NOT stored in cookies or localStorage
- Cleared on page refresh (forces re-login)

### 2. Token Validation ✅
- JWT signed with secret key
- Decoded on each access
- Expiration checked (default 24 hours)

### 3. Session Hijacking Prevention
- Token is short-lived (24 hours)
- Tied to user_id (cannot steal another user's token)
- Use HTTPS in production (Streamlit Cloud handles this)

### 4. Bypass Prevention
- Direct URL access blocked by `require_auth()`
- Cannot skip by modifying session state (token must be valid)
- API calls would need valid token in header

---

## Testing Checklist

### Test 1: Unauthenticated Access
```
Steps:
1. Clear cookies/cache
2. Open http://localhost:8501/app/pages/8_POS_Dashboard
Expected: Redirected to login page
Result: ✓ PASS / ✗ FAIL
```

### Test 2: Login Flow
```
Steps:
1. Open login page
2. Enter phone + OTP
3. Click "Log In"
Expected: Redirected to dashboard
Result: ✓ PASS / ✗ FAIL
```

### Test 3: Page Access After Login
```
Steps:
1. Log in successfully
2. Navigate to all pages using sidebar
Expected: All pages load without blocking
Result: ✓ PASS / ✗ FAIL
```

### Test 4: Logout
```
Steps:
1. Click "Log Out" button
2. Try to access dashboard
Expected: Redirected to login page
Result: ✓ PASS / ✗ FAIL
```

### Test 5: Token Expiration
```
Steps:
1. Log in
2. Wait 24 hours (or manually set expired token)
3. Refresh page
Expected: Session cleared, redirected to login
Result: ✓ PASS / ✗ FAIL
```

### Test 6: Malicious Token
```
Steps:
1. Manually set invalid token: st.session_state["auth_token"] = "fake_token"
2. Refresh page
Expected: Token rejected, redirected to login
Result: ✓ PASS / ✗ FAIL
```

---

## Deployment Checklist

Before going to production:

- [ ] All pages have `require_auth()` at top
- [ ] Session timeout is set (24 hours minimum)
- [ ] Token is signed with strong secret (not hardcoded)
- [ ] HTTPS enforced (Streamlit Cloud does this)
- [ ] Logout button clears ALL session data
- [ ] Error messages don't leak sensitive info
- [ ] Redirect after login points to correct page
- [ ] Redirect after logout points to login page
- [ ] No page is accessible without token
- [ ] All auth tests pass

---

## Quick Implementation (5-minute fix)

**For IMMEDIATE protection, add this to the 10 unprotected pages:**

**File: app/pages/0_Business_Setup.py** (add after imports)
```python
from app.auth_ui import require_auth
require_auth()
```

**File: app/pages/1_Upload_Statement.py** (add after imports)
```python
from app.auth_ui import require_auth
require_auth()
```

**Repeat for all other pages...**

---

## Recommended Reading Order

1. This file (you are here) — Understand the strategy
2. `app/auth_ui.py` — See `require_auth()` implementation
3. `auth/session_manager.py` — See token management
4. `auth/middleware.py` — See middleware implementation

---

## Troubleshooting

### "Page is blank after login"
**Cause:** `require_auth()` called but auth is somehow failing
**Fix:** Check `st.session_state.get("auth_token")` in browser console

### "Infinite redirect loop"
**Cause:** Login page also has `require_auth()`
**Fix:** Login/SignUp pages should NOT have `require_auth()`

### "Token always expired"
**Cause:** Session secret changed or system clock is wrong
**Fix:** Verify secret key in `session_manager.py`, check server time

### "Can access page without login"
**Cause:** Page doesn't have `require_auth()`
**Fix:** Add `require_auth()` to that page

---

**Status:** Ready to implement  
**Estimated Time:** 15-30 minutes for full protection  
**Risk:** Low (only affects UI access, not data)  
**Priority:** HIGH (security-critical)
