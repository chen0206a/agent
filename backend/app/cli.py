import argparse
import json
from datetime import datetime

from app.core.config import Settings
from app.db.seed import SCENARIOS, seed, validate_seed
from app.db.session import initialize, make_engine, make_sessions


def main() -> None:
    parser = argparse.ArgumentParser(description="AfterSale Copilot local simulation management")
    parser.add_argument(
        "command", choices=["init-db", "seed", "check-data", "scenarios", "evaluate", "agent-evaluate"]
    )
    parser.add_argument(
        "--live", action="store_true", help="Explicitly use configured live model for agent evaluation"
    )
    parser.add_argument("--at", help="Timezone-aware ISO time for reproducible seed/evaluation")
    parser.add_argument("--output", help="Evaluation JSON output path")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.at) if args.at else None
    if now and now.tzinfo is None:
        parser.error("--at requires an explicit timezone, for example +00:00")
    settings = Settings()
    if args.command == "agent-evaluate":
        from app.agent.evaluation import evaluate_agent
        from app.agent.provider import ProviderError

        try:
            report = evaluate_agent(settings, live=args.live, output=args.output)
        except ProviderError as error:
            parser.exit(2, error.code + ": configure model and local API key first.\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["failed"] == 0 else 1)
    if args.command == "evaluate":
        from app.evaluation import evaluate

        report = evaluate(settings, now=now, output=args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["failed"] == 0 else 1)
    engine = make_engine(settings.resolved_database_url)
    try:
        sessions = make_sessions(engine)
        if args.command == "init-db":
            initialize(engine)
            print("Database tables initialized (existing data preserved).")
        elif args.command == "seed":
            print(json.dumps(seed(sessions, now=now), ensure_ascii=False, indent=2))
        elif args.command == "scenarios":
            for order_id, label, status, _ in SCENARIOS:
                print(
                    f"order={order_id} user={(order_id - 1001) % 10 + 1} "
                    f"item={order_id * 10 + 1} {status}: {label}"
                )
        else:
            with sessions() as session:
                issues = validate_seed(session)
            print(json.dumps({"valid": not issues, "issues": issues}, ensure_ascii=False, indent=2))
            if issues:
                raise SystemExit(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
