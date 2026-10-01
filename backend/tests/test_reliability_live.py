"""No network: durable cost accounting and single-run guards."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("reliability_live", ROOT / "scripts/reliability_live.py")
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def terms(budget="2"):
    return {
        "budget_usd": budget,
        "input_usd_per_million": "0.30",
        "output_usd_per_million": "1.20",
        "price_source": "mock",
        "price_checked_at": "2026-09-30",
    }


def payload():
    return {"model": "mock-model", "max_tokens": 1024, "messages": [{"role": "user", "content": "你好"}]}


def test_reservation_survives_restart_and_blocks_unknown_attempt(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    ledger.reserve(payload(), {"case_id": "mock"})
    restarted = live.BudgetLedger(tmp_path / "budget.db", terms())
    assert restarted.state()["blocked"]
    with pytest.raises(live.ProviderError, match="BUDGET_UNRESOLVED_ATTEMPT"):
        restarted.reserve(payload(), {})


def test_usage_settlement_releases_unused_reservation(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    identifier = ledger.reserve(payload(), {})
    ledger.settle(
        identifier,
        {"model": "returned-model", "usage": {"prompt_tokens": 100, "completion_tokens": 20}},
        latency_ms=12,
    )
    state = ledger.state()
    assert state["committed_usd_proxy"] == "0.000054"
    assert not state["blocked"]
    assert state["attempts"][0]["metadata"]["provider_returned_model"] == "returned-model"


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 10},
        {"prompt_tokens": -1, "completion_tokens": 10},
        [],
    ],
)
def test_invalid_usage_retains_reserved_budget(tmp_path, usage):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    identifier = ledger.reserve(payload(), {})
    held = ledger.state()["committed_usd_proxy"]
    ledger.settle(identifier, {"usage": usage}, latency_ms=10)
    assert ledger.state()["committed_usd_proxy"] == held
    assert ledger.state()["blocked"]


def test_over_reservation_settles_real_proxy_and_stops(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    identifier = ledger.reserve(payload(), {})
    ledger.settle(
        identifier, {"usage": {"prompt_tokens": 1000000, "completion_tokens": 1000000}}, latency_ms=1
    )
    assert live.Decimal(ledger.state()["committed_usd_proxy"]) == live.Decimal("1.5")
    assert ledger.state()["blocked"]


def test_budget_limit_prevents_delegate_call(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms("0.000001"))
    calls = []
    transport = live.MeteredTransport(ledger, {}, httpx.MockTransport(lambda request: calls.append(request)))
    with pytest.raises(live.ProviderError, match="EVALUATION_BUDGET_LIMIT"):
        transport.handle_request(httpx.Request("POST", "https://example.invalid", json=payload()))
    assert calls == []


def test_terms_cannot_be_changed(tmp_path):
    live.BudgetLedger(tmp_path / "budget.db", terms())
    with pytest.raises(ValueError, match="cannot change"):
        live.BudgetLedger(tmp_path / "budget.db", terms("5"))


def test_single_marker_and_checkpoint_are_durable(tmp_path):
    path = tmp_path / "holdout.started.json"
    live.exclusive_json(path, {"started_at": "first"})
    with pytest.raises(FileExistsError):
        live.exclusive_json(path, {"started_at": "second"})
    assert live.contract.read(path)["started_at"] == "first"
    checkpoint = tmp_path / "progress.json"
    live.atomic_json(checkpoint, {"value": 1})
    live.atomic_json(checkpoint, {"value": 2})
    assert live.contract.read(checkpoint) == {"value": 2}


def test_parallel_reservations_are_serialized(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms("0.004"))

    def reserve():
        try:
            ledger.reserve(payload(), {})
            return True
        except live.ProviderError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: reserve(), range(2))) == [False, True]


def test_transport_records_metadata_without_secrets(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    delegate = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "returned-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                "choices": [{"message": {"reasoning_content": "private-canary"}}],
            },
        )
    )
    transport = live.MeteredTransport(ledger, {"case_id": "mock"}, delegate)
    response = transport.handle_request(
        httpx.Request(
            "POST", "https://example.invalid", json=payload(), headers={"Authorization": "Bearer key-canary"}
        )
    )
    assert response.status_code == 200
    text = str(ledger.state())
    assert "key-canary" not in text and "private-canary" not in text


def test_transport_timeout_retains_reservation(tmp_path):
    def timeout(request):
        raise httpx.ReadTimeout("sensitive-canary")

    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    transport = live.MeteredTransport(ledger, {}, httpx.MockTransport(timeout))
    with pytest.raises(httpx.ReadTimeout):
        transport.handle_request(httpx.Request("POST", "https://example.invalid", json=payload()))
    assert ledger.state()["blocked"] and "sensitive-canary" not in str(ledger.state())


def test_holdout_requires_dev_summary_and_final_seal(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "OUT", tmp_path)
    monkeypatch.setattr(live, "verify_release", lambda: {})
    with pytest.raises(FileNotFoundError):
        live.seal_holdout("reviewed-hash")
    live.atomic_json(tmp_path / "dev/summary.json", {"completed": False, "episodes": 13})
    with pytest.raises(ValueError, match="Complete Dev"):
        live.seal_holdout("reviewed-hash")


@pytest.mark.parametrize("budget", ["NaN", "Infinity", "-1", "0"])
def test_nonfinite_or_invalid_budget_is_rejected(tmp_path, budget):
    with pytest.raises(ValueError):
        live.BudgetLedger(tmp_path / "budget.db", terms(budget))


def test_double_settlement_cannot_reset_spent_budget(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    identifier = ledger.reserve(payload(), {})
    body = {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    ledger.settle(identifier, body, latency_ms=1)
    with pytest.raises(ValueError):
        ledger.settle(identifier, body, latency_ms=1)


def setup_mock_batch(tmp_path, monkeypatch, budget="2"):
    output, data = tmp_path / "output", tmp_path / "cases"
    monkeypatch.setattr(live, "OUT", output)
    monkeypatch.setattr(live.contract, "DATA", data)
    cfg = live.Settings(_env_file=None, llm_model="mock-model", llm_api_key="test-key")
    monkeypatch.setattr(live, "Settings", lambda: cfg)
    release = {"terms": terms(budget), "runner_sources": {}, "product_manifest_hash": "mock-hash"}
    monkeypatch.setattr(live, "verify_release", lambda: release)
    live.atomic_json(output / "release.json", release)
    cases = [
        {
            "case_id": f"MOCK-{index}",
            "user_id": 1,
            "turns": [
                {
                    "request": {"message": "mock refund query", "order_id": 1001, "read_only": True},
                    "expected": {
                        "outcome": "ANSWERED",
                        "finish": "REFUNDS",
                        "action": None,
                        "required_tools": ["get_refunds", "finish_response"],
                        "optional_tools": [],
                        "reply_contains": ["没有退款记录"],
                    },
                }
            ],
            "expected_added_rows": {"tickets": 0, "action_requests": 0, "refunds": 0, "approvals": 0},
        }
        for index in range(2)
    ]
    live.atomic_json(data / "dev.json", cases)
    live.atomic_json(data / "manifest.json", {"datasets": {"dev": live.sha(data / "dev.json")}})
    calls = []

    def respond(request):
        body = live.json.loads(request.content)
        calls.append(body)
        has_refunds = any(message["role"] == "tool" for message in body["messages"])
        name, arguments = (
            ("finish_response", {"kind": "REFUNDS"}) if has_refunds else ("get_refunds", {"order_id": 1001})
        )
        return httpx.Response(
            200,
            json={
                "model": "mock-returned",
                "usage": {"prompt_tokens": 200, "completion_tokens": 10},
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "mock-call",
                                    "type": "function",
                                    "function": {"name": name, "arguments": live.json.dumps(arguments)},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(live.httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    return output, calls


def test_mock_batch_runs_real_runtime_and_preserves_trace_once(tmp_path, monkeypatch):
    output, calls = setup_mock_batch(tmp_path, monkeypatch)
    live.run("dev")
    summary = live.contract.read(output / "dev/summary.json")
    assert summary["passed"] == 2 and summary["completed"]
    assert len(calls) == 4  # Idempotent repeats must not issue another API attempt.
    assert summary["metrics"]["input_tokens"] == 800
    assert summary["metrics"]["required_tool_recall"] == 1
    assert summary["ledger"]["attempts"][0]["metadata"]["provider_returned_model"] == "mock-returned"
    assert (output / "dev/MOCK-0.partial.json").exists()
    with pytest.raises(FileExistsError):
        live.run("dev")
    assert len(calls) == 4 and not (output / "batch.lock").exists()


def test_mock_budget_stop_preserves_fixed_denominator(tmp_path, monkeypatch):
    output, calls = setup_mock_batch(tmp_path, monkeypatch, "0.000001")
    live.run("dev")
    summary = live.contract.read(output / "dev/summary.json")
    assert not calls
    assert summary["episodes"] == 2 and summary["passed"] == 0 and not summary["completed"]
    assert summary["cases"][1]["not_run"]
    assert summary["metrics"]["planned_turns"] == 2
    assert summary["metrics"]["required_tool_recall"] == 0


def test_batch_lock_prevents_new_network_call(tmp_path, monkeypatch):
    output, calls = setup_mock_batch(tmp_path, monkeypatch)
    live.exclusive_json(output / "batch.lock", {"pid": "other"})
    with pytest.raises(FileExistsError):
        live.run("dev")
    assert not calls and (output / "batch.lock").exists()


def test_holdout_seal_validates_review_hash_and_is_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "OUT", tmp_path)
    monkeypatch.setattr(live, "verify_release", lambda: {})
    live.atomic_json(tmp_path / "release.json", {"mock": True})
    live.atomic_json(tmp_path / "dev/summary.json", {"completed": True, "episodes": 13})
    with pytest.raises(ValueError, match="reviewed"):
        live.seal_holdout("wrong")
    reviewed = live.sha(tmp_path / "dev/summary.json")
    live.seal_holdout(reviewed)
    with pytest.raises(FileExistsError):
        live.seal_holdout(reviewed)


def test_checkpoint_audit_never_replays_calls_or_removes_marker(tmp_path, monkeypatch):
    output, calls = setup_mock_batch(tmp_path, monkeypatch, "0.000001")
    live.run("dev")
    live.audit("dev")
    report = live.contract.read(output / "dev/audit.json")
    assert report["episodes"] == 2 and report["passed"] == 0
    assert not calls and (output / "dev.started.json").exists()


def test_audit_of_never_started_batch_does_not_create_output(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "OUT", tmp_path / "output")
    with pytest.raises(ValueError, match="No durable"):
        live.audit("holdout")
    assert not (tmp_path / "output").exists()


def test_holdout_without_seal_is_blocked_before_network(tmp_path, monkeypatch):
    _, calls = setup_mock_batch(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        live.run("holdout")
    assert not calls


def test_provider_retry_attempts_are_explicitly_recorded(tmp_path):
    ledger = live.BudgetLedger(tmp_path / "budget.db", terms())
    delegate = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"usage": {"prompt_tokens": 10, "completion_tokens": 2}})
    )
    transport = live.MeteredTransport(ledger, {"turn_index": 0}, delegate)
    for _ in range(2):
        transport.handle_request(httpx.Request("POST", "https://example.invalid", json=payload()))
    attempts = ledger.state()["attempts"]
    assert attempts[0]["metadata"]["attempt_index"] == 1
    assert attempts[1]["metadata"]["attempt_index"] == 2
    assert attempts[1]["metadata"]["is_retry"]


def test_explicit_freeze_check_rejects_changed_source_without_asserts(monkeypatch):
    monkeypatch.setattr(live.contract, "source_hashes", lambda: {})
    with pytest.raises(ValueError, match="Frozen product source changed"):
        live.verify_product()
