"""Start a real loopback Uvicorn server with isolated data and verify both full flows."""

import argparse
import json
import os
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

import httpx
from app.core.config import PROJECT_ROOT
from app.db.seed import seed
from app.db.session import initialize, make_engine, make_sessions
from app.services.auth import AuthService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-fixture", action="store_true", help="Use explicitly scripted test provider")
    args = parser.parse_args()
    observations = []
    (PROJECT_ROOT / "docs").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aftersale-http-") as directory:
        url = "sqlite:///" + (Path(directory) / "smoke.db").as_posix()
        engine = make_engine(url)
        initialize(engine)
        seed(make_sessions(engine))
        auth = AuthService(make_sessions(engine))
        for user_id in (1, 2, 3, 6):
            auth.create_account(f"smoke{user_id}", "Smoke-only-password-42", "customer", user_id)
        auth.create_account("smoke-admin", "Smoke-admin-password-42", "admin")
        engine.dispose()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {
            **os.environ,
            "ASC_DATABASE_URL": url,
            "ASC_DEMO_API_TOKEN": "smoke-local-token",
            "ASC_LOG_LEVEL": "WARNING",
            "ASC_HIGH_AMOUNT_THRESHOLD": "1000.00",
            "ASC_RETURN_WINDOW_DAYS": "7",
            "ASC_QUALITY_WINDOW_DAYS": "30",
            "ASC_LLM_MODEL": "",
            "ASC_LLM_API_KEY": "",
        }
        app_target = "scripts.agent_http_fixture:app" if args.agent_fixture else "app.main:app"
        if os.name == "nt":
            # Control the real interpreter, not a Windows venv launcher whose child
            # may briefly retain the log handle after the launcher exits.
            launch = [
                sys._base_executable,
                "-I",
                "-S",
                "-c",
                "import site,sys; site.addsitedir(sys.argv[1]); sys.path.insert(0,sys.argv[2]); "
                "import uvicorn; uvicorn.run(sys.argv[3], host='127.0.0.1', "
                "port=int(sys.argv[4]), proxy_headers=False)",
                sysconfig.get_path("purelib"),
                str(PROJECT_ROOT),
                app_target,
                str(port),
            ]
        else:
            launch = [
                sys.executable,
                "-m",
                "uvicorn",
                app_target,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-proxy-headers",
            ]
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                launch,
                cwd=PROJECT_ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{port}",
                    timeout=10,
                    headers={"X-Demo-Token": "smoke-local-token"},
                    trust_env=False,
                ) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError("Uvicorn exited before it became ready")
                        try:
                            if client.get("/health").status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Uvicorn did not become ready")

                    identities = {}

                    def call(method, path, role="admin", user=1, body=None, expected=200):
                        name = "smoke-admin" if role == "admin" else f"smoke{user}"
                        if name not in identities:
                            login = client.post(
                                "/auth/login",
                                json={
                                    "username": name,
                                    "password": "Smoke-admin-password-42"
                                    if role == "admin"
                                    else "Smoke-only-password-42",
                                },
                            )
                            assert login.status_code == 200
                            identities[name] = {
                                "Cookie": f"asc_session={login.cookies['asc_session']}",
                                "X-CSRF-Token": login.json()["csrf_token"],
                            }
                        headers = identities[name]
                        response = client.request(method, path, headers=headers, json=body)
                        if response.status_code != expected:
                            raise AssertionError(f"{method} {path}: {response.status_code} {response.text}")
                        observations.append({"method": method, "path": path, "status": response.status_code})
                        return response.json()

                    call("GET", "/health")
                    for order_id, user, issue, action_type, quantity in (
                        (1006, 6, "CANCEL", "CANCEL_AND_REFUND", None),
                        (1003, 3, "NO_REASON_RETURN", "RETURN_AND_REFUND", 1),
                    ):
                        ticket = call(
                            "POST",
                            "/tickets",
                            "customer",
                            user,
                            {
                                "user_id": user,
                                "order_id": order_id,
                                "issue_type": issue,
                                "description": "Real HTTP smoke test",
                            },
                            201,
                        )
                        payload = {
                            "ticket_id": ticket["id"],
                            "proposed_action": action_type,
                            "idempotency_key": f"http-smoke-{order_id}",
                        }
                        if quantity:
                            payload.update(order_item_id=order_id * 10 + 1, quantity=quantity)
                        action = call("POST", "/actions", "customer", user, payload)
                        path = f"/actions/{action['id']}"
                        call("POST", path + "/simulate-execution", "customer", user, {}, 403)
                        call("POST", path + "/simulate-execution", body={}, expected=409)
                        if action["execution_status"] == "WAITING_APPROVAL":
                            approval = next(
                                a for a in call("GET", "/approvals") if a["action_request_id"] == action["id"]
                            )
                            call(
                                "POST",
                                f"/approvals/{approval['id']}/review",
                                body={"approve": True, "reason": "Checked in local simulation"},
                            )
                        if quantity:
                            call("POST", path + "/return-receipt", body={"note": "Warehouse received item"})
                        done = call("POST", path + "/simulate-execution", body={})
                        assert done["execution_status"] == "SUCCESS"
                        assert done["final_action"] == action_type
                        call("POST", path + "/simulate-execution", body={})
                        refunds = call("GET", f"/orders/{order_id}/refunds")
                        assert len(refunds) == 1 and refunds[0]["status"] == "SUCCESS"
                        assert len(call("GET", path + "/audit")) >= 3
                    call("GET", "/orders/1002", "customer", 1, expected=403)
                    call("GET", "/orders/999999", expected=404)
                    call("POST", "/tickets", body={"amount": "1.00"}, expected=422)
                    configured = call("GET", "/agent/status")
                    assert configured["configured"] is False
                    agent_request = {
                        "message": "取消订单1001并退款",
                        "order_id": 1001,
                        "idempotency_key": "http-agent-1001",
                    }
                    agent_run = call("POST", "/agent/runs", "customer", 1, agent_request)
                    if args.agent_fixture:
                        assert agent_run["outcome"] == "READY"
                        assert agent_run["provider"] == "scripted-fixture"
                        assert agent_run["action"]["final_action"] is None
                        assert agent_run["llm_calls"] == 0
                    else:
                        assert agent_run["error_type"] == "MODEL_NOT_CONFIGURED"
                    same = call("POST", "/agent/runs", "customer", 1, agent_request)
                    assert same["run_id"] == agent_run["run_id"]
                    call("GET", f"/agent/runs/{agent_run['run_id']}", "customer", 2, expected=403)
                    call("GET", f"/agent/runs/{agent_run['run_id']}/trace", "customer", 1, expected=403)
                    trace = call("GET", f"/agent/runs/{agent_run['run_id']}/trace")
                    if args.agent_fixture:
                        assert len(trace["tool_calls"]) == 4
                    call("GET", "/agent/policies/approval", "customer", 1)
                    schema = call("GET", "/openapi.json")
                    (PROJECT_ROOT / "docs/openapi.json").write_text(
                        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
            finally:
                process.terminate()
                process.wait(timeout=15)
    report = {
        "passed": True,
        "transport": "real HTTP / loopback Uvicorn",
        "isolated_database": True,
        "agent_mode": "scripted-fixture" if args.agent_fixture else "unconfigured",
        "requests_checked": len(observations),
        "observations": observations,
    }
    output = PROJECT_ROOT / (
        "docs/verification/agent-http-smoke.json"
        if args.agent_fixture
        else "docs/verification/http-smoke.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "observations"}, indent=2))


if __name__ == "__main__":
    main()
