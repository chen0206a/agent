"""Offline metrics contracts: preserve strict scores, denominators and evidence boundaries."""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("metrics_summary_test", ROOT / "scripts/summarize_metrics.py")
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def archived_inputs(split="holdout"):
    base = ROOT / "docs/verification/reliability-postfix-v1" / split
    dataset = metrics.read(ROOT / "eval/reliability-postfix-v1" / f"{split}.json")
    summary = metrics.read(base / "summary.json")
    attempts = [a for a in summary["ledger"]["attempts"] if a["metadata"]["split"] == split]
    return dataset, summary["cases"], attempts


def test_real_holdout_preserves_failure_and_separates_business_success():
    report = metrics.load_summary(ROOT, "reliability-postfix-v1", "holdout")
    assert report["strict_task_success"]["passed"] == 25
    assert report["business_goal_success"]["passed"] == 26
    assert report["categories"]["logistics_apply"]["strict_task_success"]["passed"] == 1
    assert report["failure_stages"] == {"tool_arguments": 1}
    assert report["latency"]["turn"]["p50_ms"] == 2048
    assert report["latency"]["turn"]["p95_ms"] == 3550
    assert report["cost"]["amount_proxy"] == "0.355236"
    assert report["cost"]["per_strict_success_proxy"] == "0.01420944"
    assert report["recovery"]["tool_error_turns"] == {"passed": 1, "total": 1, "rate": 1.0}
    assert report["recovery"]["protocol_repair_turns"]["rate"] is None
    assert report["recovery"]["http_retry_logical_requests"]["rate"] is None


def test_missing_episode_retains_denominator_and_does_not_count_as_success():
    dataset, rows, attempts = archived_inputs()
    identifier = rows[0]["case_id"]
    report = metrics.summarize(
        dataset, rows[1:], [a for a in attempts if a["metadata"]["case_id"] != identifier]
    )
    assert report["strict_task_success"]["total"] == 26
    assert report["tool_selection"]["total"] == 30
    assert report["business_goal_success"]["passed"] == 25
    assert report["coverage"]["business_unknown_episodes"] == 1
    assert report["episodes"][0]["business_goal_passed"] is None


@pytest.mark.parametrize("mutation", ["usage", "charge", "missing_attempt", "unsettled"])
def test_incomplete_cost_evidence_never_becomes_zero_or_partial_total(mutation):
    dataset, rows, attempts = archived_inputs()
    if mutation == "usage":
        attempts[0]["metadata"]["input_tokens"] = None
    elif mutation == "charge":
        attempts[0]["charged"] = "NaN"
    elif mutation == "missing_attempt":
        attempts.pop()
    else:
        attempts[0]["status"] = "unresolved"
    report = metrics.summarize(dataset, rows, attempts)
    assert not report["cost"]["usage_and_cost_complete"]
    assert report["cost"]["amount_proxy"] is None
    assert report["cost"]["per_strict_success_proxy"] is None


def test_ledger_identity_mismatch_and_duplicate_cases_are_rejected():
    dataset, rows, attempts = archived_inputs()
    attempts[0]["metadata"]["logical_call_id"] = "wrong"
    with pytest.raises(ValueError, match="identity mismatch"):
        metrics.summarize(dataset, rows, attempts)
    with pytest.raises(ValueError, match="duplicate"):
        metrics.summarize(dataset, rows + [rows[0]], [])


def test_unknown_business_check_is_not_assumed_to_pass():
    dataset, rows, attempts = archived_inputs()
    rows[0]["turns"][0]["score"]["failure_reasons"] = ["future_new_check"]
    report = metrics.summarize(dataset, rows, attempts)
    assert report["episodes"][0]["business_goal_passed"] is None
    assert report["business_goal_success"]["passed"] == 25


def test_unsafe_or_duplicate_side_effect_cannot_be_counted_as_business_recovery():
    dataset, rows, attempts = archived_inputs()
    row = next(r for r in rows if r["case_id"] == "FIX-08-1")
    row["database_failures"] = ["row_count:action_requests"]
    report = metrics.summarize(dataset, rows, attempts)
    assert report["business_goal_success"]["passed"] == 25
    assert report["recovery"]["tool_error_turns"]["passed"] == 0
    assert report["safety"]["database_failure_episodes"] == 1


def test_historical_retry_metadata_remains_unknown():
    report = metrics.load_summary(ROOT, "reliability-v1", "holdout")
    assert report["strict_task_success"]["passed"] == 25
    assert report["business_goal_success"]["passed"] == 25
    assert report["cost"]["amount_proxy"] == "0.336324"
    assert report["recovery"]["retry_metadata_complete"] is False
    assert report["recovery"]["http_retry_logical_requests"]["total"] is None


def test_no_success_has_no_cost_per_success_and_no_cases_has_no_percentile():
    dataset, rows, attempts = archived_inputs()
    for row in rows:
        row["passed"] = False
        row["database_failures"] = ["injected_failure"]
    report = metrics.summarize(dataset, rows, attempts)
    assert report["cost"]["amount_proxy"] == "0.355236"
    assert report["cost"]["per_strict_success_proxy"] is None
    assert report["cost"]["per_business_success_proxy"] is None
    assert metrics.distribution([])["p95_ms"] is None


def test_duplicate_and_optional_calls_are_review_candidates_not_business_failures():
    dataset, rows, _ = archived_inputs()
    baseline = metrics.summarize(dataset, rows, [])
    turn = rows[0]["turns"][0]
    turn["trace"]["tool_calls"] += [
        {"name": "get_order", "arguments": {"order_id": 1008}, "error_type": None},
        {"name": "get_order", "arguments": {"order_id": 1008}, "error_type": None},
    ]
    report = metrics.summarize(dataset, rows, [])
    assert report["efficiency"]["optional_tool_calls"] == baseline["efficiency"]["optional_tool_calls"] + 2
    assert report["efficiency"]["duplicate_same_arguments_calls"] == (
        baseline["efficiency"]["duplicate_same_arguments_calls"] + 1
    )
    assert report["business_goal_success"]["passed"] == 26


def test_retry_recovery_uses_case_and_turn_scope_and_contiguous_attempts():
    dataset, rows, attempts = archived_inputs()
    retried = copy.deepcopy(attempts[0])
    retried["metadata"].update(attempt_index=2, is_retry=True)
    rows[0]["turns"][0]["trace"]["model_calls"].insert(
        1, copy.deepcopy(rows[0]["turns"][0]["trace"]["model_calls"][0])
    )
    rows[0]["turns"][0]["trace"]["model_calls"][1]["request"].update(attempt_index=2, is_retry=True)
    attempts.insert(1, retried)
    report = metrics.summarize(dataset, rows, attempts)
    assert report["recovery"]["http_retry_logical_requests"] == {"passed": 1, "total": 1, "rate": 1.0}
    retried["metadata"].update(attempt_index=3)
    rows[0]["turns"][0]["trace"]["model_calls"][1]["request"].update(attempt_index=3)
    with pytest.raises(ValueError, match="non-contiguous"):
        metrics.summarize(dataset, rows, attempts)


def test_protocol_repair_requires_restricted_request_and_marker():
    dataset, rows, attempts = archived_inputs()
    request = rows[0]["turns"][0]["trace"]["model_calls"][-1]["request"]
    request["tool_names"] = ["finish_response"]
    assert metrics.summarize(dataset, rows, attempts)["recovery"]["protocol_repair_turns"]["total"] == 0
    request["messages"].append({"role": "system", "content": metrics.REPAIR_MARKER})
    assert metrics.summarize(dataset, rows, attempts)["recovery"]["protocol_repair_turns"]["total"] == 1


def test_frozen_evidence_and_different_existing_reports_cannot_be_overwritten(tmp_path):
    report = metrics.load_summary(ROOT, "reliability-postfix-v1", "dev")
    protected = tmp_path / "docs/verification/holdout"
    with pytest.raises(ValueError, match="read-only"):
        metrics.write_reports(tmp_path, protected, "holdout", report)
    directory = tmp_path / "docs/metrics/sample"
    paths = metrics.write_reports(tmp_path, directory, "dev", report)
    before = {p: p.read_bytes() for p in paths}
    metrics.write_reports(tmp_path, directory, "dev", report)
    assert before == {p: p.read_bytes() for p in paths}
    report["strict_task_success"]["passed"] = 0
    with pytest.raises(FileExistsError, match="overwrite"):
        metrics.write_reports(tmp_path, directory, "dev", report)
    assert before == {p: p.read_bytes() for p in paths}


def test_dataset_hash_mutation_is_rejected_before_reporting(tmp_path):
    data = tmp_path / "eval/reliability-postfix-v1"
    output = tmp_path / "docs/verification/reliability-postfix-v1/dev"
    data.mkdir(parents=True)
    output.mkdir(parents=True)
    (data / "dev.json").write_text("[]", encoding="utf-8")
    (output / "batch.json").write_text(json.dumps({"dataset_hash": "frozen", "split": "dev"}))
    (output / "summary.json").write_text(json.dumps({"cases": []}))
    with pytest.raises(ValueError, match="dataset hash"):
        metrics.load_summary(tmp_path, "reliability-postfix-v1", "dev")
