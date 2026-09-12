"""Reproducible acceptance checks; all business mutations use isolated test databases."""

import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from app.core.config import PROJECT_ROOT


def main() -> None:
    output_dir = PROJECT_ROOT / "docs/verification"
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = [
        ("pytest", ["-m", "pytest", "-q", "--tb=short", "--junitxml=docs/verification/pytest.xml"]),
        ("ruff-check", ["-m", "ruff", "check", "backend", "scripts"]),
        ("ruff-format", ["-m", "ruff", "format", "--check", "backend", "scripts"]),
        ("pip-check", ["-m", "pip", "check"]),
        ("policy-eval", ["-m", "app.cli", "evaluate", "--output", "eval/latest-report.json"]),
        ("http-smoke", ["scripts/smoke_http.py"]),
        ("agent-eval", ["-m", "app.cli", "agent-evaluate", "--output", "eval/agent-offline-report.json"]),
        ("agent-http-smoke", ["scripts/smoke_http.py", "--agent-fixture"]),
    ]
    results = []
    for name, arguments in commands:
        start = time.perf_counter()
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=180,
        )
        (output_dir / f"{name}.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
        results.append(
            {
                "name": name,
                "exit_code": result.returncode,
                "duration_seconds": round(time.perf_counter() - start, 2),
            }
        )
        print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
    suite = ET.parse(output_dir / "pytest.xml").getroot().find("testsuite")
    report = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "passed": all(row["exit_code"] == 0 for row in results),
        "tests": int(suite.attrib["tests"]),
        "failures": int(suite.attrib["failures"]),
        "errors": int(suite.attrib["errors"]),
        "steps": results,
    }
    (output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
