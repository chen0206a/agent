"""Offline regressions for bounded completion repair; no provider network calls."""

import pytest
from app.agent.contracts import ChatRequest, ModelReply
from app.agent.evaluation import ScriptedProvider, tool_reply
from app.agent.runtime import AgentService
from app.core.enums import RunStatus
from app.models.entities import Ticket
from sqlalchemy import func, select


def agent(application, replies, **overrides):
    provider = ScriptedProvider(replies)
    service = AgentService(
        application.state.sessions,
        application.state.settings.model_copy(update=overrides),
        application.state.business,
        application.state.workflow,
        lambda: provider,
    )
    return service, provider


def test_correction_to_query_repairs_terminal_omission_without_side_effect(application):
    service, provider = agent(
        application,
        [
            tool_reply("finish_response", {"kind": "ASK_ORDER"}),
            tool_reply("get_order", {"order_id": 1001}),
            ModelReply(content="订单已付款。未经验证的退款成功 canary"),
            tool_reply("finish_response", {"kind": "ORDER"}),
        ],
    )
    parent = service.chat(1, ChatRequest(message="取消退款，还没提供订单号", idempotency_key="repair-parent"))
    request = ChatRequest(
        message="先停下取消诉求，我现在只查询1001状态。",
        order_id=1001,
        read_only=True,
        parent_run_id=parent.run_id,
        idempotency_key="repair-query",
    )
    result = service.chat(1, request)
    assert result.status == RunStatus.SUCCESS and result.outcome == "ANSWERED"
    assert "112.97" in result.reply and "canary" not in result.reply and result.action is None
    trace = service.trace(result.run_id)
    assert [call["name"] for call in trace.tool_calls] == ["get_order", "finish_response"]
    repair = trace.model_calls[-1]["request"]
    assert repair["tool_names"] == ["finish_response"]
    assert "canary" not in str(repair["messages"])
    count = provider.calls
    assert service.chat(1, request).run_id == result.run_id and provider.calls == count
    with application.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 3
    assert application.state.business.get_refunds(1001) == []


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_ticket", {"order_id": 1001, "issue_type": "CANCEL"}),
        ("submit_action", {"ticket_id": 1, "proposed_action": "CANCEL_AND_REFUND"}),
        ("execute_refund", {}),
        ("get_order", {"order_id": 1002}),
    ],
)
def test_repair_cannot_expand_tools_even_if_model_ignores_schema(application, name, args):
    service, _ = agent(application, [ModelReply(content="text"), tool_reply(name, args)])
    result = service.chat(1, ChatRequest(message="取消1001", idempotency_key="restricted-repair"))
    assert result.error_type == "PROTOCOL_REPAIR_TOOL_NOT_ALLOWED"
    assert result.action is None and service.trace(result.run_id).tool_calls == []
    assert application.state.business.get_refunds(1001) == []


def test_repair_rejects_entire_mixed_batch_before_any_tool_executes(application):
    mixed = tool_reply("finish_response", {"kind": "ASK_ORDER"})
    forbidden = tool_reply("create_ticket", {"order_id": 1001, "issue_type": "CANCEL"}).tool_calls[0]
    mixed.tool_calls.append(forbidden.model_copy(update={"id": "second-call"}))
    service, _ = agent(application, [ModelReply(content="text"), mixed])
    result = service.chat(1, ChatRequest(message="取消1001", idempotency_key="mixed-repair"))
    assert result.error_type == "PROTOCOL_REPAIR_TOOL_NOT_ALLOWED"
    assert service.trace(result.run_id).tool_calls == [] and result.action is None


def test_repair_finish_still_requires_current_order_evidence(application):
    service, _ = agent(
        application,
        [ModelReply(content="编造金额"), tool_reply("finish_response", {"kind": "ORDER"})],
        agent_max_steps=2,
    )
    result = service.chat(1, ChatRequest(message="查订单1001", idempotency_key="repair-evidence"))
    assert result.status == RunStatus.FAILED and result.action is None
    assert service.trace(result.run_id).tool_calls[0]["error_type"] == "ORDER_LOOKUP_REQUIRED"
    assert "编造金额" not in result.reply


@pytest.mark.parametrize("max_steps,error,calls", [(1, "STEP_LIMIT", 1), (8, "UNVERIFIED_RESPONSE", 2)])
def test_plain_text_repair_is_bounded_by_existing_budget(application, max_steps, error, calls):
    service, provider = agent(
        application, [ModelReply(content="我已退款成功")] * 3, agent_max_steps=max_steps
    )
    result = service.chat(1, ChatRequest(message="取消订单", idempotency_key="bounded-repair"))
    assert result.error_type == error and provider.calls == calls and result.action is None
    assert "退款成功" not in result.reply
