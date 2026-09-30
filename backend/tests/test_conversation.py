"""Conversation contracts with scripted providers; not model accuracy measurements."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.agent.contracts import ChatRequest
from app.agent.evaluation import ScriptedProvider, case_provider, tool_reply
from app.agent.runtime import AgentService
from app.core.errors import DomainError
from app.db.session import write_transaction
from app.models.entities import AgentRun, AgentRunDetail, Ticket
from sqlalchemy import func, select


def agent(app, provider):
    return AgentService(
        app.state.sessions, app.state.settings, app.state.business, app.state.workflow, lambda: provider
    )


def start(app, order_id=1001):
    return agent(app, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_INTENT"})])).chat(
        1,
        ChatRequest(
            message="先了解一下", order_id=order_id, read_only=True, idempotency_key="conversation-root"
        ),
    )


def test_cross_order_parent_rejected_but_explicit_new_conversation_allowed(application):
    parent = start(application)
    provider = ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_INTENT"})])
    svc = agent(application, provider)
    data = ChatRequest(
        message="换1011", order_id=1011, parent_run_id=parent.run_id, idempotency_key="changed-order"
    )
    with pytest.raises(DomainError) as error:
        svc.chat(1, data)
    assert error.value.code == "CONVERSATION_ORDER_MISMATCH" and provider.calls == 0
    assert svc.chat(1, data.model_copy(update={"parent_run_id": None})).status == "SUCCESS"


def test_missing_order_inherits_scope_and_blocks_other_owned_order(application, sessions):
    parent = start(application)
    provider = ScriptedProvider([tool_reply("get_order", {"order_id": 1011})])
    result = agent(application, provider).chat(
        1, ChatRequest(message="继续", parent_run_id=parent.run_id, idempotency_key="inherited-scope")
    )
    assert result.error_type == "ORDER_SCOPE_MISMATCH"
    with sessions() as session:
        assert session.get(AgentRun, result.run_id).order_id == 1001
        assert session.scalar(select(func.count()).select_from(Ticket)) == 3


@pytest.mark.parametrize(
    "tool,finish", [("get_order", "ORDER"), ("get_refunds", "REFUNDS"), ("get_shipment", "ASK_INTENT")]
)
def test_text_selected_order_is_anchored_only_after_verified_lookup(application, sessions, tool, finish):
    first = agent(
        application,
        ScriptedProvider(
            [
                tool_reply(tool, {"order_id": 1001}),
                tool_reply("finish_response", {"kind": finish}),
            ]
        ),
    ).chat(1, ChatRequest(message="查1001", idempotency_key="text-selected"))
    with sessions() as session:
        assert session.get(AgentRun, first.run_id).order_id == 1001
    result = agent(application, ScriptedProvider([tool_reply("get_order", {"order_id": 1011})])).chat(
        1, ChatRequest(message="继续", parent_run_id=first.run_id, idempotency_key="text-continue")
    )
    assert result.error_type == "ORDER_SCOPE_MISMATCH"


def test_clarification_can_bind_order_without_losing_previous_question(application):
    parent = start(application, None)

    def check(messages):
        assert "用户选择的订单：1001" in messages[0]["content"]
        assert any(m["content"] == "先了解一下" for m in messages)
        assert messages[-1]["content"] == "订单1001，先查进度"
        return tool_reply("get_refunds", {"order_id": 1001})

    result = agent(
        application,
        ScriptedProvider(
            [
                check,
                tool_reply("finish_response", {"kind": "REFUNDS"}),
            ]
        ),
    ).chat(
        1,
        ChatRequest(
            message="订单1001，先查进度",
            order_id=1001,
            read_only=True,
            parent_run_id=parent.run_id,
            idempotency_key="bind-order",
        ),
    )
    assert result.outcome == "ANSWERED"


def test_consultation_can_become_application_but_requeries_all_evidence(application):
    parent = start(application)
    provider = case_provider(
        {"order_id": 1001, "message": "取消", "issue": "CANCEL", "action": "CANCEL_AND_REFUND"}
    )
    svc = agent(application, provider)
    result = svc.chat(
        1,
        ChatRequest(
            message="现在明确申请取消退款",
            parent_run_id=parent.run_id,
            read_only=False,
            idempotency_key="consult-to-apply",
        ),
    )
    assert result.outcome == "READY" and result.action.final_action is None
    assert [t["name"] for t in svc.trace(result.run_id).tool_calls] == [
        "get_order",
        "search_policies",
        "create_ticket",
        "submit_action",
    ]


def test_correction_to_consultation_blocks_historical_application_intent(application, sessions):
    parent = agent(
        application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_ORDER"})])
    ).chat(1, ChatRequest(message="帮我取消退款", idempotency_key="old-intent"))

    def check(messages):
        assert messages[-1]["content"] == "不取消了，仅查订单"
        assert "本轮仅咨询 read_only=true。" in messages[0]["content"]
        return tool_reply("create_ticket", {"order_id": 1001, "issue_type": "CANCEL"})

    svc = agent(
        application,
        ScriptedProvider(
            [
                check,
                tool_reply("get_order", {"order_id": 1001}),
                tool_reply("finish_response", {"kind": "ORDER"}),
            ]
        ),
    )
    result = svc.chat(
        1,
        ChatRequest(
            message="不取消了，仅查订单",
            order_id=1001,
            read_only=True,
            parent_run_id=parent.run_id,
            idempotency_key="corrected-intent",
        ),
    )
    assert result.outcome == "ANSWERED" and result.action is None
    assert svc.trace(result.run_id).tool_calls[0]["error_type"] == "CONSULTATION_ONLY"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 3


def test_concurrent_children_have_one_winner_and_idempotent_retry(application, sessions):
    parent = start(application)
    barrier = Barrier(2)

    def send(index):
        provider = ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_INTENT"})])
        svc = agent(application, provider)
        data = ChatRequest(
            message=f"第{index}条", parent_run_id=parent.run_id, idempotency_key=f"concurrent-child-{index}"
        )
        barrier.wait(timeout=10)
        try:
            result = svc.chat(1, data)
            assert svc.chat(1, data).run_id == result.run_id
            return "ok", provider.calls
        except DomainError as error:
            return error.code, provider.calls

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, range(2)))
    assert sorted(results) == [("STALE_PARENT_RUN", 0), ("ok", 1)]
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentRunDetail)
                .where(AgentRunDetail.parent_run_id == parent.run_id)
            )
            == 1
        )


def test_stale_parent_http_conflict_does_not_create_run(application, client, auth_headers):
    parent = start(application)
    application.state.agent = agent(
        application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_INTENT"})])
    )
    body = {"message": "继续", "parent_run_id": parent.run_id, "idempotency_key": "first-child"}
    headers = auth_headers(1)
    assert client.post("/agent/runs", json=body, headers=headers).status_code == 200
    response = client.post("/agent/runs", json={**body, "idempotency_key": "second-child"}, headers=headers)
    assert response.status_code == 409 and response.json()["error"]["code"] == "STALE_PARENT_RUN"


def test_pre_upgrade_cross_order_run_remains_idempotently_replayable(application, sessions):
    parent = start(application)
    data = ChatRequest(message="历史换单", order_id=1011, idempotency_key="legacy-cross-order")
    original = agent(
        application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_INTENT"})])
    ).chat(1, data)
    legacy = data.model_copy(update={"parent_run_id": parent.run_id})
    # Model a completed request written by the pre-upgrade API, which permitted branching.
    with write_transaction(sessions) as session:
        detail = session.get(AgentRunDetail, original.run_id)
        detail.parent_run_id = parent.run_id
        detail.payload_hash = hashlib.sha256(
            legacy.model_dump_json(exclude={"read_only"}).encode()
        ).hexdigest()
    provider = ScriptedProvider([])
    assert agent(application, provider).chat(1, legacy).run_id == original.run_id
    assert provider.calls == 0
