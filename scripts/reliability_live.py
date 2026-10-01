"""Budgeted live evaluation. Frozen product code and gold labels are never edited."""

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import statistics
import subprocess
import time
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from app.agent.contracts import ChatRequest
from app.agent.provider import DeepSeekProvider, ProviderError
from app.agent.runtime import AgentService
from app.core.config import PROJECT_ROOT, Settings
from app.db.seed import seed
from app.db.session import initialize, make_engine, make_sessions
from app.services.business import BusinessService
from app.services.workflow import WorkflowService

SPEC = importlib.util.spec_from_file_location(
    "frozen_contract", Path(__file__).with_name("reliability_eval.py")
)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
ROOT = PROJECT_ROOT
OUT = ROOT / "docs/verification/reliability-live"
MILLION = Decimal(1_000_000)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, value):
    """Flush before replace so interruption leaves either the old or new checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, default=str)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def exclusive_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, default=str)
        output.flush()
        os.fsync(output.fileno())


class BudgetLedger:
    """One shared SQLite ledger for ALL Dev/Holdout batches of this release."""

    def __init__(self, path, terms):
        self.path, self.terms = path, terms
        for key in ("budget_usd", "input_usd_per_million", "output_usd_per_million"):
            value = Decimal(terms[key])
            if not value.is_finite() or value <= 0:
                raise ValueError("Budget and rates must be positive finite decimals")
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS terms (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY, reserved TEXT NOT NULL, charged TEXT,
                status TEXT NOT NULL, metadata TEXT NOT NULL)""")
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            stored = connection.execute("SELECT value FROM terms WHERE id=1").fetchone()
            value = json.dumps(terms, sort_keys=True)
            if stored and stored[0] != value:
                raise ValueError("Existing ledger terms cannot change")
            connection.execute("INSERT OR IGNORE INTO terms VALUES (1, ?)", (value,))
            connection.commit()

    def _state(self, connection):
        rows = connection.execute("SELECT reserved, charged, status FROM attempts").fetchall()
        committed = sum(
            (Decimal(charged if charged is not None else reserved) for reserved, charged, _ in rows),
            Decimal(0),
        )
        blocked = any(status != "settled" for _, _, status in rows)
        return committed, blocked

    def state(self):
        with closing(sqlite3.connect(self.path)) as connection:
            amount, blocked = self._state(connection)
            attempts = [
                dict(zip(("id", "reserved", "charged", "status", "metadata"), row, strict=True))
                for row in connection.execute("SELECT * FROM attempts ORDER BY id")
            ]
        for attempt in attempts:
            attempt["metadata"] = json.loads(attempt["metadata"])
        return {
            "committed_usd_proxy": str(amount),
            "blocked": blocked,
            "attempts": attempts,
            "terms": self.terms,
        }

    def reserve(self, payload, metadata):
        # UTF-8 byte count plus 4096 tokens for provider framing is a conservative proxy,
        # not a proof of proprietary tokenizer bounds or of the final invoice.
        input_bound = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 4096
        output_bound = payload["max_tokens"]
        reserved = (
            Decimal(input_bound) * Decimal(self.terms["input_usd_per_million"])
            + Decimal(output_bound) * Decimal(self.terms["output_usd_per_million"])
        ) / MILLION
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            committed, blocked = self._state(connection)
            if blocked:
                raise ProviderError("BUDGET_UNRESOLVED_ATTEMPT")
            if committed + reserved > Decimal(self.terms["budget_usd"]):
                raise ProviderError("EVALUATION_BUDGET_LIMIT")
            metadata = {
                **metadata,
                "input_reservation_tokens": input_bound,
                "output_reservation_tokens": output_bound,
                "started_at": stamp(),
            }
            cursor = connection.execute(
                "INSERT INTO attempts(reserved,status,metadata) VALUES (?, 'reserved', ?)",
                (str(reserved), json.dumps(metadata, ensure_ascii=False)),
            )
            connection.commit()  # Durable BEFORE any network call.
            return cursor.lastrowid

    def settle(self, identifier, response, *, latency_ms, error=None):
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        valid = all(type(value) is int and value >= 0 for value in (input_tokens, output_tokens))
        cost = (
            (
                Decimal(input_tokens) * Decimal(self.terms["input_usd_per_million"])
                + Decimal(output_tokens) * Decimal(self.terms["output_usd_per_million"])
            )
            / MILLION
            if valid
            else None
        )
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT reserved, status, metadata FROM attempts WHERE id=?", (identifier,)
            ).fetchone()
            if not row or row[1] != "reserved":
                raise ValueError("Attempt already settled or missing")
            # Unknown usage retains its reservation and blocks further calls, even on HTTP errors.
            status = (
                "settled"
                if valid and cost <= Decimal(row[0])
                else "unknown"
                if not valid
                else "over_reservation"
            )
            metadata = json.loads(row[2])
            metadata.update(
                finished_at=stamp(),
                latency_ms=latency_ms,
                error_type=error,
                input_tokens=input_tokens if valid else None,
                output_tokens=output_tokens if valid else None,
                usage_complete=valid,
                provider_returned_model=response.get("model") if isinstance(response, dict) else None,
            )
            connection.execute(
                "UPDATE attempts SET charged=?,status=?,metadata=? WHERE id=?",
                (str(cost) if valid else None, status, json.dumps(metadata), identifier),
            )
            connection.commit()


class MeteredTransport(httpx.BaseTransport):
    def __init__(self, ledger, metadata, delegate=None):
        self.ledger, self.metadata = ledger, metadata
        self.delegate = delegate if delegate is not None else httpx.HTTPTransport(retries=0)
        self.attempt_counts = {}

    def handle_request(self, request):
        payload = json.loads(request.content)
        turn = self.metadata.get("turn_index")
        attempt_index = self.attempt_counts.get(turn, 0) + 1
        identifier = self.ledger.reserve(
            payload,
            {
                **self.metadata,
                "requested_model": payload.get("model"),
                "request_hash": hashlib.sha256(request.content).hexdigest(),
                "attempt_index": attempt_index,
                "is_retry": attempt_index > 1,
            },
        )
        self.attempt_counts[turn] = attempt_index
        start, body, error = time.monotonic(), {}, None
        try:
            response = self.delegate.handle_request(request)
            try:
                raw = bytearray()
                for chunk in response.iter_bytes():
                    limit = request.extensions.get("timeout", {}).get("read")
                    if limit is not None and time.monotonic() - start > limit:
                        raise httpx.ReadTimeout("Evaluation response time limit")
                    raw.extend(chunk)
                    if len(raw) > 250_000:
                        raise ProviderError("MODEL_RESPONSE_TOO_LARGE")
                try:
                    body = json.loads(raw)
                except ValueError:
                    error = "INVALID_PROVIDER_JSON"
                if response.status_code != 200:
                    error = f"PROVIDER_HTTP_{response.status_code}"
                headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key not in {"content-encoding", "content-length"}
                }
                return httpx.Response(response.status_code, headers=headers, content=bytes(raw))
            finally:
                response.close()
        except Exception as failure:
            error = type(failure).__name__  # Do not persist exception strings or credentials.
            raise
        finally:
            self.ledger.settle(
                identifier, body, latency_ms=round((time.monotonic() - start) * 1000), error=error
            )

    def close(self):
        # The provider closes an HTTP client per attempt; the batch owns this shared delegate.
        pass


def runner_sources():
    paths = [ROOT / "scripts/reliability_live.py", ROOT / "backend/tests/test_reliability_live.py"]
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in paths}


def verify_product():
    """Explicit checks still enforce the freeze when Python runs with -O."""
    manifest = contract.read(contract.DATA / "manifest.json")
    if manifest["source_files"] != contract.source_hashes():
        raise ValueError("Frozen product source changed")
    if any(
        sha(contract.DATA / f"{split}.json") != expected for split, expected in manifest["datasets"].items()
    ):
        raise ValueError("Frozen dataset changed")
    if manifest["configuration_hash"] != contract.digest(contract.configuration(Settings())):
        raise ValueError("Frozen configuration changed")


def prepare(terms):
    verify_product()
    if not terms.get("price_source") or not terms.get("price_checked_at"):
        raise ValueError("Pricing source and verification time required")
    release = {
        "created_at": stamp(),
        "product_manifest_hash": sha(contract.DATA / "manifest.json"),
        "runner_sources": runner_sources(),
        "terms": terms,
        "base_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    # Validate terms without consuming API credits.
    ledger = BudgetLedger(OUT / "budget.db", terms)
    if ledger.state()["attempts"]:
        raise ValueError("Release preparation requires an unused ledger")
    exclusive_json(OUT / "release.json", release)


def verify_release():
    verify_product()
    release = contract.read(OUT / "release.json")
    if release["product_manifest_hash"] != sha(contract.DATA / "manifest.json"):
        raise ValueError("Product manifest changed")
    if release["runner_sources"] != runner_sources():
        raise ValueError("Frozen runner changed")
    return release


def seal_holdout(reviewed_dev_hash):
    verify_release()
    dev = contract.read(OUT / "dev/summary.json")
    if not dev["completed"] or dev["episodes"] != 13:
        raise ValueError("Complete Dev once before sealing; review all failures")
    if reviewed_dev_hash != sha(OUT / "dev/summary.json"):
        raise ValueError("Explicit reviewed Dev summary hash required")
    exclusive_json(
        OUT / "holdout-final.json",
        {
            "created_at": stamp(),
            "release_hash": sha(OUT / "release.json"),
            "dev_hash": sha(OUT / "dev/summary.json"),
        },
    )


def metrics(cases, rows, state):
    """Keep planned denominators, including unrun turns after interruption."""
    scores = [turn["score"] for row in rows for turn in row.get("turns", [])]
    turns = sum(len(case["turns"]) for case in cases)
    required = sum(len(turn["expected"]["required_tools"]) for case in cases for turn in case["turns"])
    attempts = state["attempts"]
    complete_usage = all(attempt["metadata"].get("usage_complete") for attempt in attempts)
    return {
        "task_success": sum(row["passed"] for row in rows) / len(cases),
        "planned_turns": turns,
        "observed_turns": len(scores),
        "tool_selection_accuracy": sum(score["tool_selection"] for score in scores) / turns,
        "tool_arguments_accuracy": sum(score["tool_arguments"] for score in scores) / turns,
        "required_tool_recall": sum(score["required_tool_hits"] for score in scores) / required,
        "unsafe_action_observed_turns": sum(score["unsafe_action"] for score in scores),
        "database_failure_episodes": sum(bool(row.get("database_failures")) for row in rows),
        "policy_compliant_episodes": sum(
            bool(row.get("turns"))
            and not row.get("database_failures")
            and not row.get("incomplete_turns", 0)
            and all(turn["score"]["policy_compliance"] for turn in row["turns"])
            for row in rows
        ),
        "average_llm_calls_observed_turns": statistics.mean(score["llm_calls"] for score in scores)
        if scores
        else None,
        "average_tool_calls_observed_turns": statistics.mean(score["tool_calls"] for score in scores)
        if scores
        else None,
        "average_latency_ms_observed_turns": statistics.mean(score["latency_ms"] for score in scores)
        if scores
        else None,
        "all_attempt_usage_complete": complete_usage,
        "input_tokens": sum(attempt["metadata"]["input_tokens"] for attempt in attempts)
        if complete_usage
        else None,
        "output_tokens": sum(attempt["metadata"]["output_tokens"] for attempt in attempts)
        if complete_usage
        else None,
    }


def run(split):
    if split not in {"dev", "holdout"}:
        raise ValueError("Unknown split")
    release = verify_release()
    settings = Settings()
    if not settings.llm_model or not settings.llm_api_key.get_secret_value():
        raise ValueError("Model credentials are not configured")
    ledger = BudgetLedger(OUT / "budget.db", release["terms"])
    if ledger.state()["blocked"]:
        raise ValueError("Unresolved ledger attempt: stop and reconcile before any new call")
    if split == "holdout":
        final = contract.read(OUT / "holdout-final.json")
        if final["release_hash"] != sha(OUT / "release.json") or final["dev_hash"] != sha(
            OUT / "dev/summary.json"
        ):
            raise ValueError("Final Holdout seal changed")
    cases = contract.read(contract.DATA / f"{split}.json")
    folder = OUT / split
    exclusive_json(OUT / "batch.lock", {"pid": os.getpid(), "started_at": stamp(), "split": split})
    started = False
    try:
        exclusive_json(
            OUT / f"{split}.started.json", {"started_at": stamp(), "release_hash": sha(OUT / "release.json")}
        )
        started = True
        folder.mkdir(exist_ok=False)
        metadata = {
            "split": split,
            "requested_model": settings.llm_model,
            "configuration_hash": contract.digest(contract.configuration(settings)),
            "prompt_hash": contract.digest(contract.SYSTEM_PROMPT),
            "tool_schema_hash": contract.digest(contract.tool_definitions()),
            "dataset_hash": sha(contract.DATA / f"{split}.json"),
            "product_manifest_hash": release["product_manifest_hash"],
            "runner_sources_hash": contract.digest(release["runner_sources"]),
            "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "started_at": stamp(),
        }
        atomic_json(folder / "batch.json", metadata)
        rows, stopped = [], None
        for case in cases:
            if stopped:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "passed": False,
                        "not_run": True,
                        "failure_stage": "batch_stop",
                        "error_type": stopped,
                    }
                )
                continue
            path = folder / f"{case['case_id']}.db"
            engine = make_engine("sqlite:///" + path.as_posix())
            before, turns, after, error = {}, [], {}, None
            transport = MeteredTransport(ledger, {**metadata, "case_id": case["case_id"]})
            try:
                initialize(engine)
                sessions = make_sessions(engine)
                seed(sessions, now=contract.NOW)
                before = contract.snapshot(path)
                business = BusinessService(sessions)
                workflow = WorkflowService(sessions, settings, clock=lambda: contract.NOW)
                service = AgentService(
                    sessions,
                    settings,
                    business,
                    workflow,
                    lambda: DeepSeekProvider(settings, transport=transport),
                )
                parent, scoped_order = None, None
                for index, turn in enumerate(case["turns"]):
                    transport.metadata["turn_index"] = index
                    scoped_order = turn["request"]["order_id"] or scoped_order
                    request = ChatRequest(
                        **turn["request"], parent_run_id=parent, idempotency_key=f"{case['case_id']}-{index}"
                    )
                    result = service.chat(case["user_id"], request)
                    trace = service.trace(result.run_id).model_dump(mode="json")
                    db_after = contract.snapshot(path)
                    repeat = service.chat(case["user_id"], request)
                    unchanged = (
                        repeat.run_id == result.run_id
                        and contract.snapshot(path) == db_after
                        and service.trace(result.run_id).model_dump(mode="json") == trace
                    )
                    score = contract.assess_turn(turn, trace, case["user_id"], scoped_order)
                    if not unchanged:
                        score["task_success"] = False
                        score["failure_reasons"].append("idempotency")
                    turns.append({"trace": trace, "score": score, "idempotent_repeat": unchanged})
                    atomic_json(
                        folder / f"{case['case_id']}.partial.json",
                        {"turns": turns, "before": before, "after": db_after},
                    )
                    parent = result.run_id
                    if ledger.state()["blocked"] or result.error_type in {
                        "EVALUATION_BUDGET_LIMIT",
                        "BUDGET_UNRESOLVED_ATTEMPT",
                    }:
                        stopped = result.error_type or "UNRESOLVED_USAGE"
                        break
            except Exception as failure:
                error = type(failure).__name__
                stopped = error
            finally:
                if before:
                    after = contract.snapshot(path)
                transport.delegate.close()
                engine.dispose()
            db_failures = (
                contract.assess_database(case, before, after) if before and after else ["fixture_incomplete"]
            )
            passed = (
                not error
                and not db_failures
                and len(turns) == len(case["turns"])
                and all(turn["score"]["task_success"] for turn in turns)
            )
            row = {
                "case_id": case["case_id"],
                "passed": passed,
                "turns": turns,
                "database_failures": db_failures,
                "error_type": error,
                "failure_stage": "runner"
                if error
                else "database"
                if db_failures
                else next(
                    (
                        turn["score"]["runtime_failure_stage"] or turn["score"]["evaluation_failure_stage"]
                        for turn in turns
                        if not turn["score"]["task_success"]
                    ),
                    None,
                ),
                "incomplete_turns": len(case["turns"]) - len(turns),
            }
            atomic_json(folder / f"{case['case_id']}.json", {**row, "before": before, "after": after})
            rows.append(row)
            atomic_json(folder / "progress.json", {"cases": rows, "ledger": ledger.state()})
        summary = {
            "episodes": len(cases),
            "passed": sum(row["passed"] for row in rows),
            "completed": not stopped,
            "batch_stop": stopped,
            "finished_at": stamp(),
            "cases": rows,
            "ledger": ledger.state(),
            "metrics": metrics(
                cases,
                rows,
                {
                    **ledger.state(),
                    "attempts": [
                        attempt
                        for attempt in ledger.state()["attempts"]
                        if attempt["metadata"].get("split") == split
                    ],
                },
            ),
            "metrics_scope": "synthetic frozen contract cases",
        }
        atomic_json(folder / "summary.json", summary)
        print(json.dumps({key: value for key, value in summary.items() if key not in {"cases", "ledger"}}))
    finally:
        # A process crash leaves the lock/marker in place. No automatic paid replay or marker deletion.
        (OUT / "batch.lock").unlink()
        if started:
            atomic_json(OUT / "budget-export.json", ledger.state())


def audit(split):
    """Read durable checkpoints after interruption; never rerun a model or business action."""
    if not (OUT / f"{split}.started.json").exists() or not (OUT / "budget.db").exists():
        raise ValueError("No durable batch start/ledger to audit")
    cases = contract.read(contract.DATA / f"{split}.json")
    manifest = contract.read(contract.DATA / "manifest.json")
    if sha(contract.DATA / f"{split}.json") != manifest["datasets"][split]:
        raise ValueError("Audit dataset changed")
    release = contract.read(OUT / "release.json")
    ledger = BudgetLedger(OUT / "budget.db", release["terms"])
    rows = []
    for case in cases:
        path = OUT / split / f"{case['case_id']}.json"
        if path.exists():
            saved = contract.read(path)
            rows.append({key: value for key, value in saved.items() if key not in {"before", "after"}})
        else:
            partial = OUT / split / f"{case['case_id']}.partial.json"
            rows.append(
                {
                    "case_id": case["case_id"],
                    "passed": False,
                    "not_run": not partial.exists(),
                    "failure_stage": "incomplete_checkpoint",
                    "turns": [],
                    "incomplete_turns": len(case["turns"]),
                    "database_state_unverified": True,
                }
            )
    report = {
        "mode": "checkpoint-audit-only",
        "created_at": stamp(),
        "api_calls_by_audit": 0,
        "episodes": len(cases),
        "passed": sum(row["passed"] for row in rows),
        "cases": rows,
        "ledger": ledger.state(),
        "warning": "Uncheckpointed execution remains unknown; markers/locks are not removed",
    }
    atomic_json(OUT / split / "audit.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in {"cases", "ledger"}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("prepare")
    for name in (
        "budget-usd",
        "input-usd-per-million",
        "output-usd-per-million",
        "price-source",
        "price-checked-at",
    ):
        setup.add_argument("--" + name, required=True)
    sub.add_parser("verify")
    seal = sub.add_parser("seal-holdout")
    seal.add_argument("--reviewed-dev-hash", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("split", choices=["dev", "holdout"])
    inspect = sub.add_parser("audit")
    inspect.add_argument("split", choices=["dev", "holdout"])
    args = parser.parse_args()
    if args.command == "prepare":
        prepare({key: value for key, value in vars(args).items() if key != "command"})
    elif args.command == "verify":
        verify_release()
    elif args.command == "seal-holdout":
        seal_holdout(args.reviewed_dev_hash)
    elif args.command == "audit":
        audit(args.split)
    else:
        run(args.split)
