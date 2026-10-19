"""Make one account the Duka administrator (server-side only).

    python scripts/set_admin.py 0712345678              # first admin
    python scripts/set_admin.py 0712345678 --transfer   # hand over from the current admin
    python scripts/set_admin.py --show                  # who is the admin

There is exactly one admin. The app has no screen that changes roles; this
script needs shell access to the server and the database file.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth.phone_utils import hash_phone, normalise_phone
from auth.rbac import PrivilegeEscalationBlocked, assign_admin
from core.config import Config
from db.migrate import ensure_006
from db.users import get_user_id_by_phone_hash


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("phone", nargs="?", help="the account's registered phone number")
    p.add_argument("--transfer", action="store_true", help="replace the current admin")
    p.add_argument("--show", action="store_true", help="print the current admin and exit")
    p.add_argument("--db", default=Config.DB_PATH)
    a = p.parse_args()

    ensure_006(a.db)
    if a.show or not a.phone:
        with sqlite3.connect(a.db) as conn:
            row = conn.execute(
                "SELECT user_id, display_name FROM app_user WHERE account_role = 'admin'").fetchone()
        print(f"Admin: user {row[0]} ({row[1]})" if row else "No admin set.")
        return 0

    user_id = get_user_id_by_phone_hash(a.db, hash_phone(normalise_phone(a.phone)))
    if user_id is None:
        print("No account with that phone number. Sign up in the app first.", file=sys.stderr)
        return 1
    try:
        assign_admin(a.db, user_id, transfer=a.transfer)
    except PrivilegeEscalationBlocked as e:
        print(e, file=sys.stderr)
        return 2
    print(f"User {user_id} is now the admin (the Admin Security page checks the role on every load).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
