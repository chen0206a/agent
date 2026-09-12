from sqlalchemy import select

from app.models.auth import Account, LoginSession


class AuthRepository:
    def __init__(self, session):
        self.session = session

    def account(self, username):
        return self.session.scalar(select(Account).where(Account.username == username))

    def session_account(self, token_hash):
        row = self.session.get(LoginSession, token_hash)
        return (row, self.session.get(Account, row.account_id)) if row else (None, None)
