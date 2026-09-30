import time
from datetime import timedelta

import pytest
from app.agent.contracts import ChatRequest
from app.agent.evaluation import ScriptedProvider, case_provider, tool_reply
from app.agent.provider import ProviderError
from app.agent.runtime import AgentService
from app.agent.tools import AgentTools, ToolContext
from app.core.enums import RunStatus
from app.core.errors import DomainError
from app.core.types import utcnow
from app.db.session import write_transaction
from app.models.entities import AgentRun, AgentRunDetail, Refund, Ticket, ToolCall
from sqlalchemy import func, select


def service(app, provider, **overrides):
    return AgentService(
        app.state.sessions,
        app.state.settings.model_copy(update=overrides),
        app.state.business,
        app.state.workflow,
        lambda: provider,
    )


@pytest.mark.parametrize("stop_after", ["create_ticket", "submit_action"])
def test_crash_after_commit_recovers_without_replaying_tools(application, sessions, monkeypatch, stop_after):
    provider = case_provider(
        {"order_id": 1001, "message": "取消", "issue": "CANCEL", "action": "CANCEL_AND_REFUND"}
    )
    agent = service(application, provider)
    original = agent._tool_step

    def crash(run_id, tools, call):
        result = original(run_id, tools, call)
        if call["name"] == stop_after:
            raise RuntimeError("simulated lost completion")
        return result

    monkeypatch.setattr(agent, "_tool_step", crash)

    def no_finalize(*args, **kwargs):
        raise RuntimeError("simulated process termination")

    monkeypatch.setattr(agent, "_finalize", no_finalize)
    data = ChatRequest(message="取消1001", order_id=1001, idempotency_key="recovery-commit")
    with pytest.raises(RuntimeError):
        agent.chat(1, data)
    with write_transaction(sessions) as session:
        detail = session.scalar(
            select(AgentRunDetail).where(AgentRunDetail.idempotency_key == data.idempotency_key)
        )
        run_id = detail.run_id
        session.get(AgentRun, run_id).created_at = utcnow() - timedelta(minutes=10)
        row = session.scalar(
            select(ToolCall).where(ToolCall.agent_run_id == run_id).order_by(ToolCall.id.desc())
        )
        row.status = RunStatus.RUNNING
    result = application.state.agent.recover(run_id)
    assert result.failure_stage == "recovery" and result.status == "FAILED"
    assert result.outcome == ("READY" if stop_after == "submit_action" else "FAILED")
    assert "尚未退款" in result.reply if result.action else "已保留工单" in result.reply
    assert application.state.agent.recover(run_id).finished_at == result.finished_at
    replay = service(application, ScriptedProvider([])).chat(1, data)
    assert replay.run_id == run_id and replay.failure_stage == "recovery"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 4
        assert session.scalar(select(func.count()).select_from(Refund).where(Refund.order_id == 1001)) == (
            1 if result.action else 0
        )
        assert not session.scalar(
            select(ToolCall.id).where(ToolCall.agent_run_id == run_id, ToolCall.status == "RUNNING")
        )


def test_late_model_result_cannot_start_tools_after_deadline(application):
    def late(messages):
        time.sleep(0.05)
        return tool_reply("create_ticket", {"order_id": 1001, "issue_type": "CANCEL"})

    result = service(application, ScriptedProvider([late]), agent_timeout_seconds=0.02).chat(
        1, ChatRequest(message="取消", idempotency_key="late-model-result")
    )
    assert result.error_type == "RUN_TIMEOUT" and result.failure_stage == "runtime"
    assert result.tool_calls == 0 and result.action is None


@pytest.mark.parametrize(
    "reply,stage",
    [
        (ProviderError("MODEL_TIMEOUT"), "model"),
        (tool_reply("execute_refund", {}), "tool"),
    ],
)
def test_failure_stage_comes_from_trace(application, reply, stage):
    result = service(application, ScriptedProvider([reply])).chat(
        1, ChatRequest(message="取消", idempotency_key="failure-attribution")
    )
    assert result.failure_stage == stage


def test_closed_run_cannot_be_overwritten_or_start_another_tool(application):
    agent = service(application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_ORDER"})]))
    data = ChatRequest(message="取消", idempotency_key="closed-run-fence")
    result = agent.chat(1, data)
    ctx = ToolContext(user_id=1, run_id=result.run_id, request=data)
    agent._finalize(ctx, "RUN_INTERRUPTED", 999, interrupted=True)
    assert agent.get_run(result.run_id) == result
    tools = AgentTools(ctx, application.state.business, application.state.workflow, agent.knowledge)
    with pytest.raises(DomainError) as error:
        agent._tool_step(result.run_id, tools, {"name": "get_order", "arguments": '{"order_id":1001}'})
    assert error.value.code == "RUN_CLOSED"
    assert agent.get_run(result.run_id).tool_calls == result.tool_calls
    provider = ScriptedProvider([])
    with pytest.raises(ProviderError) as error:
        agent._model_step(result.run_id, provider, [], time.monotonic() + 30)
    assert error.value.code == "RUN_CLOSED" and provider.calls == 0


def test_recovery_requires_admin_and_rejects_recent_active_run(application, sessions, client, auth_headers):
    result = service(
        application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_ORDER"})])
    ).chat(1, ChatRequest(message="取消", idempotency_key="recover-permissions"))
    with write_transaction(sessions) as session:
        session.get(AgentRun, result.run_id).status = RunStatus.RUNNING
    url = f"/agent/runs/{result.run_id}/recover"
    assert client.post(url, headers=auth_headers(1)).status_code == 403
    response = client.post(url, headers=auth_headers(None))
    assert response.status_code == 409 and response.json()["error"]["code"] == "RUN_STILL_ACTIVE"


def test_late_model_return_preserves_recovered_trace_and_does_not_run_tools(application, sessions):
    def late(messages):
        with write_transaction(sessions) as session:
            run = session.scalar(select(AgentRun).order_by(AgentRun.id.desc()))
            run.created_at = utcnow() - timedelta(minutes=10)
            run_id = run.id
        application.state.agent.recover(run_id)
        return tool_reply("get_order", {"order_id": 1001})

    agent = service(application, ScriptedProvider([late]))
    result = agent.chat(1, ChatRequest(message="查订单", idempotency_key="late-recovered-model"))
    assert result.error_type == "RUN_INTERRUPTED" and result.tool_calls == 0
    assert agent.trace(result.run_id).model_calls[0]["error_type"] == "TRACE_INTERRUPTED"
