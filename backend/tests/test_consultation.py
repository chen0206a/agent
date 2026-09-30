"""Deterministic regressions, not a new measurement of model intent accuracy."""

import hashlib
import json

import pytest
from app.agent.contracts import ChatRequest
from app.agent.evaluation import ScriptedProvider, tool_reply
from app.agent.runtime import AgentService
from app.agent.tools import AgentTools, ToolContext
from app.core.enums import RefundStatus
from app.core.errors import DomainError
from app.db.session import write_transaction
from app.models.entities import AgentRunDetail, Refund, Ticket, TicketSubmission
from pydantic import ValidationError
from sqlalchemy import func, select


def service(app, replies):
    return AgentService(
        app.state.sessions,
        app.state.settings,
        app.state.business,
        app.state.workflow,
        lambda: ScriptedProvider(replies),
    )


def counts(sessions):
    with sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (Ticket, TicketSubmission, Refund)
        )


@pytest.mark.parametrize(
    "status,expected",
    [
        (RefundStatus.PENDING, "待处理，尚未退款"),
        (RefundStatus.APPROVED, "已批准，尚未退款"),
        (RefundStatus.PROCESSING, "退款处理中，尚未确认成功"),
        (RefundStatus.SUCCESS, "退款成功（模拟），不代表真实资金到账"),
        (RefundStatus.REJECTED, "退款已拒绝，未执行退款"),
        (RefundStatus.FAILED, "退款处理失败，尚未确认成功"),
    ],
)
def test_refund_answer_uses_verified_record(application, sessions, status, expected):
    with write_transaction(sessions) as session:
        refund = session.scalar(select(Refund).where(Refund.order_id == 1008))
        refund.status = status
        amount = refund.amount
    agent = service(
        application,
        [
            tool_reply("get_refunds", {"order_id": 1008}),
            tool_reply("finish_response", {"kind": "REFUNDS", "draft_reply": "已到账999999元"}),
        ],
    )
    result = agent.chat(8, ChatRequest(message="查退款进度", idempotency_key="refund-state"))
    assert result.outcome == "ANSWERED"
    assert expected in result.reply and str(amount) in result.reply
    assert "订单 1008" in result.reply and "999999" not in result.reply
    assert result.action is None


def test_legacy_order_finish_includes_observed_refunds(application):
    agent = service(
        application,
        [
            tool_reply("get_order", {"order_id": 1008}),
            tool_reply("get_refunds", {"order_id": 1008}),
            tool_reply("finish_response", {"kind": "ORDER"}),
        ],
    )
    result = agent.chat(8, ChatRequest(message="查进度", idempotency_key="legacy-refund"))
    assert "退款处理中" in result.reply and "尚未确认成功" in result.reply


def test_empty_refunds_are_not_a_success_claim(application):
    agent = service(
        application,
        [
            tool_reply("get_refunds", {"order_id": 1001}),
            tool_reply("finish_response", {"kind": "REFUNDS"}),
        ],
    )
    result = agent.chat(1, ChatRequest(message="查进度", idempotency_key="empty-refund"))
    assert "当前没有退款记录" in result.reply and "退款成功" not in result.reply


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("finish_response", {"kind": "REFUNDS"}, "REFUND_LOOKUP_REQUIRED"),
        ("get_refunds", {"order_id": 1008}, "FORBIDDEN"),
        ("get_refunds", {"order_id": 1001, "read_only": False}, "INVALID_TOOL_ARGUMENTS"),
        ("create_ticket", {"order_id": 1001, "issue_type": "CANCEL"}, "CONSULTATION_ONLY"),
        ("submit_action", {"ticket_id": 2, "proposed_action": "CANCEL_AND_REFUND"}, "CONSULTATION_ONLY"),
    ],
)
def test_consultation_boundary(application, sessions, name, args, code):
    before = counts(sessions)
    ctx = ToolContext(
        user_id=1,
        run_id=123,
        request=ChatRequest(message="仅咨询", idempotency_key="boundary-only", read_only=True),
    )
    tools = AgentTools(
        ctx, application.state.business, application.state.workflow, application.state.agent.knowledge
    )
    with pytest.raises(DomainError) as error:
        tools.invoke(name, json.dumps(args))
    assert error.value.code == code and counts(sessions) == before


def test_api_read_only_blocks_mutations_and_recovers(application, client, auth_headers, sessions):
    before = counts(sessions)
    application.state.agent = service(
        application,
        [
            tool_reply("get_order", {"order_id": 1001}),
            tool_reply("create_ticket", {"order_id": 1001, "issue_type": "CANCEL"}),
            tool_reply("submit_action", {"ticket_id": 2, "proposed_action": "CANCEL_AND_REFUND"}),
            tool_reply("finish_response", {"kind": "ORDER"}),
        ],
    )
    body = {"message": "取消退款", "idempotency_key": "api-read-only", "read_only": True}
    headers = auth_headers(1)
    response = client.post("/agent/runs", json=body, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert result["outcome"] == "ANSWERED" and result["action"] is None
    assert counts(sessions) == before
    trace = application.state.agent.trace(result["run_id"])
    assert sum(t["error_type"] == "CONSULTATION_ONLY" for t in trace.tool_calls) == 2
    assert client.post("/agent/runs", json=body, headers=headers).json()["run_id"] == result["run_id"]
    assert client.post("/agent/runs", json={**body, "read_only": False}, headers=headers).status_code == 409


def test_missing_intent_asks_before_order_or_submission(application, sessions):
    before = counts(sessions)
    agent = service(application, [tool_reply("finish_response", {"kind": "ASK_INTENT"})])
    result = agent.chat(1, ChatRequest(message="帮我处理一下", idempotency_key="ask-intent"))
    assert result.outcome == "NEED_MORE_INFO" and "咨询政策、查询进度" in result.reply
    assert "订单号" not in result.reply and counts(sessions) == before


def test_legacy_request_hash_remains_compatible(application, sessions):
    data = ChatRequest(message="你好", idempotency_key="legacy-hash")
    agent = service(application, [tool_reply("finish_response", {"kind": "ASK_INTENT"})])
    result = agent.chat(1, data)
    expected = hashlib.sha256(data.model_dump_json(exclude={"read_only"}).encode()).hexdigest()
    with sessions() as session:
        detail = session.scalar(select(AgentRunDetail).where(AgentRunDetail.run_id == result.run_id))
        assert detail.payload_hash == expected


def test_read_only_requires_real_boolean():
    with pytest.raises(ValidationError):
        ChatRequest(message="查询", idempotency_key="strict-bool", read_only="true")
