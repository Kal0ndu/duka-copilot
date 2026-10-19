"""Roles (single admin), admin-only audit access, security events, login
lockout, session revocation and per-user isolation of the AI's context."""
import json
import sqlite3
import types
from datetime import datetime, timedelta

import pytest

from auth import rbac
from auth.session_manager import create_session, decode_session, is_jti_revoked, revoke_jti
from tests.fixtures_duka import build_world


@pytest.fixture
def world(tmp_path):
    w = build_world(tmp_path)
    from db.migrate import ensure_006
    ensure_006(w.db)
    return w


def _events(db, event_type):
    with sqlite3.connect(db) as conn:
        return [json.loads(r[0]) | {"decision": r[1]} for r in conn.execute(
            "SELECT details_json, decision FROM audit_log WHERE event_type = ?", (event_type,))]


def test_new_accounts_are_users(world):
    assert rbac.get_account_role(world.db, world.amina_user) == "user"
    assert not rbac.is_admin(world.db, world.other_user)


def test_only_one_admin(world):
    rbac.assign_admin(world.db, world.amina_user)
    assert rbac.is_admin(world.db, world.amina_user)
    with pytest.raises(rbac.PrivilegeEscalationBlocked):
        rbac.assign_admin(world.db, world.other_user)
    assert not rbac.is_admin(world.db, world.other_user)
    assert _events(world.db, "PRIVILEGE_ESCALATION_BLOCKED")[0]["decision"] == "blocked"
    # The database refuses a second admin even if app code is bypassed.
    with sqlite3.connect(world.db) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE app_user SET account_role = 'admin' WHERE user_id = ?", (world.other_user,))
    # ...and an account can never be created as admin.
    with sqlite3.connect(world.db) as conn, pytest.raises(sqlite3.IntegrityError, match="cannot be created"):
        conn.execute("INSERT INTO app_user (phone_hash, display_name, display_token, account_role) "
                     "VALUES ('h', 'x', 'x', 'admin')")


def test_admin_transfer(world):
    rbac.assign_admin(world.db, world.amina_user)
    rbac.assign_admin(world.db, world.other_user, transfer=True)
    assert rbac.is_admin(world.db, world.other_user) and not rbac.is_admin(world.db, world.amina_user)


def test_audit_reads_are_admin_only_and_denials_logged(world):
    svc = rbac.AdminAuditService(world.db)
    for call in (svc.recent_events, svc.security_events, svc.verify_chain, svc.summary, svc.accounts):
        with pytest.raises(rbac.AccessDenied) as e:
            call(world.other_user)
        assert str(e.value) == rbac.DENIED_MESSAGE   # nothing about what exists
    with pytest.raises(rbac.AccessDenied):
        svc.recent_events(None)
    denied = _events(world.db, "UNAUTHORIZED_ACCESS")
    assert len(denied) == 6 and {d["user_id"] for d in denied} == {world.other_user, None}

    rbac.assign_admin(world.db, world.amina_user)
    assert any(e["event_type"] == "UNAUTHORIZED_ACCESS" for e in svc.security_events(world.amina_user))
    assert svc.verify_chain(world.amina_user)["valid"]


def test_a_forged_role_in_the_token_does_not_grant_admin(world):
    token = create_session(world.other_user, world.other, "Grace", role="admin")
    assert decode_session(token).role == "admin"
    with pytest.raises(rbac.AccessDenied):
        rbac.require_admin(world.db, decode_session(token).user_id, "audit_log")


def test_login_lockout_after_repeated_failures(world):
    for _ in range(rbac.MAX_FAILED_LOGINS - 1):
        rbac.log_security_event(world.db, "LOGIN_FAILED", user_id=world.amina_user, outcome="denied",
                                detection="password check failed", handling="login refused")
    assert not rbac.login_locked(world.db, world.amina_user)
    rbac.log_security_event(world.db, "LOGIN_FAILED", user_id=world.amina_user, outcome="denied",
                            detection="password check failed", handling="login refused")
    assert rbac.login_locked(world.db, world.amina_user)
    assert not rbac.login_locked(world.db, world.other_user)
    assert not rbac.login_locked(world.db, world.amina_user, now=datetime.utcnow() + rbac.LOGIN_LOCKOUT + timedelta(seconds=2))


def test_logout_revokes_the_token(world):
    s = decode_session(create_session(world.amina_user, world.amina, "Amina"))
    assert not is_jti_revoked(world.db, s)
    revoke_jti(world.db, s)
    assert is_jti_revoked(world.db, s)


def test_security_events_record_detection_and_handling(world):
    rbac.log_security_event(world.db, "LOGIN_FAILED", user_id=world.amina_user, outcome="denied",
                            detection="otp check failed", handling="login refused", resource="login")
    e = _events(world.db, "LOGIN_FAILED")[0]
    assert (e["detection"], e["handling"], e["resource"], e["decision"]) == \
        ("otp check failed", "login refused", "login", "denied")


def test_injection_in_a_statement_is_a_security_event(tmp_path):
    w = build_world(tmp_path, statement="malicious_statement.csv")
    e = _events(w.db, "INJECTION_DETECTED")
    assert e and e[0]["decision"] == "blocked" and "injection" in e[0]["detection"]


# ---- the AI's context is per user ----

def _orch(world, captured):
    from agent.orchestrator import Orchestrator
    from core.config import Config
    cfg = types.SimpleNamespace(**{k: getattr(Config, k) for k in dir(Config) if k.isupper()})
    cfg.DB_PATH, cfg.LLM_API_KEY, cfg.caps_minor = world.db, "test-key", Config.caps_minor
    o = Orchestrator(cfg)
    o.llm.structured = lambda msgs, schema=None: (captured.append(msgs), {"final": True, "response": "ok"})[1]
    return o


def test_context_is_the_users_own_business(world):
    from auth.user_context import UserContext
    ctx = UserContext(world.amina_user, world.amina, world.db).refresh()
    assert ctx["business_summary"]["name"] == "Amina Grocery"
    assert ctx["business_summary"]["sector"] == "grocery"
    assert ctx["summary"]["transaction_count"] > 0


def test_cannot_load_another_users_business(world):
    from auth.user_context import ContextAccessDenied, UserContext
    with pytest.raises(ContextAccessDenied):
        UserContext(world.other_user, world.amina, world.db).get()
    assert _events(world.db, "UNAUTHORIZED_ACCESS")[0]["resource"] == f"business:{world.amina}"


def test_orchestrator_refuses_foreign_business(world):
    captured = []
    r = _orch(world, captured).process("How is my business?", user_id=world.other_user, business_id=world.amina)
    assert r["blocked"] and r["error"] == "access_denied"
    assert captured == []          # nothing about Amina's business went to the AI


def test_conversation_does_not_leak_to_next_user(world):
    captured = []
    o = _orch(world, captured)
    o.process("My secret supplier is ACME", user_id=world.amina_user, business_id=world.amina)
    o.process("hello", user_id=world.other_user, business_id=world.other)
    prompt = json.dumps(captured[-1])
    assert "ACME" not in prompt and "Amina Grocery" not in prompt and "Grace Salon" in prompt
