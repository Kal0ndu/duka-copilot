from datetime import datetime

import pytest

import settings
from categoriser import categorise, payee_key
from security import ApprovalError, Approvals, PolicyGuard
from settings import (defaults, forget, learn, needs_pin, policy_from, profile_from,
                      safety_buffer, validate)


# --- safety buffer ---

@pytest.mark.parametrize("business", ["amina_grocery", "grace_salon", "otieno_transport"])
def test_default_buffer_is_1000(business):
    assert safety_buffer(defaults(business)) == 1_000


@pytest.mark.parametrize("value", [0, 500, 10_000])
def test_owner_buffer_any_value_from_zero(value):
    cfg = dict(defaults("amina_grocery"), safety_buffer=value)
    assert safety_buffer(cfg) == value                  # 0 stays 0, not the default
    assert not validate(cfg)


def test_old_files_without_a_buffer_get_1000():
    assert safety_buffer(dict(defaults("amina_grocery"), safety_buffer=None)) == 1_000


def test_negative_buffer_refused():
    assert validate(dict(defaults("amina_grocery"), safety_buffer=-1))


# --- settings file and checks ---

def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_DIR", tmp_path)
    cfg = dict(defaults("grace_salon"), payday="Fri", daily_cap=45_000)
    settings.save_settings("grace_salon", cfg)
    assert settings.load_settings("grace_salon") == cfg


def test_missing_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_DIR", tmp_path)
    assert settings.load_settings("otieno_transport") == defaults("otieno_transport")


@pytest.mark.parametrize("change", [
    {"daily_cap": 1_000},                                    # below the per-payment cap
    {"per_transaction_cap": -5},
    {"payday": "Someday"},
    {"verified_payees": {"0799123456": "ATTACKER"}},         # not an ID like SUP-01
    {"verified_payees": {"SUP-09": ""}},
    {"learned_rules": [{"match": "x", "category": "sales"}]},
    {"learned_rules": [{"match": "peter", "category": "free_money"}]},
])
def test_invalid_settings_refused(change):
    assert validate(dict(defaults("amina_grocery"), **change))


def test_caps_and_payees_need_pin_but_sector_does_not():
    old = defaults("amina_grocery")
    assert needs_pin(old, dict(old, daily_cap=90_000))
    assert needs_pin(old, dict(old, verified_payees={**old["verified_payees"], "SUP-04": "X"}))
    assert not needs_pin(old, dict(old, sector="kiosk", payday="Sat", safety_buffer=5_000))


def test_new_caps_reach_the_guard():
    guard = PolicyGuard(policy_from(dict(defaults("amina_grocery"), per_transaction_cap=10_000)))
    assert not guard.check({"type": "pay_supplier", "payee_id": "SUP-01", "amount": 10_001}).allowed


def test_settings_pin_check_shares_the_lockout():
    ap = Approvals("2468")
    ap.check_pin("2468")
    for pin in ("1", "2", "3"):
        with pytest.raises(ApprovalError):
            ap.check_pin(pin)
    with pytest.raises(ApprovalError, match="locked"):
        ap.check_pin("2468")


# --- payday and "teach it once" ---

def transfer(name, when=datetime(2026, 10, 10, 19, 0)):      # a Saturday evening
    return {"details": f"Customer Transfer to 0712***345 - {name}", "money_in": 0.0,
            "money_out": 5_000.0, "time": when}


def test_payday_setting_controls_wages():
    t = transfer("PETER NJERI")
    assert categorise(t, profile=profile_from(dict(defaults("amina_grocery"), payday="Sat")))[0] == "wages"
    assert categorise(t, profile=profile_from(defaults("amina_grocery")))[0] == "family_transfer"


def test_payee_key():
    assert payee_key("Pay Bill to 123 - SOKO SUPPLIES Acc. 9") == "soko supplies"
    assert payee_key("Customer Transfer to 0712***345 - PETER  Njeri") == "peter njeri"


def test_teach_it_once_beats_built_in_rules():
    cfg = learn(defaults("amina_grocery"), "Customer Transfer to 0799***111 - PETER NJERI", "wages")
    assert cfg["learned_rules"] == [{"match": "peter njeri", "category": "wages"}]
    later = transfer("Peter Njeri", when=datetime(2026, 10, 14, 9, 0))   # other phone, Tuesday
    assert categorise(later, learned=cfg["learned_rules"]) == ("wages", "owner")
    assert categorise(transfer("MARY NJERI"), learned=cfg["learned_rules"])[0] == "family_transfer"


def test_relearning_replaces_and_forget_removes():
    cfg = learn(defaults("amina_grocery"), "peter njeri", "wages")
    cfg = learn(cfg, "PETER NJERI", "family_transfer")
    assert cfg["learned_rules"] == [{"match": "peter njeri", "category": "family_transfer"}]
    assert forget(cfg, "peter njeri")["learned_rules"] == []
    assert defaults("amina_grocery")["learned_rules"] == []                # not changed
