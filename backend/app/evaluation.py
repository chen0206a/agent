import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings
from app.db.seed import seed
from app.db.session import initialize, make_engine, make_sessions
from app.schemas.api import ActionCreate, TicketCreate
from app.services.business import BusinessService
from app.services.workflow import WorkflowService


def evaluate(settings: Settings, *, now: datetime | None = None, output: str | None = None) -> dict:
    """Golden policy cases run in a fresh temporary database, never the demo database."""
    now = now or datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    cases = json.loads((PROJECT_ROOT / "eval/cases.json").read_text(encoding="utf-8"))
    rows = []
    with tempfile.TemporaryDirectory(prefix="aftersale-eval-") as directory:
        engine = make_engine("sqlite:///" + (Path(directory) / "eval.db").as_posix())
        try:
            initialize(engine)
            sessions = make_sessions(engine)
            seed(sessions, now=now)
            business = BusinessService(sessions)
            for index, case in enumerate(cases):
                order_id = case["order_id"]
                user_id = business.get_order(order_id).user_id if order_id else 1
                ticket = business.create_ticket(
                    TicketCreate(
                        user_id=user_id,
                        order_id=order_id,
                        issue_type=case["issue"],
                        description=case["name"],
                    )
                )
                quantity = case.get("quantity")
                data = ActionCreate(
                    ticket_id=ticket.id,
                    proposed_action=case["action"],
                    quantity=quantity,
                    order_item_id=order_id * 10 + 1 if quantity else None,
                    evidence_provided=case.get("evidence", False),
                    idempotency_key=f"eval-{index:08}",
                )
                at = now + timedelta(seconds=case.get("offset_seconds", 0))
                workflow = WorkflowService(sessions, settings, clock=lambda: at)
                actual = workflow.preview(data).model_dump(mode="json")
                checks = {
                    "decision": actual["decision"] == case["expected_decision"],
                    "action": actual["authorized_action"] == case["expected_action"],
                    "amount": actual["amount"] == case["expected_amount"],
                    "rule": case["expected_rule"] in actual["rule_codes"],
                }
                rows.append(
                    {
                        "name": case["name"],
                        "passed": all(checks.values()),
                        "checks": checks,
                        "expected": {k: v for k, v in case.items() if k.startswith("expected_")},
                        "actual": actual,
                    }
                )
        finally:
            engine.dispose()
    passed = sum(row["passed"] for row in rows)
    report = {
        "suite": "Stage 2 deterministic demo policy",
        "base_time": now.isoformat(),
        "policy_version": workflow.policy.version,
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "pass_rate": passed / len(rows),
        "llm_calls": 0,
        "cases": rows,
    }
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
