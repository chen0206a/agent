from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import auth as _auth  # noqa: F401 -- register additive auth tables
from app.models.entities import Base


def make_engine(url: str) -> Engine:
    if not url.startswith("sqlite:"):
        raise ValueError("This release supports SQLite only")
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()

    return engine


def initialize(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@contextmanager
def write_transaction(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions() as session:
        # Acquire the SQLite writer lock BEFORE reading refundable balances.
        # Check + reserve + audit commit atomically, including across processes.
        session.execute(text("BEGIN IMMEDIATE"))
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
