"""Only complete, versioned task trials may support benchmark acceptance."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts.dev import benchmark_evidence as evidence
from scripts.dev import verify_task_benchmark_evidence as verifier
from scripts.dev.task_benchmark_report import summarize_trials


@pytest.fixture
def holdout(tmp_path, monkeypatch):
    dataset = tmp_path / "tests/benchmarks/task_holdout_set.json"
    dataset.parent.mkdir(parents=True)
    tasks = [{"task_id": "create", "instruction": "create a fixture", "domain": "customers"}]
    dataset.write_text(json.dumps({"tasks": tasks}))
    (dataset.parent / "task_golden_set.json").write_text(dataset.read_text())
    identity = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "tracked_source_dirty": False,
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "captured_at": "2026-11-23T00:00:00Z",
        "ci_run_id": "123",
        "ci_run_attempt": "1",
    }
    monkeypatch.setattr(verifier, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evidence, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evidence,
        "evidence_identity",
        lambda path, **kwargs: {**identity, "dataset": path.name},
    )
    monkeypatch.setenv("XCAGI_BENCHMARK_REPORT_DIR", str(tmp_path))

    def write(*, success=True, responses=1, mode="observe", benchmark_set="holdout", **changes):
        rows = [
            [{"task_id": "create", "trial": i, "pass": success, "model_responses": responses}]
            for i in range(3)
        ]
        artifacts = []
        for i, trial in enumerate(rows):
            path = tmp_path / f"task_benchmark_trial_{i}.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in trial) + "\n")
            artifacts.append(evidence.trial_artifact(path))
        report = {
            **identity,
            **summarize_trials(tasks, rows),
            "set": benchmark_set,
            "dataset": f"task_{benchmark_set}_set.json",
            "acceptance_mode": mode,
            "execution_mode": "model_workflow" if responses else "rule_only",
            "min_required": 1.0 if mode == "gate" else 0.0,
            "gate_passed": mode == "gate" and success,
            "model_responses": 3 * responses,
            "trial_artifacts": artifacts,
            **changes,
        }
        name = (
            "task_holdout_report.json"
            if benchmark_set == "holdout"
            else "task_benchmark_report.json"
        )
        (tmp_path / name).write_text(json.dumps(report))
        return report

    return tmp_path, write


def test_complete_failed_observation_is_not_acceptance(holdout):
    directory, write = holdout
    write(success=False)
    marker = verifier.write_task_evidence()
    assert marker["status"] == "OBSERVED"
    assert marker["llm_verified"] is True
    assert marker["gate_passed"] is False
    assert marker["evidence"]["pass_k"] == 0
    assert marker["source_sha"] == marker["sha"] == "a" * 40
    assert (directory / "task_holdout_run_mode.json").is_file()


def test_real_model_receipts_and_passing_gate_are_distinct(holdout):
    _, write = holdout
    write(mode="gate")
    marker = verifier.write_task_evidence(minimum=1.0)
    assert marker["status"] == "VERIFIED" and marker["gate_passed"] is True
    write(responses=0)
    marker = verifier.write_task_evidence()
    assert marker["status"] == "UNVERIFIED" and marker["llm_verified"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha": "b" * 40},
        {"tracked_source_dirty": True},
        {"dataset_sha256": "b" * 64},
        {"ci_run_id": "456"},
        {"ci_run_attempt": "2"},
        {"model_responses": 1},
        {"model_responses": True},
        {"execution_mode": "rule_only"},
        {"gate_passed": True},
        {"trial_artifacts": []},
    ],
)
def test_unrelated_or_incomplete_reports_cannot_be_stamped_verified(holdout, changes):
    directory, write = holdout
    write(**changes)
    with pytest.raises(ValueError):
        verifier.write_task_evidence()
    assert not (directory / "task_holdout_run_mode.json").exists()


@pytest.mark.parametrize("success,responses", [(False, 1), (True, 0)])
def test_failed_or_rule_only_gate_cannot_pass_verification(holdout, success, responses):
    _, write = holdout
    write(mode="gate", success=success, responses=responses)
    with pytest.raises(ValueError):
        verifier.write_task_evidence(minimum=1.0)


def test_original_trial_is_required_even_when_summary_claims_success(holdout):
    directory, write = holdout
    write()
    (directory / "task_benchmark_trial_1.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="checksum"):
        verifier.write_task_evidence()


def test_rejected_retry_removes_previous_verification_marker(holdout):
    directory, write = holdout
    write(mode="gate")
    verifier.write_task_evidence(minimum=1.0)
    write(source_sha="b" * 40)
    with pytest.raises(ValueError):
        verifier.write_task_evidence()
    assert not (directory / "task_holdout_run_mode.json").exists()


def test_golden_acceptance_uses_same_raw_evidence_verifier(holdout):
    directory, write = holdout
    write(benchmark_set="golden", mode="gate")
    marker = verifier.write_task_evidence("golden", minimum=0.4)
    assert marker["mode"] == "acceptance" and marker["status"] == "VERIFIED"
    assert (directory / "benchmark_run_mode.json").is_file()


@pytest.mark.parametrize("minimum", [None, 0, float("nan"), 0.4])
def test_report_cannot_lower_or_omit_independent_gate_threshold(holdout, minimum):
    _, write = holdout
    write(benchmark_set="golden", mode="gate", min_required=0.2)
    with pytest.raises(ValueError, match="independently configured"):
        verifier.write_task_evidence("golden", minimum=minimum)


def test_golden_observation_cannot_be_promoted_to_acceptance(holdout):
    _, write = holdout
    write(benchmark_set="golden")
    with pytest.raises(ValueError, match="observation-only"):
        verifier.write_task_evidence("golden", minimum=0.4)
