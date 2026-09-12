from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import UTCDateTime, utcnow
from app.models.entities import Base


class Account(Base):
    __tablename__ = "auth_accounts"
    __table_args__ = (
        CheckConstraint("role IN ('customer','admin')"),
        CheckConstraint(
            "(role = 'customer' AND user_id IS NOT NULL) OR (role = 'admin' AND user_id IS NULL)"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    active: Mapped[bool] = mapped_column(default=True)


class LoginSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("auth_accounts.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LoginThrottle(Base):
    __tablename__ = "auth_throttles"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)
    reset_at: Mapped[datetime] = mapped_column(UTCDateTime())
