"""Login/sign-up codes: a phone can log in more than once, and a correct code verifies."""
from auth.otp_service import store_otp, verify_otp
from db.migrate import MigrationRunner


def _db(tmp_path):
    db = str(tmp_path / "duka.db")
    MigrationRunner(db).run_pending()
    return db


def test_same_phone_can_get_a_second_code(tmp_path):
    db = _db(tmp_path)
    assert store_otp(db, "h1", "111111", "login")
    assert store_otp(db, "h1", "222222", "login")          # used to crash (UNIQUE)
    assert not verify_otp(db, "h1", "111111", "login").success   # old code replaced
    assert verify_otp(db, "h1", "222222", "login").success


def test_code_verifies_once(tmp_path):
    db = _db(tmp_path)
    store_otp(db, "h2", "123456", "signup")
    assert verify_otp(db, "h2", "123456", "signup").success        # used to say "Database error"
    assert not verify_otp(db, "h2", "123456", "signup").success    # can't be reused


def test_wrong_code_counts_attempts(tmp_path):
    db = _db(tmp_path)
    store_otp(db, "h3", "123456", "login")
    r = verify_otp(db, "h3", "000000", "login")
    assert not r.success and r.remaining_attempts == 2
