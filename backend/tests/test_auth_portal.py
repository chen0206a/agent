from datetime import timedelta

import pytest
from app.core.types import utcnow
from app.db.session import write_transaction
from app.models.auth import Account, LoginSession
from app.services.auth import password_hash, token_hash, verify_password
from app.services.portal import public_trace
from sqlalchemy import select


def test_password_hash_is_salted_and_verifiable():
    first, second = password_hash("long-test-password"), password_hash("long-test-password")
    assert first != second and "long-test-password" not in first
    assert verify_password("long-test-password", first)
    assert not verify_password("wrong", first)


def test_login_cookie_me_logout_and_replay(client, application):
    application.state.auth.create_account("alice", "long-test-password", "customer", 1)
    bad = client.post("/auth/login", json={"username": "alice", "password": "wrong"})
    assert bad.status_code == 401 and "wrong" not in bad.text
    response = client.post("/auth/login", json={"username": "alice", "password": "long-test-password"})
    assert response.status_code == 200
    assert (
        "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
    )
    csrf, cookie = response.json()["csrf_token"], client.cookies.get("asc_session")
    assert client.get("/auth/me").json()["user_id"] == 1
    assert client.post("/auth/logout").status_code == 403
    assert client.post("/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/auth/me", headers={"Cookie": f"asc_session={cookie}"}).status_code == 401


def test_demo_headers_cannot_authenticate_or_override_role(client, auth_headers):
    assert client.get("/approvals", headers={"X-Demo-Role": "admin"}).status_code == 401
    headers = {**auth_headers(1), "X-Demo-Role": "admin", "X-Demo-User-Id": "2"}
    assert client.get("/approvals", headers=headers).status_code == 403
    assert client.get("/orders/1002", headers=headers).status_code == 403
    assert client.get("/auth/me", headers=headers).json()["user_id"] == 1


def test_csrf_and_untrusted_origin_rejected(client, auth_headers):
    headers = auth_headers(1)
    body = {"message": "test", "idempotency_key": "csrf-test"}
    assert client.post("/agent/runs", headers={"Cookie": headers["Cookie"]}, json=body).status_code == 403
    assert (
        client.post(
            "/agent/runs", headers={**headers, "Origin": "https://evil.invalid"}, json=body
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/auth/login", headers={"Origin": "https://evil.invalid"}, json={"username": "x", "password": "x"}
        ).status_code
        == 403
    )


def test_expired_session_and_disabled_account(client, auth_headers, sessions):
    headers = auth_headers(1)
    with write_transaction(sessions) as session:
        row = session.get(LoginSession, token_hash(headers["Cookie"].split("=", 1)[1]))
        row.expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/auth/me", headers=headers).status_code == 401
    second = auth_headers(2)
    with write_transaction(sessions) as session:
        session.scalar(select(Account).where(Account.user_id == 2)).active = False
    assert client.get("/auth/me", headers=second).status_code == 401


def test_login_throttle_and_mass_assignment(client):
    for _ in range(10):
        assert (
            client.post("/auth/login", json={"username": "unknown", "password": "wrong"}).status_code == 401
        )
    assert client.post("/auth/login", json={"username": "different", "password": "wrong"}).status_code == 429
    assert (
        client.post("/auth/login", json={"username": "x", "password": "x", "role": "admin"}).status_code
        == 422
    )


@pytest.mark.parametrize("path", ["/portal/dashboard", "/approvals", "/agent/runs/1/trace"])
def test_admin_reads_are_rejected_for_customers(client, auth_headers, path):
    assert client.get(path, headers=auth_headers(1)).status_code == 403


@pytest.mark.parametrize(
    "path", ["/approvals/1/review", "/actions/1/return-receipt", "/actions/1/simulate-execution"]
)
def test_admin_mutations_are_rejected_for_customers(client, auth_headers, path):
    body = (
        {"approve": True, "reason": "test"}
        if "review" in path
        else {"note": "test"}
        if "receipt" in path
        else {}
    )
    assert client.post(path, headers=auth_headers(1), json=body).status_code == 403


def test_dashboard_empty_data_and_trace_projection(client, admin_headers):
    metrics = client.get("/portal/dashboard", headers=admin_headers).json()
    assert metrics["total_runs"] == 0 and metrics["automation_rate"] == 0
    assert metrics["avg_latency_ms"] == 0 and metrics["unknown_usage_calls"] == 0
    data = {
        "messages": [{"role": "system", "content": "secret prompt"}, {"role": "user", "content": "你好"}],
        "response": {"reasoning_content": "private", "content": "hello"},
    }
    assert public_trace(data) == {
        "messages": [{"role": "user", "content": "你好"}],
        "response": {"content": "hello"},
    }


def test_run_list_nonempty_scoping_and_live_usage_metrics(client, application, auth_headers, admin_headers):
    from app.agent.evaluation import case_provider
    from app.models.entities import ModelCall

    application.state.agent.provider_factory = lambda: case_provider(
        {"order_id": 1001, "message": "取消", "issue": "CANCEL", "action": "CANCEL_AND_REFUND"}
    )
    headers = auth_headers(1)
    result = client.post(
        "/agent/runs",
        headers=headers,
        json={"message": "取消订单1001", "order_id": 1001, "idempotency_key": "portal-regression"},
    ).json()
    runs = client.get("/portal/runs", headers=headers)
    assert runs.status_code == 200 and runs.json()[0]["id"] == result["run_id"]
    assert client.get("/portal/runs", headers=auth_headers(2)).json() == []
    assert client.get("/portal/actions", headers=auth_headers(2)).json() == []
    assert client.get("/portal/actions?status=WAITING_APPROVAL", headers=headers).json() == []
    assert len(client.get("/portal/actions?status=READY", headers=headers).json()) == 1
    dashboard = client.get("/portal/dashboard", headers=admin_headers).json()
    assert dashboard["total_runs"] == 1 and dashboard["successful_runs"] == 1
    assert dashboard["automation_rate"] == 1 and dashboard["avg_tool_calls"] == 4
    assert dashboard["input_tokens"] == 0
    # Unknown live usage is counted explicitly, never presented as zero known usage.
    with write_transaction(application.state.sessions) as session:
        session.add(
            ModelCall(
                agent_run_id=result["run_id"],
                sequence=99,
                is_live=True,
                model="test-accounting",
                request_json={},
                status="FAILED",
            )
        )
    assert client.get("/portal/dashboard", headers=admin_headers).json()["unknown_usage_calls"] == 1
