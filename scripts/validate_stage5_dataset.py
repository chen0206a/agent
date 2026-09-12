"""Pre-freeze oracle and fixture audit. Never sends an HTTP model request."""

import json
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.schemas.api import ActionCreate, TicketCreate
from app.services.business import BusinessService
from app.services.workflow import WorkflowService
from stage5 import DATA, NOW, OUT, db_read, digest, read, save, setup_fixture, sha


def main():
    if (DATA / "manifest.json").exists():
        raise SystemExit("Already frozen")
    cases = read(DATA / "dev.json") + read(DATA / "test.json")
    checks = []
    assert len({c["case_id"] for c in cases}) == 125
    assert (
        len({json.dumps(c["parent_history"], ensure_ascii=False) + c["user_message"] for c in cases}) == 125
    )
    assert not (
        {c["family_id"] for c in cases if c["split"] == "dev"}
        & {c["family_id"] for c in cases if c["split"] == "test"}
    )
    cfg = Settings(_env_file=None, llm_api_key="", llm_model="")
    for case in cases:
        with tempfile.TemporaryDirectory(prefix="stage5-oracle-") as directory:
            engine, sessions = setup_fixture(Path(directory) / "case.db", case)
            try:
                record = {
                    "case_id": case["case_id"],
                    "fixture_valid": True,
                    "fixture_hash": digest(db_read(Path(directory) / "case.db")),
                    "oracle_checked": False,
                }
                if case["expected_policy_decision"] is not None:
                    b = BusinessService(sessions)
                    w = WorkflowService(sessions, cfg, clock=lambda: NOW)
                    ticket = b.create_ticket(
                        TicketCreate(
                            user_id=case["user_id"],
                            order_id=case["initial_database_fixture"]["order_id"],
                            issue_type=case["issue"],
                            description=case["user_message"],
                        )
                    )
                    args = {
                        "ticket_id": ticket.id,
                        "proposed_action": case["proposed_action"],
                        "evidence_provided": case["evidence_provided"],
                        "idempotency_key": "offline-oracle-check",
                    }
                    if case["proposed_action"] != "CANCEL_AND_REFUND":
                        args.update(order_item_id=case["item_id"], quantity=case["quantity"])
                    result = w.submit(ActionCreate(**args))
                    actual = [
                        result.decision.value,
                        result.authorized_action.value if result.authorized_action else None,
                        f"{result.amount:.2f}",
                    ]
                    expected = [
                        case["expected_policy_decision"],
                        case["expected_authorized_action"],
                        case["expected_amount"],
                    ]
                    if actual != expected:
                        raise AssertionError((case["case_id"], actual, expected))
                    record.update(oracle_checked=True, actual=actual)
                checks.append(record)
            finally:
                engine.dispose()
    save(
        OUT / "preflight-oracles.json",
        {"live_api_calls": 0, "checks": checks, "total": len(checks), "passed": True},
    )
    files = {name: sha((DATA / name).read_bytes()) for name in ["dev.json", "test.json"]}
    save(
        DATA / "manifest.json",
        {
            "version": "stage5-dataset-v1",
            "files": files,
            "dataset_hash": digest(files),
            "cases": 125,
            "dev": 75,
            "test": 50,
            "categories": 25,
            "frozen_before_live": True,
            "fixture_oracle_validation": "docs/verification/stage5/preflight-oracles.json",
        },
    )
    print(
        "Frozen dataset:",
        digest(files),
        "125 fixtures valid; manual numeric expectations agree with unchanged business engine",
    )


if __name__ == "__main__":
    main()
