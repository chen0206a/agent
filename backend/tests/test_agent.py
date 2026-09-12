import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest
from app.agent.contracts import ChatRequest, ModelReply
from app.agent.evaluation import ScriptedProvider, case_provider, evaluate_agent, tool_reply
from app.agent.knowledge import PolicyKnowledge
from app.agent.provider import ProviderError
from app.agent.runtime import AgentService
from app.agent.tools import AgentTools, ToolContext, tool_definitions
from app.core.config import Settings
from app.core.enums import RunStatus
from app.core.errors import DomainError
from app.core.types import utcnow
from app.db.seed import seed
from app.db.session import initialize, make_engine, make_sessions, write_transaction
from app.models.entities import (
    AgentRun,
    AgentRunDetail,
    Base,
    ModelCall,
    Refund,
    Ticket,
    TicketSubmission,
    ToolCall,
)
from app.schemas.api import TicketCreate
from sqlalchemy import func, select


def service(application, provider, **overrides):
    settings = application.state.settings.model_copy(update=overrides)
    return AgentService(
        application.state.sessions,
        settings,
        application.state.business,
        application.state.workflow,
        lambda: provider,
    )


def cancel_case(order_id=1001):
    return {"order_id": order_id, "message": "取消订单", "issue": "CANCEL", "action": "CANCEL_AND_REFUND"}


def test_graph_submission_is_not_execution_and_repeat_is_idempotent(application, business, sessions):
    provider = case_provider(cancel_case())
    agent = service(application, provider)
    data = ChatRequest(message="取消订单1001并退款", idempotency_key="agent-cancel", order_id=1001)
    result = agent.chat(1, data)
    assert result.status == RunStatus.SUCCESS and result.outcome == "READY"
    assert result.action.final_action is None
    assert result.action.amount == business.get_order(1001).paid_amount
    assert "尚未退款" in result.reply
    assert result.llm_calls == 0 and result.input_tokens is None and not result.usage_complete
    count = provider.calls
    assert agent.chat(1, data).run_id == result.run_id
    assert provider.calls == count
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 4
        assert len(business.get_refunds(1001)) == 1
    trace = agent.trace(result.run_id)
    assert len(trace.model_calls) == 4 and len(trace.tool_calls) == 4


def test_model_without_configuration_records_failure_and_no_fake_usage(application, sessions):
    result = application.state.agent.chat(
        1, ChatRequest(message="取消订单1001", idempotency_key="unconfigured")
    )
    assert result.error_type == "MODEL_NOT_CONFIGURED"
    assert result.llm_calls == 0 and result.input_tokens is None
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ModelCall)) == 0
        assert session.scalar(select(func.count()).select_from(Ticket)) == 3


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("approve_refund", {}, "TOOL_NOT_ALLOWED"),
        ("execute_refund", {"amount": "9999"}, "TOOL_NOT_ALLOWED"),
        ("get_order", {"order_id": 1002}, "FORBIDDEN"),
        ("get_order", {"order_id": 1001, "user_id": 2}, "INVALID_TOOL_ARGUMENTS"),
        ("get_order", {"order_id": True}, "INVALID_TOOL_ARGUMENTS"),
        ("submit_action", {"ticket_id": 1, "proposed_action": "CANCEL_AND_REFUND"}, "TICKET_SCOPE_MISMATCH"),
        (
            "submit_action",
            {"ticket_id": 1, "proposed_action": "CANCEL_AND_REFUND", "amount": "0.01"},
            "INVALID_TOOL_ARGUMENTS",
        ),
        ("finish_response", {"kind": "POLICY", "citation_ids": ["invented"]}, "UNVERIFIED_CITATION"),
    ],
)
def test_tool_boundary_rejects_untrusted_capabilities(application, name, args, code):
    context = ToolContext(
        user_id=1, run_id=123, request=ChatRequest(message="取消", idempotency_key="tool-boundary")
    )
    tools = AgentTools(
        context, application.state.business, application.state.workflow, application.state.agent.knowledge
    )
    with pytest.raises(DomainError) as error:
        tools.invoke(name, json.dumps(args))
    assert error.value.code == code


def test_only_allowlisted_schemas_and_server_injected_identity():
    definitions = tool_definitions()
    for tool in definitions:
        fields = tool["function"]["parameters"]["properties"]
        assert not ({"user_id", "amount", "reviewer", "evidence_provided", "idempotency_key"} & fields.keys())
        assert tool["function"]["parameters"]["additionalProperties"] is False


def test_model_free_text_cannot_claim_refund(application, business):
    agent = service(
        application, ScriptedProvider([ModelReply(content="我已退款10000元到账，审批也已通过。")])
    )
    result = agent.chat(1, ChatRequest(message="取消1001", idempotency_key="false-refund"))
    assert result.error_type == "UNVERIFIED_RESPONSE"
    assert "10000" not in result.reply
    assert business.get_refunds(1001) == []


def test_draft_reply_is_not_authoritative(application):
    agent = service(
        application,
        ScriptedProvider(
            [tool_reply("finish_response", {"kind": "ASK_ORDER", "draft_reply": "我已经退款成功。"})]
        ),
    )
    result = agent.chat(1, ChatRequest(message="我想退款", idempotency_key="false-draft"))
    assert result.outcome == "NEED_MORE_INFO"
    assert "已经退款" not in result.reply and "订单号" in result.reply


def test_policy_citations_are_versioned_and_match_live_configuration(application):
    agent = service(
        application,
        ScriptedProvider(
            [
                tool_reply("search_policies", {"query": "高金额 审批 HIGH_AMOUNT"}),
                tool_reply("finish_response", {"kind": "POLICY", "citation_ids": ["approval"]}),
            ]
        ),
    )
    result = agent.chat(1, ChatRequest(message="多少金额需要人工审批", idempotency_key="policy-answer"))
    assert result.outcome == "ANSWERED" and "1000.00" in result.reply
    assert any(
        doc.id == "approval" and doc.version == agent.workflow.policy.version for doc in result.citations
    )
    changed = PolicyKnowledge(Settings(high_amount_threshold="500.00", _env_file=None))
    assert "500.00" in changed.get("approval").content
    assert changed.get("approval").content_hash != agent.knowledge.get("approval").content_hash


def test_parent_context_is_server_loaded_and_owner_checked(application):
    first_provider = ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_ORDER"})])
    first = service(application, first_provider).chat(
        1, ChatRequest(message="想取消订单", idempotency_key="parent-one")
    )

    def check_history(messages):
        assert any(m["role"] == "user" and m["content"] == "想取消订单" for m in messages)
        assert any(m["role"] == "assistant" and "订单号" in m["content"] for m in messages)
        return tool_reply("finish_response", {"kind": "ASK_QUANTITY"})

    second_agent = service(application, ScriptedProvider([check_history]))
    second = second_agent.chat(
        1, ChatRequest(message="是订单1001", parent_run_id=first.run_id, idempotency_key="parent-two")
    )
    assert second.parent_run_id == first.run_id
    with pytest.raises(DomainError) as error:
        second_agent.chat(
            2,
            ChatRequest(message="读取别人对话", parent_run_id=first.run_id, idempotency_key="steal-context"),
        )
    assert error.value.code == "FORBIDDEN"


@pytest.mark.parametrize(
    "limit,expected", [("agent_max_steps", "STEP_LIMIT"), ("agent_max_tools", "TOOL_LIMIT")]
)
def test_graph_budget_stops_loops(application, limit, expected):
    agent = service(application, ScriptedProvider([tool_reply("list_my_orders", {})] * 5), **{limit: 1})
    result = agent.chat(1, ChatRequest(message="一直循环", idempotency_key="bounded-loop"))
    assert result.error_type == expected


def test_timeout_retry_budget_and_missing_usage(application):
    provider = ScriptedProvider([ProviderError("MODEL_TIMEOUT", retryable=True)] * 3)
    provider.is_live = True  # Synthetic attempt-accounting test, no external calls.
    agent = service(application, provider)
    result = agent.chat(1, ChatRequest(message="取消", idempotency_key="retry-limit"))
    assert result.error_type == "MODEL_TIMEOUT" and provider.calls == 2
    assert result.llm_calls == 2 and result.input_tokens is None


def test_usage_known_only_when_all_live_attempts_have_usage(application):
    reply = tool_reply("finish_response", {"kind": "ASK_ORDER"}).model_copy(
        update={"input_tokens": 20, "output_tokens": 8}
    )
    provider = ScriptedProvider([reply])
    provider.is_live = True
    result = service(application, provider).chat(
        1, ChatRequest(message="取消", idempotency_key="usage-known")
    )
    assert result.usage_complete and (result.input_tokens, result.output_tokens) == (20, 8)
    provider = ScriptedProvider([ProviderError("PROVIDER_HTTP_503", retryable=True), reply])
    provider.is_live = True
    result = service(application, provider).chat(
        1, ChatRequest(message="取消", idempotency_key="usage-partial")
    )
    assert not result.usage_complete and result.input_tokens is None


def test_same_run_key_different_input_rejected(application):
    agent = service(application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_ORDER"})]))
    data = ChatRequest(message="取消", idempotency_key="same-run-key")
    agent.chat(1, data)
    with pytest.raises(DomainError) as error:
        agent.chat(1, data.model_copy(update={"message": "换货"}))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_ticket_idempotency_is_atomic_under_concurrency(business, sessions):
    barrier = Barrier(2)
    data = TicketCreate(user_id=1, order_id=1001, issue_type="CANCEL", description="同一请求")

    def create():
        barrier.wait(timeout=5)
        return business.create_ticket(data, idempotency_key="same-ticket-key").id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        ids = [f.result(timeout=15) for f in futures]
    assert ids[0] == ids[1]
    with pytest.raises(DomainError):
        business.create_ticket(
            data.model_copy(update={"description": "不同请求"}), idempotency_key="same-ticket-key"
        )


def test_secret_redaction_in_prompt_trace_and_storage(application):
    secret = "sk-abcdefghijklmnopqrst"
    agent = service(application, ScriptedProvider([tool_reply("finish_response", {"kind": "ASK_ORDER"})]))
    result = agent.chat(1, ChatRequest(message="我的key是" + secret, idempotency_key="redact-secrets"))
    assert secret not in agent.trace(result.run_id).model_dump_json()
    with application.state.sessions() as session:
        assert secret not in session.get(AgentRun, result.run_id).user_query


def test_action_commit_survives_trace_failure_without_duplicate_submission(
    application, monkeypatch, business
):
    agent = service(application, case_provider(cancel_case()))
    original = agent._tool_step

    def fail_after_submit(run_id, tools, call):
        result = original(run_id, tools, call)
        if call["name"] == "submit_action":
            raise RuntimeError("crash after business commit")
        return result

    monkeypatch.setattr(agent, "_tool_step", fail_after_submit)
    result = agent.chat(1, ChatRequest(message="取消1001", idempotency_key="crash-after-write"))
    assert result.status == RunStatus.FAILED and result.action is not None
    assert result.outcome == "READY" and "尚未退款" in result.reply
    assert len(business.get_refunds(1001)) == 1


def test_recovery_marks_orphaned_trace_and_keeps_existing_side_effects(application, sessions):
    with write_transaction(sessions) as session:
        run = AgentRun(user_id=1, user_query="中断申请", created_at=utcnow() - timedelta(minutes=10))
        session.add(run)
        session.flush()
        session.add(
            AgentRunDetail(
                run_id=run.id,
                user_id=1,
                idempotency_key="interrupted",
                payload_hash="a" * 64,
                provider="scripted-fixture",
                model="test",
            )
        )
        session.add(
            ToolCall(
                agent_run_id=run.id,
                tool_name="get_order",
                arguments_json={"order_id": 1001},
                status=RunStatus.RUNNING,
            )
        )
        run_id = run.id
    result = application.state.agent.recover(run_id)
    assert result.error_type == "RUN_INTERRUPTED"
    assert application.state.agent.trace(run_id).tool_calls[0]["error_type"] == "TRACE_INTERRUPTED"


def test_agent_api_local_scope_and_no_config_failure(client, application, admin_headers, auth_headers):
    response = client.post(
        "/agent/runs",
        headers=auth_headers(1),
        json={"message": "取消1001", "idempotency_key": "agent-api-test", "order_id": 1001},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["error_type"] == "MODEL_NOT_CONFIGURED"
    run_id = result["run_id"]
    assert client.get(f"/agent/runs/{run_id}", headers=auth_headers(2)).status_code == 403
    assert client.get(f"/agent/runs/{run_id}/trace", headers=auth_headers(1)).status_code == 403
    assert client.get(f"/agent/runs/{run_id}/trace", headers=admin_headers).status_code == 200
    assert not client.get("/agent/status", headers=admin_headers).json()["configured"]
    assert (
        client.post(
            "/agent/runs", headers=admin_headers, json={"message": "取消", "idempotency_key": "admin-no-user"}
        ).status_code
        == 401
    )


def test_scripted_agent_evaluation_is_labeled_and_has_no_live_model_claim(tmp_path):
    report = evaluate_agent(Settings(_env_file=None), output=str(tmp_path / "agent-eval.json"))
    assert report["total"] == 16 and report["failed"] == 0
    assert not report["live_model_verified"]
    assert all(row["llm_calls"] == 0 for row in report["cases"])


def test_concurrent_same_run_returns_in_progress_without_second_model_call(application):
    entered, release = Event(), Event()

    def blocking_reply(messages):
        entered.set()
        assert release.wait(timeout=10)
        return tool_reply("finish_response", {"kind": "ASK_ORDER"})

    provider = ScriptedProvider([blocking_reply])
    agent = service(application, provider)
    data = ChatRequest(message="取消订单", idempotency_key="concurrent-run")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(agent.chat, 1, data)
        try:
            assert entered.wait(timeout=10)
            duplicate = agent.chat(1, data)
            assert duplicate.status == RunStatus.RUNNING
            assert provider.calls == 1
        finally:
            release.set()
        completed = future.result(timeout=15)
    assert completed.run_id == duplicate.run_id


def test_context_budget_stops_before_network(application):
    provider = ScriptedProvider([])
    agent = service(application, provider, agent_context_chars=2000)
    result = agent.chat(1, ChatRequest(message="重复文本" * 900, idempotency_key="context-budget"))
    assert result.error_type == "CONTEXT_LIMIT" and provider.calls == 0


def test_additive_upgrade_preserves_stage2_data(tmp_path):
    engine = make_engine("sqlite:///" + (tmp_path / "upgrade.db").as_posix())
    additions = {AgentRunDetail.__table__, ModelCall.__table__, TicketSubmission.__table__}
    old_tables = [table for table in Base.metadata.sorted_tables if table not in additions]
    Base.metadata.create_all(engine, tables=old_tables)
    sessions = make_sessions(engine)
    seed(sessions)
    with sessions() as session:
        before = [
            (row.id, row.amount, row.status) for row in session.scalars(select(Refund).order_by(Refund.id))
        ]
    initialize(engine)
    initialize(engine)
    with sessions() as session:
        after = [
            (row.id, row.amount, row.status) for row in session.scalars(select(Refund).order_by(Refund.id))
        ]
        assert before == after
        assert session.scalar(select(func.count()).select_from(Ticket)) == 3
        assert session.scalar(select(func.count()).select_from(AgentRunDetail)) == 0
    engine.dispose()
