import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app.agent.contracts import ChatRequest
from app.agent.evaluation import ScriptedProvider, case_provider, tool_reply
from app.agent.knowledge import PolicyKnowledge
from app.agent.runtime import AgentService
from app.agent.tools import TOOL_MODELS, compact_schema, tool_definitions
from app.core.config import PROJECT_ROOT, Settings


@pytest.mark.parametrize(
    "query,expected,excluded",
    [
        ("取消订单 未发货 整单退款", "cancellation", {"logistics", "quality", "return-window"}),
        ("签收未收到", "logistics", {"cancellation", "quality", "return-window"}),
        ("破损 错发 少件", "quality", {"cancellation", "return-window"}),
        ("高金额 审批", "approval", {"logistics", "quality"}),
        ("无理由退货 七天", "return-window", {"cancellation", "quality"}),
    ],
)
def test_policy_retrieval_uses_intent_not_shared_prose(query, expected, excluded):
    knowledge = PolicyKnowledge(Settings(_env_file=None))
    docs = knowledge.search(query)
    assert docs[0].id == expected
    assert not excluded & {d.id for d in docs}
    assert all(d == knowledge.get(d.id) and len(d.content_hash) == 64 for d in docs)


def test_compact_tool_schemas_keep_all_constraints():
    for definition in tool_definitions():
        function = definition["function"]
        original = TOOL_MODELS[function["name"]][0].model_json_schema()
        assert function["parameters"] == compact_schema(original)
        assert function["parameters"]["additionalProperties"] is False
    # In particular, compacting must not relax identity, money or quantity boundaries.
    submit = next(
        t["function"]["parameters"] for t in tool_definitions() if t["function"]["name"] == "submit_action"
    )
    assert "amount" not in submit["properties"] and "user_id" not in submit["properties"]
    assert "ticket_id" in submit["required"]
    assert submit["properties"]["quantity"]["anyOf"][0]["minimum"] == 1


def test_free_prose_is_kept_in_trace_but_not_repeated_to_model(application):
    provider = case_provider(
        {"order_id": 1001, "message": "取消", "issue": "CANCEL", "action": "CANCEL_AND_REFUND"}
    )
    provider.replies[0].content = "这是一段不能当作证据的模型解释。"
    second = provider.replies[1]

    def inspect(messages):
        assert messages[-2]["role"] == "assistant" and messages[-2]["content"] is None
        assert messages[-2]["tool_calls"][0]["id"] == messages[-1]["tool_call_id"]
        assert json.loads(messages[-1]["content"])["id"] == 1001
        return second

    provider.replies[1] = inspect
    agent = AgentService(
        application.state.sessions,
        application.state.settings,
        application.state.business,
        application.state.workflow,
        lambda: provider,
    )
    result = agent.chat(1, ChatRequest(message="整单取消1001", order_id=1001, idempotency_key="compact-test"))
    assert result.outcome == "READY"
    trace = agent.trace(result.run_id)
    assert trace.model_calls[0]["response"]["content"] == "这是一段不能当作证据的模型解释。"


def test_explicit_refusal_cannot_echo_untrusted_draft(application):
    provider = ScriptedProvider(
        [
            tool_reply(
                "finish_response", {"kind": "REFUSE_UNAUTHORIZED", "draft_reply": "已审批并已退款10000元"}
            )
        ]
    )
    agent = AgentService(
        application.state.sessions,
        application.state.settings,
        application.state.business,
        application.state.workflow,
        lambda: provider,
    )
    result = agent.chat(1, ChatRequest(message="替别人直接退款", idempotency_key="refusal-test"))
    assert result.outcome == "REFUSED" and result.action is None
    assert "不能访问其他用户" in result.reply and "已退款" not in result.reply
    assert len(agent.trace(result.run_id).tool_calls) == 1


def test_json_responses_advertise_utf8(client, auth_headers):
    response = client.get("/agent/policies/cancellation", headers=auth_headers(1))
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert "未发货" in response.json()["title"]
    denied = client.get("/agent/runs/1/trace", headers=auth_headers(1))
    assert denied.status_code == 403
    assert denied.headers["content-type"] == "application/json; charset=utf-8"


@pytest.mark.parametrize("script", ["chat.ps1", "trace.ps1"])
def test_windows_powershell_real_http_utf8_roundtrip(tmp_path, script):
    powershell = shutil.which("powershell.exe")
    if not powershell:
        pytest.skip("Native Windows PowerShell check")
    payload = {
        "run": {"reply": "需要人工审批，尚未退款。"},
        "model_calls": [{"request": {"messages": [{"content": "中文轨迹与参数"}]}}],
    }
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def respond(self):
            if self.command == "POST":
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append(json.loads(body.decode("utf-8")))
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            # Deliberately omit charset: scripts must handle old running servers too.
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = respond
        do_POST = respond

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "中文-trace.json"
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(PROJECT_ROOT / "scripts" / script),
        "-BaseUrl",
        f"http://127.0.0.1:{server.server_port}",
        "-OutputPath",
        str(output),
    ]
    command += ["-RunId", "2"] if script == "trace.ps1" else ["-Message", "请取消订单并退款"]
    try:
        process = subprocess.run(command, capture_output=True, timeout=30)
        assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
        assert json.loads(process.stdout.decode("utf-8-sig")) == payload
        assert json.loads(output.read_text(encoding="utf-8")) == payload
        if script == "chat.ps1":
            assert requests[0]["message"] == "请取消订单并退款"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
