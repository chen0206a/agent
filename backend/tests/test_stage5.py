"""Scoring/metering tests are offline and never counted as model evaluation."""

import copy
import json

import httpx
import pytest
from app.agent.contracts import ChatRequest
from app.agent.evaluation import case_provider
from app.agent.runtime import AgentService
from app.core.config import Settings
from app.services.business import BusinessService
from app.services.workflow import WorkflowService

from scripts import stage5 as s5


@pytest.fixture
def observed(tmp_path):
    case = next(c for c in s5.read(s5.DATA / "dev.json") if c["category"] == "cancel")
    path = tmp_path / "case.db"
    engine, sessions = s5.setup_fixture(path, case)
    cfg = Settings(_env_file=None, llm_model="", llm_api_key="")
    before = s5.db_read(path)
    provider = case_provider(
        {
            "order_id": case["order_id"],
            "message": case["user_message"],
            "issue": case["issue"],
            "action": case["proposed_action"],
        }
    )
    b = BusinessService(sessions)
    w = WorkflowService(sessions, cfg, clock=lambda: s5.NOW)
    agent = AgentService(sessions, cfg, b, w, lambda: provider)
    try:
        result = agent.chat(
            case["user_id"],
            ChatRequest(
                message=case["user_message"], order_id=case["order_id"], idempotency_key="scorer-offline-test"
            ),
        )
        trace = agent.trace(result.run_id).model_dump(mode="json")
        yield case, [trace], before, s5.db_read(path)
    finally:
        engine.dispose()


def test_scorer_valid_business_and_wrong_amount(observed):
    case, traces, before, after = observed
    assert s5.assess(case, traces, before, after)["task_success"]
    altered = copy.deepcopy(traces)
    altered[-1]["run"]["action"]["amount"] = "999999.00"
    assert not s5.assess(case, altered, before, after)["amount_accuracy"]
    assert not s5.assess(case, altered, before, after)["task_success"]


def test_scorer_detects_old_row_mutation_and_replay(observed):
    case, traces, before, after = observed
    altered = copy.deepcopy(after)
    altered["orders"][0]["paid_amount"] = "1.00"
    assert s5.assess(case, traces, before, altered)["unsafe_action"]
    assert s5.assess(case, traces, before, after, replay_ok=False)["duplicate_side_effect"]


def test_scorer_detects_foreign_data_disclosure(observed):
    case, traces, before, after = observed
    altered = copy.deepcopy(traces)
    altered[0]["tool_calls"].append(
        {"name": "get_order", "arguments": {"order_id": 1002}, "result": {}, "error_type": None}
    )
    assert s5.assess(case, altered, before, after)["unauthorized_access"]


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setattr(s5, "OUT", tmp_path)
    folder = tmp_path / "batch"
    s5.save(folder / "batch.json", {"split": "dev"})
    t = s5.MeteredTransport(folder, {"case_id": "test-meter"})
    t.delegate.close()
    t.delegate = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            json={"model": "returned-revision", "usage": {"prompt_tokens": 123, "completion_tokens": 9}},
            request=r,
        )
    )
    yield t, folder
    t.delegate.close()


def request():
    return httpx.Request(
        "POST",
        "https://unit.invalid/chat/completions",
        headers={"Authorization": "Bearer NEVER-STORE"},
        json={"model": "requested-alias", "messages": [], "max_tokens": 32},
    )


def test_meter_records_returned_model_usage_without_secrets(transport):
    t, folder = transport
    t.handle_request(request())
    row = s5.read(next((folder / "attempts").glob("*.json")))
    assert (
        row["requested_model"] == "requested-alias" and row["provider_returned_model"] == "returned-revision"
    )
    assert row["input_tokens"] == 123 and row["actual_external_request"]
    assert "NEVER-STORE" not in json.dumps(row)


def test_injected_timeout_not_counted_as_external(transport):
    t, folder = transport
    t.case["fault"] = "provider_timeout_once"
    with pytest.raises(httpx.ReadTimeout):
        t.handle_request(request())
    row = s5.read(next((folder / "attempts").glob("*.json")))
    assert not row["actual_external_request"] and row["cost_proxy_usd"] == 0


def test_budget_guard_preserves_test_reserve(transport):
    t, folder = transport
    s5.save(folder / "attempts" / "old.json", {"actual_external_request": True, "cost_proxy_usd": 3.0})
    with pytest.raises(SystemExit, match="BUDGET_GUARD"):
        t.handle_request(request())
    assert len(list((folder / "attempts").glob("*.json"))) == 1


def test_percentiles_use_linear_interpolation():
    assert s5.percentile([10, 20, 30, 40], 0.5) == 25
    assert s5.percentile([10, 20, 30, 40], 0.95) == 38.5
