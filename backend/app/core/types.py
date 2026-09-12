from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Integer
from sqlalchemy.types import TypeDecorator

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cents(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Money requires a finite Decimal, never a float")
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ValueError("Money cannot have fractions of a cent")
    if abs(scaled) > 10**14:
        raise ValueError("Money exceeds the supported range")
    return int(scaled)


class Money(TypeDecorator[Decimal]):
    """Python Decimal ↔ SQLite integer cents; no floating point conversion."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else cents(value)

    def process_result_value(self, value, dialect):
        return None if value is None else (Decimal(value) / 100).quantize(CENT)


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite stores naive UTC; callers always exchange timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("A timezone-aware datetime is required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)
