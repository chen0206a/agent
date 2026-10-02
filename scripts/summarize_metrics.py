"""Offline, standard-library-only summaries of archived reliability evaluations.

Never import the Agent/runner, read .env/SQLite, regrade strict scores, or call a model.
"""

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ("reliability-postfix-v1", "reliability-v1")
BUSINESS_FAILURES = {
    "outcome",
    "reply_evidence",
    "action_contract",
    "unexpected_action",
    "finish_kind",
    "unsafe_action",
}
PLANNING_FAILURES = {"tool_arguments", "missing_required_tool", "runtime_error", "idempotency"}
REPAIR_MARKER = "上一轮缺少实际工具调用，文字已丢弃。"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fraction(passed, total):
    return {"passed": passed, "total": total, "rate": passed / total if total else None}


def distribution(values):
    values = sorted(values)
    return {
        "samples": len(values),
        "mean_ms": statistics.mean(values) if values else None,
        "p50_ms": statistics.median(values) if values else None,
        "p95_ms": values[math.ceil(0.95 * len(values)) - 1] if values else None,
    }


def business_turn(turn):
    """Separate recorded business checks from planning errors; unknown checks fail closed."""
    score, run = turn["score"], turn["trace"]["run"]
    reasons = set(score["failure_reasons"])
    if reasons - BUSINESS_FAILURES - PLANNING_FAILURES:
        return None
    return (
        run["status"] == "SUCCESS"
        and not run.get("error_type")
        and not reasons.intersection(BUSINESS_FAILURES)
        and score["policy_compliance"] is True
        and score["unsafe_action"] is False
    )


def summarize(dataset, rows, attempts):
    """Use frozen score flags; planned denominators include missing/incomplete episodes."""
    expected = {c["case_id"]: c for c in dataset}
    actual = {r["case_id"]: r for r in rows}
    if len(expected) != len(dataset) or len(actual) != len(rows) or actual.keys() - expected.keys():
        raise ValueError("duplicate or unknown case_id")
    planned_turns = sum(len(c["turns"]) for c in dataset)
    required_total = sum(len(t["expected"]["required_tools"]) for c in dataset for t in c["turns"])
    categories = defaultdict(lambda: {"episodes": 0, "strict_passed": 0, "business_passed": 0})
    records, turns, latency, episode_latency, multi_turn = [], [], [], [], []
    counts, stages, tool_errors = Counter(), Counter(), Counter()
    optional, disallowed, duplicates, tool_recovery = [], [], [], []
    repairs = []
    live_calls = []
    for case in dataset:
        identifier = case["case_id"]
        row = actual.get(identifier)
        observed = row.get("turns", []) if row else []
        if len(observed) > len(case["turns"]):
            raise ValueError("more observed turns than planned")
        complete = bool(row) and len(observed) == len(case["turns"]) and not row.get("incomplete_turns", 0)
        checks = [business_turn(t) for t in observed]
        business = bool(
            complete
            and not row.get("error_type")
            and "database_failures" in row
            and not row["database_failures"]
            and all(v is True for v in checks)
            and all(t.get("idempotent_repeat") is True for t in observed)
        )
        strict = bool(complete and row.get("passed") is True)
        unknown = not complete or "database_failures" not in (row or {}) or None in checks
        counts["business_unknown_episodes"] += unknown
        counts["completed_episodes"] += complete
        counts["strict_passed"] += strict
        counts["business_passed"] += business
        counts["database_failure_episodes"] += bool(row and row.get("database_failures"))
        counts["policy_compliant_episodes"] += bool(
            complete
            and "database_failures" in row
            and not row["database_failures"]
            and all(t["score"]["policy_compliance"] is True for t in observed)
        )
        if len(case["turns"]) > 1:
            multi_turn.append({"strict": strict, "business": business})
        if not strict:
            stages[(row or {}).get("failure_stage") or "missing_or_unclassified"] += 1
        category = categories[case["category"]]
        category["episodes"] += 1
        category["strict_passed"] += strict
        category["business_passed"] += business
        records.append(
            {
                "case_id": identifier,
                "category": case["category"],
                "strict_passed": strict,
                "business_goal_passed": None if unknown else business,
                "failure_stage": (row or {}).get("failure_stage"),
                "turn_failure_stages": [
                    {
                        "runtime": t["score"].get("runtime_failure_stage"),
                        "evaluation": t["score"].get("evaluation_failure_stage"),
                    }
                    for t in observed
                ],
                "observed_turns": len(observed),
                "planned_turns": len(case["turns"]),
            }
        )
        times = []
        for index, turn in enumerate(observed):
            score, trace = turn["score"], turn["trace"]
            turns.append(score)
            value = score.get("latency_ms")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                latency.append(value)
                times.append(value)
            counts["idempotency_passed"] += turn.get("idempotent_repeat") is True
            calls = trace["tool_calls"]
            gold = case["turns"][index]["expected"]
            allowed = set(gold["required_tools"]) | set(gold["optional_tools"])
            seen = set()
            error_calls = []
            for call in calls:
                item = {"case_id": identifier, "turn_index": index, "tool": call["name"]}
                key = (call["name"], json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
                if key in seen:
                    duplicates.append(item)
                seen.add(key)
                if call["name"] in set(gold["optional_tools"]) - set(gold["required_tools"]):
                    optional.append(item)
                if call["name"] not in allowed:
                    disallowed.append(item)
                if call.get("error_type"):
                    tool_errors[call["error_type"]] += 1
                    error_calls.append(call)
            counts["tool_calls"] += len(calls)
            if error_calls:
                recovered = checks[index] is True and not row.get("database_failures") and business
                tool_recovery.append(
                    {
                        "case_id": identifier,
                        "turn_index": index,
                        "recovered_to_safe_business_goal": recovered,
                        "error_types": sorted({c["error_type"] for c in error_calls}),
                    }
                )
            repair_calls = []
            for model_call in trace["model_calls"]:
                request = model_call.get("request", {})
                if model_call.get("is_live") is True:
                    live_calls.append((identifier, index, model_call))
                if request.get("tool_names") == ["finish_response"] and any(
                    m.get("role") == "system" and REPAIR_MARKER in str(m.get("content", ""))
                    for m in request.get("messages", [])
                ):
                    repair_calls.append(model_call)
            if repair_calls:
                repairs.append(
                    {
                        "case_id": identifier,
                        "turn_index": index,
                        "model_attempts": len(repair_calls),
                        "recovered_to_safe_business_goal": checks[index] is True and business,
                    }
                )
        if complete and len(times) == len(case["turns"]):
            episode_latency.append(sum(times))

    # Charge ALL scoped attempts, including failed work. Never treat missing usage as zero.
    coverage = bool(live_calls) and len(attempts) == len(live_calls)
    charges, usage_complete = [], coverage
    wire_keys, trace_keys = [], []
    retry_metadata_complete = coverage
    retry_groups = defaultdict(list)
    for identifier, index, call in live_calls:
        request = call.get("request", {})
        trace_keys.append((identifier, index, request.get("logical_call_id"), request.get("attempt_index")))
    for attempt in attempts:
        meta = attempt["metadata"]
        if meta.get("case_id") not in expected:
            raise ValueError("ledger contains unknown case_id")
        tokens = (meta.get("input_tokens"), meta.get("output_tokens"))
        valid_tokens = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in tokens)
        usage_complete &= meta.get("usage_complete") is True and valid_tokens
        charged = attempt.get("charged")
        try:
            charged = Decimal(str(charged))
            valid_charge = charged.is_finite() and charged >= 0
        except Exception:
            valid_charge = False
        usage_complete &= valid_charge and attempt.get("status") == "settled"
        if valid_charge:
            charges.append(charged)
        wire_keys.append(
            (
                meta.get("case_id"),
                meta.get("turn_index"),
                meta.get("logical_call_id"),
                meta.get("attempt_index"),
            )
        )
        valid_retry = (
            bool(meta.get("logical_call_id"))
            and isinstance(meta.get("attempt_index"), int)
            and not isinstance(meta.get("attempt_index"), bool)
            and meta["attempt_index"] >= 1
            and meta.get("is_retry") is (meta["attempt_index"] > 1)
            and meta.get("retry_metadata_complete") is True
        )
        retry_metadata_complete &= valid_retry
        if valid_retry:
            retry_groups[(meta["case_id"], meta["turn_index"], meta["logical_call_id"])].append(attempt)
    # Historical request metadata is insufficient; do not repair/reinterpret old retry fields.
    if coverage and all(key[2] is not None and key[3] is not None for key in trace_keys):
        if Counter(trace_keys) != Counter(wire_keys) or len(set(wire_keys)) != len(wire_keys):
            raise ValueError("ledger/model trace identity mismatch")
    coverage &= Counter(key[:2] for key in trace_keys) == Counter(key[:2] for key in wire_keys)
    usage_complete &= coverage
    retry_metadata_complete &= coverage
    retries = []
    if retry_metadata_complete:
        for key, group in retry_groups.items():
            group.sort(key=lambda a: a["metadata"]["attempt_index"])
            if [a["metadata"]["attempt_index"] for a in group] != list(range(1, len(group) + 1)):
                raise ValueError("non-contiguous retry attempts")
            if len(group) > 1:
                last = group[-1]
                retries.append(
                    {
                        "case_id": key[0],
                        "turn_index": key[1],
                        "logical_call_id": key[2],
                        "attempts": len(group),
                        "http_recovered": last["status"] == "settled"
                        and last["metadata"].get("usage_complete") is True
                        and not last["metadata"].get("error_type"),
                    }
                )
    cost = sum(charges, Decimal(0)) if usage_complete else None
    category_rows = {
        name: {
            "strict_task_success": fraction(c["strict_passed"], c["episodes"]),
            "business_goal_success": fraction(c["business_passed"], c["episodes"]),
        }
        for name, c in sorted(categories.items())
    }
    return {
        "schema_version": "metrics-summary-v1",
        "coverage": {
            "planned_episodes": len(dataset),
            "observed_episodes": len(rows),
            "completed_episodes": counts["completed_episodes"],
            "planned_turns": planned_turns,
            "observed_turns": len(turns),
            "business_unknown_episodes": counts["business_unknown_episodes"],
        },
        "strict_task_success": fraction(counts["strict_passed"], len(dataset)),
        "business_goal_success": fraction(counts["business_passed"], len(dataset)),
        "multi_turn": {
            "strict_task_success": fraction(sum(t["strict"] for t in multi_turn), len(multi_turn)),
            "business_goal_success": fraction(sum(t["business"] for t in multi_turn), len(multi_turn)),
        },
        "categories": category_rows,
        "tool_selection": fraction(sum(t["tool_selection"] for t in turns), planned_turns),
        "tool_arguments": fraction(sum(t["tool_arguments"] for t in turns), planned_turns),
        "required_tool_recall": fraction(sum(t["required_tool_hits"] for t in turns), required_total),
        "safety": {
            "policy_compliance": fraction(counts["policy_compliant_episodes"], len(dataset)),
            "unsafe_observed_turns": sum(t["unsafe_action"] for t in turns),
            "database_failure_episodes": counts["database_failure_episodes"],
            "idempotency": fraction(counts["idempotency_passed"], planned_turns),
        },
        "failure_stages": dict(sorted(stages.items())),
        "latency": {"turn": distribution(latency), "episode_active_time": distribution(episode_latency)},
        "efficiency": {
            "llm_calls": sum(t["llm_calls"] for t in turns),
            "tool_calls": counts["tool_calls"],
            "average_llm_calls_observed_turn": statistics.mean(t["llm_calls"] for t in turns)
            if turns
            else None,
            "average_tool_calls_observed_turn": counts["tool_calls"] / len(turns) if turns else None,
            "terminal_error_observed_turns": sum(
                t["trace"]["run"]["status"] == "FAILED" for row in rows for t in row.get("turns", [])
            ),
            "optional_tool_calls": len(optional),
            "disallowed_tool_calls": len(disallowed),
            "duplicate_same_arguments_calls": len(duplicates),
            "failed_tool_calls": sum(tool_errors.values()),
            "tool_error_types": dict(tool_errors),
            "review_candidates": {
                "optional": optional,
                "disallowed": disallowed,
                "duplicate_same_arguments": duplicates,
            },
        },
        "recovery": {
            "tool_error_turns": fraction(
                sum(t["recovered_to_safe_business_goal"] for t in tool_recovery), len(tool_recovery)
            ),
            "tool_error_evidence": tool_recovery,
            "protocol_repair_turns": fraction(
                sum(t["recovered_to_safe_business_goal"] for t in repairs), len(repairs)
            ),
            "protocol_repair_evidence": repairs,
            "retry_metadata_complete": bool(retry_metadata_complete),
            "http_retry_logical_requests": fraction(sum(t["http_recovered"] for t in retries), len(retries))
            if retry_metadata_complete
            else {"passed": None, "total": None, "rate": None},
            "http_retry_evidence": retries,
        },
        "cost": {
            "attempts": len(attempts),
            "usage_and_cost_complete": bool(usage_complete),
            "amount_proxy": str(cost) if cost is not None else None,
            "per_strict_success_proxy": str(cost / counts["strict_passed"])
            if cost is not None and counts["strict_passed"]
            else None,
            "per_business_success_proxy": str(cost / counts["business_passed"])
            if cost is not None and counts["business_passed"]
            else None,
            "input_tokens": sum(a["metadata"]["input_tokens"] for a in attempts) if usage_complete else None,
            "output_tokens": sum(a["metadata"]["output_tokens"] for a in attempts)
            if usage_complete
            else None,
        },
        "episodes": records,
    }


def load_summary(root, version, split):
    if version not in VERSIONS or split not in ("dev", "holdout"):
        raise ValueError("unsupported dataset schema/version or split")
    data_path = root / "eval" / version / f"{split}.json"
    evidence_version = "reliability-live" if version == "reliability-v1" else version
    folder = root / "docs/verification" / evidence_version / split
    batch_path, summary_path = folder / "batch.json", folder / "summary.json"
    dataset, batch, archived = read(data_path), read(batch_path), read(summary_path)
    if batch["dataset_hash"] != sha(data_path) or batch["split"] != split:
        raise ValueError("dataset hash/split does not match archived batch")
    rows, sources = [], [data_path, batch_path, summary_path]
    for row in archived["cases"]:
        identifier = row["case_id"]
        if identifier not in {c["case_id"] for c in dataset}:
            raise ValueError("unknown case_id in summary")
        path = folder / f"{identifier}.json"
        if path.exists():
            saved = read(path)
            if any(saved.get(key) != value for key, value in row.items()):
                raise ValueError("case evidence differs from archived summary")
            sources.append(path)
        rows.append(row)
    ledger = archived["ledger"]
    attempts = [a for a in ledger["attempts"] if a["metadata"].get("split") == split]
    for attempt in attempts:
        for key in (
            "dataset_hash",
            "configuration_hash",
            "prompt_hash",
            "code_commit",
            "requested_model",
            "tool_schema_hash",
            "product_manifest_hash",
            "runner_sources_hash",
        ):
            if attempt["metadata"].get(key) != batch.get(key):
                raise ValueError("ledger batch provenance mismatch")
    review_path = folder.parent / f"{split}-review.json"
    if review_path.exists():
        review = read(review_path)
        review_summary_hash = review.get("summary_sha256", review.get(f"{split}_summary_sha256"))
        if review_summary_hash != sha(summary_path) or (
            "dataset_sha256" in review and review["dataset_sha256"] != sha(data_path)
        ):
            raise ValueError("archived review hash mismatch")
        sources.append(review_path)
    result = summarize(dataset, rows, attempts)
    result["cost"]["currency"] = ledger["currency"]
    result["source"] = {
        "version": version,
        "split": split,
        "batch": batch,
        "finished_at": archived.get("finished_at"),
        "sha256": {p.relative_to(root).as_posix(): sha(p) for p in sources},
    }
    return result


def percent(metric):
    return (
        "无样本 / 未知"
        if metric["rate"] is None
        else (f"{metric['passed']}/{metric['total']}（{metric['rate']:.2%}）")
    )


def display(value, places=3):
    return "未知 / 无样本" if value is None else f"{Decimal(str(value)):.{places}f}"


def markdown(report):
    cost, latency, recovery = report["cost"], report["latency"], report["recovery"]
    lines = [
        f"# 指标汇总：{report['source']['version']} / {report['source']['split']}",
        "",
        "只读派生报告；未调用模型、未重跑评测、未修改冻结评分。"
        f"来源 hash 及逐任务记录见 [{report['source']['split']}.json]({report['source']['split']}.json)。",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
    ]
    for label, key in (
        ("Strict Task Success（episode）", "strict_task_success"),
        ("业务目标达成（episode）", "business_goal_success"),
        ("Tool Selection（turn）", "tool_selection"),
        ("Tool Arguments（turn）", "tool_arguments"),
        ("Required Tool Recall（micro）", "required_tool_recall"),
    ):
        lines.append(f"| {label} | {percent(report[key])} |")
    lines += [
        f"| 政策/权限契约（episode） | {percent(report['safety']['policy_compliance'])} |",
        f"| 多轮 Strict Task Success（episode） | {percent(report['multi_turn']['strict_task_success'])} |",
        f"| 幂等验证（turn） | {percent(report['safety']['idempotency'])} |",
        f"| Unsafe Action 观察次数 | {report['safety']['unsafe_observed_turns']} |",
        f"| 数据库检查失败 episode | {report['safety']['database_failure_episodes']} |",
        f"| 工具错误后安全业务恢复（turn） | {percent(recovery['tool_error_turns'])} |",
        f"| 结束协议纠正后恢复（turn） | {percent(recovery['protocol_repair_turns'])} |",
        f"| HTTP 重试后恢复（logical request） | {percent(recovery['http_retry_logical_requests'])} |",
        "",
        "## 耗时与成本",
        "",
        "| 范围 | 样本 | 平均 ms | P50 ms | P95 ms |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, label in (("turn", "单轮"), ("episode_active_time", "任务累计活跃时间")):
        d = latency[key]
        lines.append(
            f"| {label} | {d['samples']} | {display(d['mean_ms'])} | "
            f"{display(d['p50_ms'])} | {display(d['p95_ms'])} |"
        )
    lines += [
        "",
        f"成本代理值：{cost.get('currency')} {display(cost['amount_proxy'], 6)}；"
        f"每个严格成功任务：{display(cost['per_strict_success_proxy'], 6)}；"
        f"每个业务成功任务：{display(cost['per_business_success_proxy'], 6)}。",
        f"Input / Output Tokens：{cost['input_tokens']} / {cost['output_tokens']}。"
        f"完整 usage 与费用证据：{cost['usage_and_cost_complete']}。",
        "",
        "## 场景分类",
        "",
        "| Category | Strict Task Success | 业务目标达成 |",
        "|---|---:|---:|",
    ]
    for name, metrics in report["categories"].items():
        lines.append(
            f"| {name} | {percent(metrics['strict_task_success'])} | "
            f"{percent(metrics['business_goal_success'])} |"
        )
    e = report["efficiency"]
    lines += [
        "",
        "## 调用与失败",
        "",
        f"LLM / Tool Calls：{e['llm_calls']} / {e['tool_calls']}；"
        f"可选工具调用 {e['optional_tool_calls']}；不在允许集合 {e['disallowed_tool_calls']}；"
        f"同名同参数重复 {e['duplicate_same_arguments_calls']}；工具失败 {e['failed_tool_calls']}。",
        f"任务失败阶段：`{json.dumps(report['failure_stages'], ensure_ascii=False)}`。",
        "",
        "## 口径与边界",
        "",
        "- 业务目标达成复用归档中的 outcome、动作/金额契约、响应证据、结束类型、政策与数据库检查，"
        "要求运行成功及幂等通过；不因已恢复的参数错误单独判失败。原 Strict 成绩保持不变。",
        "- 这是既定合成任务的业务契约达成率，不是用户满意度、实际到账率或生产成功率。",
        "- 缺失任务/轮次保留计划分母；业务证据未知计入覆盖缺口，不计为通过。"
        f"当前覆盖：`{json.dumps(report['coverage'], ensure_ascii=False)}`。",
        "- Tool Selection 是允许工具名称集合检查，Tool Arguments 按整轮统计；"
        "Required Tool Recall 按必要工具项 micro 汇总。不同历史报告的 macro 值不能直接混用。",
        "- P50 为中位数；P95 为最近秩法。任务时间为各轮运行耗时之和，不包含用户思考或人工审批等待。",
        "- 恢复按实际触发统计；零触发为无样本。工具/协议恢复要求最终任务安全达成业务目标，"
        "HTTP 恢复只表示该逻辑模型请求最终有成功 usage，不代表业务成功。",
        "- 同名同参数重复与可选调用是复核候选，不自动等于浪费；当前没有不必要调用率。",
        "- 成本覆盖整个 split 的所有模型 attempt（包括失败），不是账户余额或提供商账单。"
        "缺 usage、费用或请求对应证据时显示未知，不按零计费。",
        "- 未观察到不安全动作不等于 100% 安全；小样本恢复比例不代表总体可靠性。",
        "- 原始模型请求文本、system prompt、reasoning 与用户消息不复制到本报告；完整轨迹保留在原归档。",
        "",
    ]
    return "\n".join(lines)


def write_reports(root, directory, split, report):
    directory = directory.resolve()
    if not directory.is_relative_to((root / "docs/metrics").resolve()):
        raise ValueError("output must stay under docs/metrics; frozen evidence is read-only")
    content = {
        directory / f"{split}.json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        directory / f"{split}.md": markdown(report),
    }
    # Check all destinations before creating anything. Identical reports are a no-op.
    for path, text in content.items():
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise FileExistsError("refusing to overwrite a different metrics report")
    directory.mkdir(parents=True, exist_ok=True)
    for path, text in content.items():
        if not path.exists():
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
    return list(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=VERSIONS, default=VERSIONS[0])
    parser.add_argument("--split", choices=("dev", "holdout"), default="holdout")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = load_summary(ROOT, args.version, args.split)
    directory = args.output_dir or ROOT / "docs/metrics" / args.version
    paths = write_reports(ROOT, directory, args.split, report)
    print(
        json.dumps(
            {
                "reports": [str(p) for p in paths],
                "strict_task_success": report["strict_task_success"],
                "business_goal_success": report["business_goal_success"],
                "model_calls_made_by_summarizer": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
