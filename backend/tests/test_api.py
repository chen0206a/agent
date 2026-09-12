import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/users/1",
        "/users/1/orders",
        "/orders/1001",
        "/orders/1001/items",
        "/orders/1001/shipment",
        "/orders/1007/refunds",
        "/tickets/1",
        "/tickets",
        "/approvals",
        "/openapi.json",
    ],
)
def test_get_routes(client, admin_headers, path):
    response = client.get(path, headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["X-Request-Id"]


def test_money_serialization_and_unshipped_null(client, admin_headers):
    response = client.get("/orders/1001", headers=admin_headers)
    assert response.json()["paid_amount"] == "112.97"
    assert response.json()["created_at"].endswith("Z")
    assert client.get("/orders/1001/shipment", headers=admin_headers).json() is None


@pytest.mark.parametrize(
    "path",
    ["/users/999", "/orders/999", "/orders/999/items", "/tickets/999", "/actions/999", "/approvals/999"],
)
def test_api_not_found_and_error_contract(client, admin_headers, path):
    response = client.get(path, headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]
    assert "traceback" not in response.text.lower()


def test_identity_ownership_and_admin_boundaries(client, auth_headers):
    assert client.get("/users/1").status_code == 401
    headers = auth_headers(1)
    assert client.get("/users/2", headers=headers).status_code == 403
    assert client.get("/orders/1002", headers=headers).status_code == 403
    assert client.get("/approvals", headers=headers).status_code == 403
    assert client.get("/users/1", headers=headers).status_code == 200
    for row in client.get("/tickets", headers=headers).json():
        assert row["user_id"] == 1
    assert (
        client.post(
            "/tickets",
            headers=headers,
            json={"user_id": 2, "order_id": 1002, "issue_type": "CANCEL", "description": "非法代他人提交"},
        ).status_code
        == 403
    )


def test_remote_connection_cannot_use_demo_headers(application, admin_headers):
    with TestClient(application, client=("192.0.2.10", 50000)) as remote:
        assert remote.get("/users/1", headers=admin_headers).status_code == 403


def test_optional_token_and_uninitialized_health(tmp_path, admin_headers):
    app = create_app(
        Settings(
            database_url="sqlite:///" + (tmp_path / "empty.db").as_posix(),
            demo_api_token="test-secret",
            _env_file=None,
        )
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/users/1").status_code == 401
        assert (
            client.get("/users/1", headers={**admin_headers, "X-Demo-Token": "test-secret"}).status_code
            == 503
        )


def test_post_ticket_validation_and_mass_assignment_rejected(client, admin_headers):
    body = {"user_id": 1, "order_id": 1001, "issue_type": "CANCEL", "description": "取消订单"}
    created = client.post("/tickets", headers=admin_headers, json=body)
    assert created.status_code == 201
    assert created.json()["status"] == "OPEN"
    for changes in ({"status": "RESOLVED"}, {"user_id": True}, {"description": " "}, {"issue_type": "BAD"}):
        result = client.post("/tickets", headers=admin_headers, json={**body, **changes})
        assert result.status_code == 422
        assert result.json()["error"]["code"] == "VALIDATION_ERROR"


def test_api_high_amount_approval_and_simulated_execution(client, admin_headers, auth_headers):
    customer = auth_headers(6)
    ticket = client.post(
        "/tickets",
        headers=customer,
        json={"user_id": 6, "order_id": 1006, "issue_type": "CANCEL", "description": "取消高金额订单"},
    ).json()
    payload = {
        "ticket_id": ticket["id"],
        "proposed_action": "CANCEL_AND_REFUND",
        "idempotency_key": "api-high-amount",
    }
    assert client.post("/actions", headers=customer, json={**payload, "amount": "0.01"}).status_code == 422
    action = client.post("/actions", headers=customer, json=payload).json()
    assert action["execution_status"] == "WAITING_APPROVAL"
    endpoint = f"/actions/{action['id']}/simulate-execution"
    assert client.post(endpoint, headers=customer, json={}).status_code == 403
    assert client.post(endpoint, headers=admin_headers, json={}).status_code == 409
    approval = client.get("/approvals?status=PENDING", headers=admin_headers).json()[0]
    result = client.post(
        f"/approvals/{approval['id']}/review",
        headers=admin_headers,
        json={"approve": True, "reason": "已人工核验"},
    )
    assert result.status_code == 200
    assert result.json()["reviewer"] == "admin:test-reviewer"
    done = client.post(endpoint, headers=admin_headers, json={})
    assert done.json()["execution_status"] == "SUCCESS"
    assert done.json()["final_action"] == "CANCEL_AND_REFUND"
    assert client.get("/orders/1006/refunds", headers=customer).json()[0]["status"] == "SUCCESS"
    assert len(client.get(f"/actions/{action['id']}/audit", headers=admin_headers).json()) >= 4


def test_unknown_route_and_unexpected_error_do_not_leak(client, admin_headers, application, monkeypatch):
    assert client.get("/missing").json()["error"]["code"] == "HTTP_ERROR"

    def fail(_):
        raise RuntimeError("private database password")

    monkeypatch.setattr(application.state.business, "get_user", fail)
    response = client.get("/users/1", headers=admin_headers)
    assert response.status_code == 500
    assert "private database password" not in response.text


def test_pagination_and_role_schema_validation(client, admin_headers):
    assert len(client.get("/tickets?limit=1&offset=1", headers=admin_headers).json()) == 1
    assert client.get("/tickets?limit=101", headers=admin_headers).status_code == 422
    assert client.get("/tickets", headers={"X-Demo-Role": "root"}).status_code == 401
