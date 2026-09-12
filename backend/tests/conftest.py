from datetime import datetime, timezone

import pytest
from app.core.config import Settings
from app.db.seed import seed
from app.db.session import initialize
from app.main import create_app
from fastapi.testclient import TestClient

NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def application(tmp_path):
    settings = Settings(database_url="sqlite:///" + (tmp_path / "test.db").as_posix(), _env_file=None)
    app = create_app(settings, clock=lambda: NOW)
    initialize(app.state.engine)
    seed(app.state.sessions, now=NOW)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def sessions(application):
    return application.state.sessions


@pytest.fixture
def business(application):
    return application.state.business


@pytest.fixture
def workflow(application):
    return application.state.workflow


@pytest.fixture
def client(application):
    with TestClient(application, client=("127.0.0.1", 50000)) as result:
        yield result


@pytest.fixture
def admin_headers(auth_headers):
    return auth_headers(None)


@pytest.fixture
def auth_headers(application):
    from app.db.session import write_transaction
    from app.models.auth import Account
    from app.services.auth import password_hash

    cache = {}

    def headers(user_id=1):
        if user_id in cache:
            return cache[user_id]
        username = f"customer{user_id}" if user_id else "test-reviewer"
        password = "Test-only-password-42"
        with write_transaction(application.state.sessions) as session:
            session.add(
                Account(
                    username=username,
                    user_id=user_id,
                    role="customer" if user_id else "admin",
                    password_hash=password_hash(password),
                )
            )
        token, csrf, _ = application.state.auth.login(username, password, "127.0.0.1")
        cache[user_id] = {"Cookie": f"asc_session={token}", "X-CSRF-Token": csrf}
        return cache[user_id]

    return headers
