"""A user sets up their business once; later logins find it again."""
import sqlite3

import pytest

from core.business_setup import BusinessSetup
from db.migrate import MigrationRunner


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "duka.db")
    runner = MigrationRunner(path)
    runner.load_base_schema_if_needed()
    runner.init_schema_tracking()
    runner.run_pending()
    return path


def _add_user(db_path, phone_hash):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "INSERT INTO app_user (phone_hash, display_name, display_token) VALUES (?, 'Owner', 'TOK')",
            (phone_hash,),
        ).lastrowid


def test_new_user_has_no_business(db_path):
    uid = _add_user(db_path, "hash-a")
    assert BusinessSetup(db_path).get_business_for_user(uid) is None


def test_registered_business_is_found_on_next_login(db_path):
    uid = _add_user(db_path, "hash-a")
    setup = BusinessSetup(db_path)
    bid = setup.register_business("Mama Jane", "grocery", owner_user_id=uid)

    # A fresh BusinessSetup stands in for a new login session.
    assert BusinessSetup(db_path).get_business_for_user(uid) == bid

    with sqlite3.connect(db_path) as conn:
        owner = conn.execute(
            "SELECT owner_user_id, owner_phone_hash FROM business WHERE business_id = ?", (bid,)
        ).fetchone()
        role = conn.execute(
            "SELECT role FROM business_member WHERE business_id = ? AND user_id = ?", (bid, uid)
        ).fetchone()
    assert owner == (uid, "hash-a")
    assert role == ("owner",)


def test_businesses_are_not_shared_between_users(db_path):
    a = _add_user(db_path, "hash-a")
    b = _add_user(db_path, "hash-b")
    setup = BusinessSetup(db_path)
    bid_a = setup.register_business("Shop A", "kiosk", owner_user_id=a)
    assert setup.get_business_for_user(b) is None
    bid_b = setup.register_business("Shop B", "salon", owner_user_id=b)
    assert setup.get_business_for_user(a) == bid_a
    assert setup.get_business_for_user(b) == bid_b


def test_profile_can_be_updated_later(db_path):
    uid = _add_user(db_path, "hash-a")
    setup = BusinessSetup(db_path)
    bid = setup.register_business("Mama Jane", "grocery", owner_user_id=uid)

    setup.update_business_profile(
        bid, name="Mama Jane Wholesale", sector="retail", sub_sector="cereals",
        employee_count=4, registration_type="sole_proprietor",
    )

    profile = setup.get_business_profile(bid)
    assert profile.name_token == "Mama Jane Wholesale"
    assert profile.sector == "retail"
    assert profile.sub_sector == "cereals"
    assert profile.employee_count == 4
    assert profile.registration_type == "sole_proprietor"
    assert setup.get_business_for_user(uid) == bid


def test_unknown_owner_is_rejected(db_path):
    with pytest.raises(ValueError):
        BusinessSetup(db_path).register_business("Ghost", "other", owner_user_id=999)
