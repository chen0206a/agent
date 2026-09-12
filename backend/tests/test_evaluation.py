from app.core.config import Settings
from app.evaluation import evaluate


def test_golden_policy_suite_in_isolated_database(tmp_path):
    output = tmp_path / "report.json"
    report = evaluate(Settings(_env_file=None), output=str(output))
    assert report["total"] == 28
    assert report["failed"] == 0, [row for row in report["cases"] if not row["passed"]]
    assert output.exists()
    assert report["llm_calls"] == 0
