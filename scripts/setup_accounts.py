"""Interactive local account provisioning; never saves or prints plaintext passwords."""

import argparse
from getpass import getpass

from app.core.config import Settings
from app.db.session import initialize, make_engine, make_sessions
from app.models.auth import Account
from app.models.entities import User
from app.services.auth import AuthService
from sqlalchemy import select


def main():
    parser = argparse.ArgumentParser(description="Create local accounts with individually chosen passwords.")
    parser.add_argument("--user-id", type=int, nargs="+", default=[1, 3, 4, 6, 10])
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings.resolved_database_url)
    try:
        initialize(engine)
        sessions = make_sessions(engine)
        with sessions() as session:
            users = set(session.scalars(select(User.id)))
            accounts = list(session.scalars(select(Account)))
        requested = list(dict.fromkeys(args.user_id))
        if not set(requested).issubset(users):
            raise SystemExit("A requested user does not exist. Run init-db and seed first.")
        existing_names = {a.username for a in accounts}
        bound_users = {a.user_id for a in accounts}
        pending = [
            (f"customer{uid}", "customer", uid)
            for uid in requested
            if uid not in bound_users and f"customer{uid}" not in existing_names
        ]
        if "admin" not in existing_names:
            pending.append(("admin", "admin", None))
        credentials = []
        for username, role, uid in pending:
            password = getpass(f"{username} password (12-128 characters): ")
            if password != getpass("Confirm password: ") or not 12 <= len(password) <= 128:
                raise SystemExit("Invalid password or confirmation mismatch; nothing changed.")
            if any(password == row[1] for row in credentials):
                raise SystemExit("Use a different password for each account; nothing changed.")
            credentials.append((username, password, role, uid))
        auth = AuthService(sessions)
        for values in credentials:
            auth.create_account(*values)
            print(f"Created {values[0]} (salted password hash stored).")
        print("Existing accounts and credentials were preserved.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
