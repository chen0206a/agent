"""Back up the configured SQLite database, add tables, verify existing rows unchanged."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from app.core.config import PROJECT_ROOT, Settings
from app.db.session import initialize, make_engine
from sqlalchemy.engine import make_url


def snapshot(connection):
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    result = {}
    for (table,) in tables:
        escaped = table.replace('"', '""')
        rows = connection.execute(f'SELECT * FROM "{escaped}" ORDER BY rowid').fetchall()
        value = json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8")
        result[table] = {"rows": len(rows), "sha256": hashlib.sha256(value).hexdigest()}
    return result


def main():
    url = Settings().resolved_database_url
    parsed = make_url(url)
    if parsed.drivername != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise SystemExit("This upgrade helper supports a local SQLite file only.")
    from pathlib import Path

    database = Path(parsed.database)
    if not database.is_file():
        raise SystemExit("Database does not exist. For a fresh installation use init-db and seed.")
    directory = PROJECT_ROOT / "data/backups"
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = directory / f"before-stage4-{timestamp}.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        before = snapshot(source)
        with sqlite3.connect(backup) as destination:
            source.backup(destination)
    engine = make_engine(url)
    try:
        initialize(engine)
    finally:
        engine.dispose()
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        after = snapshot(source)
    unchanged = all(after.get(table) == value for table, value in before.items())
    report = {
        "backup": str(backup.relative_to(PROJECT_ROOT)),
        "existing_rows_unchanged": unchanged,
        "before": before,
        "after": after,
    }
    output = PROJECT_ROOT / "docs/verification/stage4/database-upgrade.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Backup: {backup}")
    print(f"Tables: {len(before)} -> {len(after)}; existing rows unchanged: {unchanged}")
    if not unchanged:
        raise SystemExit("Existing data changed unexpectedly; inspect the report before continuing.")


if __name__ == "__main__":
    main()
