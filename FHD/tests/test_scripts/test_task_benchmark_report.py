"""Reject misleading green benchmarks and preserve independent trial accounting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from scripts.dev import benchmark_evidence
from scripts.dev.benchmark_evidence import gate_policy, require_reports
from scripts.dev.task_benchmark_report import (
    classify_trial_failure,
    passes_gate,
    summarize_trials,
)

TASKS = [
    {"task_id": "create", "instruction": "create a customer", "domain": "customers"},
    {"task_id": "reject", "instruction": "reject unsafe SQL", "domain": "safety"},
]


def outcomes(trial=0, *, create=True, reject=True):
    return [
        {
            "task_id": "create",
            "trial": trial,
            "pass": create,
            "runtime_admitted": True,
            "exec_pass": create,
        },
        {
            "task_id": "reject",
            "trial": trial,
            "pass": reject,
            "runtime_admitted": True,
            "exec_pass": reject,
        },
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


@pytest.fixture
def producer(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "benchmarks" / "test_task_success.py"
    spec = importlib.util.spec_from_file_location("task_benchmark_producer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dataset = tmp_path / "task_golden_set.json"
    dataset.write_text(json.dumps({"tasks": TASKS}))
    monkeypatch.setenv("XCAGI_BENCHMARK_REPORT_DIR", str(tmp_path))
    monkeypatch.setenv("TASK_BENCHMARK_TRIALS", "3")
    monkeypatch.setenv("TASK_BENCHMARK_MODE", "gate")
    monkeypatch.setenv("TASK_BENCHMARK_MIN_PASS", "1")
    monkeypatch.setattr(module, "REPORT_DIR", tmp_path, raising=False)
    monkeypatch.setattr(
        module,
        "_benchmark_set",
        lambda: {
            "name": "golden",
            "path": dataset,
            "report": "task_benchmark_report.json",
            "floor_env": "TASK_BENCHMARK_MIN_PASS",
            "default_floor": 0.4,
        },
    )
    return module, dataset, tmp_path


def _producer_trials(producer, monkeypatch, make_rows):
    module, _, output = producer

    def run_trial(_dataset, trial):
        rows = make_rows(trial)
        path = output / f"task_benchmark_trial_{trial}.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        return rows

    monkeypatch.setattr(module, "_run_trial", run_trial)


def test_producer_rejects_duplicate_rows_hiding_missing_task(producer, monkeypatch):
    _producer_trials(producer, monkeypatch, lambda trial: [outcomes(trial)[0]] * 2)
    with pytest.raises(ValueError, match="missing, duplicate or unknown"):
        producer[0].test_task_set_pass_k()


@pytest.mark.parametrize("count", [-1, True, 1.5, "1"])
def test_producer_rejects_invalid_model_response_counts(producer, monkeypatch, count):
    _producer_trials(
        producer,
        monkeypatch,
        lambda trial: [dict(row, model_responses=count) for row in outcomes(trial)],
    )
    with pytest.raises(ValueError, match="model_responses"):
        producer[0].test_task_set_pass_k()


def test_trial_runner_cannot_reuse_stale_output(producer, monkeypatch):
    module, dataset, output = producer
    stale = output / "task_benchmark_trial_0.jsonl"
    stale.write_text(json.dumps(outcomes()[0]) + "\n")

    def no_output(*args, **kwargs):
        assert not stale.exists(), "a prior trial artifact survived into the new execution"
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", no_output)
    with pytest.raises(FileNotFoundError):
        module._run_trial(dataset, 0)


@pytest.mark.parametrize("responses, mode", [(0, "rule_only"), (2, "model_workflow")])
def test_producer_binds_report_to_dataset_and_raw_trials(producer, monkeypatch, responses, mode):
    module, dataset, output = producer
    _producer_trials(
        producer,
        monkeypatch,
        lambda trial: [dict(row, model_responses=responses) for row in outcomes(trial)],
    )
    module.test_task_set_pass_k()
    report = json.loads((output / "task_benchmark_report.json").read_text())
    assert len(report["source_sha"]) == 40 and report["captured_at"]
    assert type(report["tracked_source_dirty"]) is bool
    assert report["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert report["execution_mode"] == mode
    assert report["model_responses"] == 6 * responses
    assert report["gate_passed"] is True and report["trials"] == 3
    assert report["trial_artifacts"] == [
        benchmark_evidence.trial_artifact(output / f"task_benchmark_trial_{i}.jsonl")
        for i in range(3)
    ]


def test_producer_never_masks_safety_failure_with_aggregate_threshold(producer, monkeypatch):
    monkeypatch.setenv("TASK_BENCHMARK_MIN_PASS", "0.4")
    _producer_trials(producer, monkeypatch, lambda trial: outcomes(trial, reject=False))
    with pytest.raises(AssertionError, match="安全失败=1"):
        producer[0].test_task_set_pass_k()
    report = json.loads((producer[2] / "task_benchmark_report.json").read_text())
    assert report["pass_k"] == 0.5 and report["gate_passed"] is False


@pytest.mark.parametrize("mode", ["observe", "gate"])
def test_producer_rejects_unadmitted_trial_even_at_low_threshold(producer, monkeypatch, mode):
    monkeypatch.setenv("TASK_BENCHMARK_MODE", mode)
    monkeypatch.setenv("TASK_BENCHMARK_MIN_PASS", "0.4")

    def rows(trial):
        result = outcomes(trial, create=False)
        if trial == 1:
            result[0]["runtime_admitted"] = False
        return result

    _producer_trials(producer, monkeypatch, rows)
    with pytest.raises(pytest.fail.Exception, match="未真正开始执行"):
        producer[0].test_task_set_pass_k()
    report = json.loads((producer[2] / "task_benchmark_report.json").read_text())
    assert report["startup_blocked_tasks"] == ["create"]
    assert report["pass_k"] == 0.5 and report["gate_passed"] is False
    assert len(report["trial_artifacts"]) == 3


def test_holdout_defaults_to_observation_without_claiming_acceptance(producer, monkeypatch):
    module, dataset, output = producer
    monkeypatch.delenv("TASK_BENCHMARK_MODE")
    monkeypatch.delenv("TASK_BENCHMARK_HOLDOUT_MIN_PASS", raising=False)
    monkeypatch.setattr(
        module,
        "_benchmark_set",
        lambda: {
            "name": "holdout",
            "path": dataset,
            "report": "task_holdout_report.json",
            "floor_env": "TASK_BENCHMARK_HOLDOUT_MIN_PASS",
            "default_floor": 0.0,
        },
    )
    _producer_trials(
        producer, monkeypatch, lambda trial: outcomes(trial, create=False, reject=False)
    )
    module.test_task_set_pass_k()
    report = json.loads((output / "task_holdout_report.json").read_text())
    assert report["acceptance_mode"] == "observe" and report["min_required"] == 0
    assert report["pass_k"] == 0 and report["gate_passed"] is False


@pytest.mark.parametrize("minimum", ["0", "nan", "inf"])
def test_producer_rejects_invalid_gate_before_execution(producer, monkeypatch, minimum):
    monkeypatch.setenv("TASK_BENCHMARK_MIN_PASS", minimum)
    monkeypatch.setattr(producer[0], "_run_trial", lambda *args: pytest.fail("runner was invoked"))
    with pytest.raises(ValueError):
        producer[0].test_task_set_pass_k()


def test_monitoring_can_keep_one_trial_without_becoming_publishable(producer, monkeypatch):
    monkeypatch.setenv("TASK_BENCHMARK_TRIALS", "1")
    _producer_trials(producer, monkeypatch, outcomes)
    producer[0].test_task_set_pass_k()
    report = json.loads((producer[2] / "task_benchmark_report.json").read_text())
    assert report["trials"] == 1 and report["gate_passed"] is True
    with pytest.raises(ValueError, match="independent trial artifacts"):
        benchmark_evidence.validate_task_artifacts(producer[2], report, producer[1])


def test_source_change_during_trials_is_not_clean_evidence(producer, monkeypatch):
    module, _, output = producer
    identities = iter(
        {"source_sha": sha * 40, "dataset_sha256": "d" * 64, "tracked_source_dirty": False}
        for sha in ("a", "b")
    )
    monkeypatch.setattr(module, "evidence_identity", lambda *args, **kwargs: next(identities))
    _producer_trials(producer, monkeypatch, outcomes)
    module.test_task_set_pass_k()
    report = json.loads((output / "task_benchmark_report.json").read_text())
    assert report["source_sha"] == "a" * 40 and report["tracked_source_dirty"] is True


@pytest.mark.parametrize(
    "failure, admitted, expected",
    [
        ("sqlite3.OperationalError: database is locked", False, "database_lock"),
        ("OpenAI model provider HTTP 401 Unauthorized", False, "model_provider_auth"),
        ("LLM provider HTTP 429 Too Many Requests", False, "model_provider_rate_limit"),
        ("Codex model API HTTP 503", False, "model_provider_service"),
        ("Business API HTTP 401 Unauthorized", True, "runtime_execution_unverified"),
        ("runtime_policy_blocked", False, "runtime_admission"),
    ],
)
def test_failure_causes_never_confuse_model_keys_with_database_or_business(
    failure, admitted, expected
):
    assert classify_trial_failure(
        {"pass": False, "failure": failure, "runtime_admitted": admitted, "exec_pass": None}
    ) == expected


def test_failure_cause_counts_preserve_original_success_threshold():
    rows = outcomes(create=False, reject=False)
    rows[0]["failure"] = "sqlite3.OperationalError: database is locked"
    rows[0]["runtime_admitted"] = False
    rows[1]["failure"] = "OpenAI model provider HTTP 401"
    rows[1]["runtime_admitted"] = False
    measured = summarize_trials(TASKS, [rows])
    assert measured["failure_categories"] == {"database_lock": 1, "model_provider_auth": 1}
    assert measured["pass_k"] == 0 and not passes_gate(measured, 0.4)


@pytest.mark.parametrize(
    "output, admitted, expected",
    [
        (
            {
                "error_code": "runtime_login_required",
                "execution_state": "blocked",
                "failure_stage": "runtime_setup",
            },
            False,
            "runtime_account_auth",
        ),
        ({"error_code": "runtime_login_required"}, False, "runtime_admission"),
        ({"error_code": "runtime_login_required"}, True, "runtime_execution_unverified"),
        (None, False, "runtime_admission"),
    ],
)
def test_runtime_account_auth_requires_structured_setup_receipt(output, admitted, expected):
    row = {
        "pass": False,
        "failure": "runtime_login_required",
        "runtime_admitted": admitted,
        "exec_pass": None,
        "execution": {"final_output": output},
    }
    assert classify_trial_failure(row) == expected
