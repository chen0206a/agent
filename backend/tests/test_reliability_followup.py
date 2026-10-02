"""No paid calls: the follow-up must not reuse or overwrite historical experiments."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("followup_test", ROOT / "scripts/reliability_followup.py")
followup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(followup)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "cases"
    monkeypatch.setattr(followup, "DATA", data)
    monkeypatch.setattr(followup.contract, "DATA", data)
    monkeypatch.setattr(followup.contract, "OUT", tmp_path / "offline")
    monkeypatch.setattr(followup.live, "OUT", tmp_path / "live")
    return data


def test_new_wording_has_fixed_counts_and_no_historical_exact_overlap(isolated):
    result = followup.build()
    assert result["episodes"] == 39 and result["turns"] == 45
    assert result["historical_exact_overlap"] == 0
    assert result["historical_dataset_hashes"]


def test_followup_output_is_separate_and_old_modules_are_not_modified():
    assert followup.OUT.name == followup.VERSION
    assert followup.live.OUT == followup.OUT
    assert followup.contract.DATA.name != "reliability-v1"


def test_existing_dataset_cannot_be_overwritten(isolated):
    followup.build()
    original = (isolated / "holdout.json").read_bytes()
    with pytest.raises(ValueError, match="never overwrite"):
        followup.build()
    assert (isolated / "holdout.json").read_bytes() == original


def test_historical_message_leak_is_rejected(isolated):
    followup.build()
    cases = followup.contract.read(isolated / "holdout.json")
    old = followup.contract.read(ROOT / "eval/reliability-v1/holdout.json")
    cases[0]["turns"][0]["request"]["message"] = old[0]["turns"][0]["request"]["message"]
    followup.live.atomic_json(isolated / "holdout.json", cases)
    with pytest.raises(ValueError, match="historical"):
        followup.validate()


@pytest.mark.parametrize("currency,budget", [("USD", "5.00"), ("CNY", "10.00")])
def test_unapproved_budget_cannot_prepare_a_ledger(isolated, currency, budget):
    followup.live.atomic_json(
        isolated / "pricing.json", {"terms": {"currency": currency, "budget_amount": budget}}
    )
    with pytest.raises(ValueError, match="authorized"):
        followup.prepare()
    assert not (followup.live.OUT / "budget.db").exists()


def test_holdout_mutation_is_rejected_by_shared_runtime_guard(isolated, monkeypatch):
    followup.build()
    cfg = followup.contract.Settings(_env_file=None)
    monkeypatch.setattr(followup.live, "Settings", lambda: cfg)
    monkeypatch.setattr(followup.contract, "source_hashes", lambda: {"product": "frozen"})
    followup.live.atomic_json(
        isolated / "manifest.json",
        {
            "source_files": {"product": "frozen"},
            "datasets": {
                split: followup.live.sha(isolated / f"{split}.json") for split in ("dev", "holdout")
            },
            "configuration_hash": followup.contract.digest(followup.contract.configuration(cfg)),
        },
    )
    followup.live.verify_product()
    with (isolated / "holdout.json").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="dataset changed"):
        followup.live.verify_product()


def test_single_start_guard_and_runner_sources_include_adapter(isolated):
    sources = followup.runner_sources()
    assert "scripts/reliability_followup.py" in sources
    marker = followup.live.OUT / "holdout.started.json"
    followup.live.exclusive_json(marker, {"first": True})
    with pytest.raises(FileExistsError):
        followup.live.exclusive_json(marker, {"second": True})
    assert followup.contract.read(marker) == {"first": True}
