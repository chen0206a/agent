import hashlib
import hmac
import secrets
from datetime import timedelta

from app.core.errors import DomainError
from app.core.types import utcnow
from app.db.session import write_transaction
from app.models.auth import Account, LoginSession, LoginThrottle
from app.repositories.auth import AuthRepository


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=131072, r=8, p=1, maxmem=256 * 1024 * 1024
    ).hex()
    return f"scrypt${salt}${value}"


def verify_password(password, encoded):
    try:
        return hmac.compare_digest(password_hash(password, encoded.split("$")[1]), encoded)
    except (ValueError, IndexError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, sessions, clock=utcnow):
        self.sessions, self.clock = sessions, clock

    def create_account(self, username, password, role, user_id=None):
        if (
            role not in {"customer", "admin"}
            or (role == "customer" and user_id is None)
            or (role == "admin" and user_id is not None)
        ):
            raise ValueError("Invalid account role/user binding")
        if not 12 <= len(password) <= 128:
            raise ValueError("Password must contain 12–128 characters")
        with write_transaction(self.sessions) as session:
            if AuthRepository(session).account(username.lower()):
                raise ValueError("Account already exists; not overwriting credentials")
            row = Account(
                username=username.lower(), password_hash=password_hash(password), role=role, user_id=user_id
            )
            session.add(row)
            session.flush()
            return row

    def login(self, username, password, ip):
        now = self.clock()
        key = token_hash(ip)  # IP-wide limit prevents bypass by rotating usernames.
        denied = False
        with write_transaction(self.sessions) as session:
            throttle = session.get(LoginThrottle, key)
            if throttle and throttle.reset_at > now and throttle.attempts >= 10:
                raise DomainError("LOGIN_THROTTLED", "尝试次数过多，请15分钟后重试", 429)
            if not throttle:
                throttle = LoginThrottle(key=key, attempts=0, reset_at=now + timedelta(minutes=15))
                session.add(throttle)
            if throttle.reset_at <= now:
                throttle.attempts, throttle.reset_at = 0, now + timedelta(minutes=15)
            account = AuthRepository(session).account(username.lower())
            # Same expensive work for unknown accounts to reduce username timing leakage.
            valid = (
                verify_password(password, account.password_hash)
                if account
                else bool(password_hash(password)) and False
            )
            if not account or not account.active or not valid:
                throttle.attempts += 1
                denied = True
            else:
                throttle.attempts = 0
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                session.add(
                    LoginSession(
                        token_hash=token_hash(token),
                        account_id=account.id,
                        csrf_token=csrf,
                        expires_at=now + timedelta(hours=12),
                    )
                )
        if denied:
            raise DomainError("INVALID_CREDENTIALS", "账号或密码不正确", 401)
        return token, csrf, account

    def authenticate(self, token):
        if not token or len(token) > 200:
            raise DomainError("LOGIN_REQUIRED", "请先登录", 401)
        with self.sessions() as session:
            row, account = AuthRepository(session).session_account(token_hash(token))
            if not row or row.expires_at <= self.clock() or not account or not account.active:
                raise DomainError("SESSION_EXPIRED", "登录已失效，请重新登录", 401)
            return account, row.csrf_token

    def logout(self, token):
        with write_transaction(self.sessions) as session:
            row = session.get(LoginSession, token_hash(token))
            if row:
                session.delete(row)
