"""Reject misleading green benchmarks and preserve independent trial accounting."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts.dev import benchmark_evidence
from scripts.dev.benchmark_evidence import gate_policy, require_reports
from scripts.dev.task_benchmark_report import passes_gate, summarize_trials

TASKS = [
    {"task_id": "create", "instruction": "create a customer", "domain": "customers"},
    {"task_id": "reject", "instruction": "reject unsafe SQL", "domain": "safety"},
]


def outcomes(trial=0, *, create=True, reject=True):
    return [
        {"task_id": "create", "trial": trial, "pass": create},
        {"task_id": "reject", "trial": trial, "pass": reject},
    ]


def test_all_failed_results_are_red_at_default_policy(monkeypatch):
    monkeypatch.delenv("TASK_BENCHMARK_MODE", raising=False)
    monkeypatch.delenv("TASK_BENCHMARK_MIN_PASS", raising=False)
    mode, minimum = gate_policy()
    assert mode == "gate"
    report = summarize_trials(TASKS, [outcomes(create=False, reject=False)])
    assert not passes_gate(report, minimum)


@pytest.mark.parametrize("value", ["0", "-1", "1.01", "nan", "inf"])
def test_invalid_acceptance_threshold_is_rejected(monkeypatch, value):
    monkeypatch.setenv("TASK_BENCHMARK_MODE", "gate")
    monkeypatch.setenv("TASK_BENCHMARK_MIN_PASS", value)
    with pytest.raises(ValueError):
        gate_policy()


def test_zero_threshold_requires_explicit_observation(monkeypatch):
    monkeypatch.setenv("TASK_BENCHMARK_MODE", "observe")
    monkeypatch.setenv("TASK_BENCHMARK_MIN_PASS", "0")
    assert gate_policy() == ("observe", 0)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"task_id": "create", "trial": 0, "pass": True}] * 2,
        [{"task_id": "unknown", "trial": 0, "pass": True}] * 2,
    ],
)
def test_missing_duplicate_and_unknown_results_never_count_as_success(rows):
    with pytest.raises(ValueError):
        summarize_trials(TASKS, [rows])


@pytest.mark.parametrize("value", ["true", "false", 1, None])
def test_only_boolean_outcomes_are_accepted(value):
    rows = outcomes()
    rows[0]["pass"] = value
    with pytest.raises(ValueError):
        summarize_trials(TASKS, [rows])


def test_repeated_trial_cannot_masquerade_as_independent_runs():
    with pytest.raises(ValueError):
        summarize_trials(TASKS, [outcomes(), outcomes()])


def test_reliability_requires_every_trial_and_protects_safety():
    report = summarize_trials(TASKS, [outcomes(), outcomes(1, create=False)])
    assert report["pass_k"] == 0.5
    assert report["pass_at_k"] == 1.0
    assert report["passed_all_trials"] == 1
    safety = summarize_trials(TASKS, [outcomes(reject=False)])
    assert not passes_gate(safety, 0.1)


def test_missing_reports_are_not_a_successful_publish(tmp_path):
    with pytest.raises(FileNotFoundError):
        require_reports(tmp_path, "a" * 40)


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha": "b" * 40},
        {"tracked_source_dirty": True},
        {"acceptance_mode": "observe"},
        {"gate_passed": False},
        {"dataset_sha256": None},
    ],
)
def test_stale_dirty_observation_and_failed_reports_cannot_publish(tmp_path, change):
    payload = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "tracked_source_dirty": False,
        "acceptance_mode": "gate",
        "gate_passed": True,
        "dataset_sha256": "d" * 64,
        "captured_at": "2026-09-08T00:00:00+00:00",
        **change,
    }
    for name in ("intent_benchmark_latest.json", "task_benchmark_report.json"):
        (tmp_path / name).write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        require_reports(tmp_path, "a" * 40)


@pytest.fixture
def verified_artifacts(tmp_path, monkeypatch):
    project = tmp_path / "FHD"
    datasets = project / "tests" / "benchmarks"
    datasets.mkdir(parents=True)
    monkeypatch.setattr(benchmark_evidence, "PROJECT_ROOT", project)
    intent = datasets / "intent_golden_set.json"
    task = datasets / "task_golden_set.json"
    intent.write_text(json.dumps([{"text": "hello"}]))
    task.write_text(json.dumps({"tasks": TASKS}))
    common = {
        "schema_version": 1,
        "source_sha": "a" * 40,
        "tracked_source_dirty": False,
        "acceptance_mode": "gate",
        "gate_passed": True,
        "captured_at": "2026-09-08T00:00:00Z",
    }
    intent_report = {
        **common,
        "dataset_sha256": hashlib.sha256(intent.read_bytes()).hexdigest(),
        "min_required": 1.0,
        "tier_accuracy": {"core": 1.0},
        "total": 1,
    }
    trials = [outcomes(i) for i in range(3)]
    artifacts = []
    for i, rows in enumerate(trials):
        path = tmp_path / f"task_benchmark_trial_{i}.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        artifacts.append(benchmark_evidence.trial_artifact(path))
    task_report = {
        **common,
        **summarize_trials(TASKS, trials),
        "min_required": 1.0,
        "dataset_sha256": hashlib.sha256(task.read_bytes()).hexdigest(),
        "trial_artifacts": artifacts,
    }
    (tmp_path / "intent_benchmark_latest.json").write_text(json.dumps(intent_report))
    (tmp_path / "task_benchmark_report.json").write_text(json.dumps(task_report))
    return tmp_path


def test_complete_receipt_is_verified_from_raw_artifacts(verified_artifacts):
    require_reports(verified_artifacts, "a" * 40)


def test_tampered_outcome_cannot_publish_with_old_summary(verified_artifacts):
    path = verified_artifacts / "task_benchmark_trial_1.jsonl"
    path.write_text(path.read_text().replace('"pass": true', '"pass": false'))
    report_path = verified_artifacts / "task_benchmark_report.json"
    report = json.loads(report_path.read_text())
    report["trial_artifacts"][1] = benchmark_evidence.trial_artifact(path)
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="summary differs"):
        require_reports(verified_artifacts, "a" * 40)
