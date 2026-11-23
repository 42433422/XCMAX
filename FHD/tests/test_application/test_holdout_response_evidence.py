import importlib.util
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({}, 0),
        ({"codex_runtime": {"model_requests": {"x": {"state": "unknown", "usage": {}}}}}, 0),
        ({"codex_runtime": {"model_requests": {"x": {"state": "failed", "usage": {}}}}}, 0),
        ({"codex_runtime": {"model_requests": {"x": {"state": "completed"}}}}, 0),
        (
            {
                "codex_runtime": {
                    "model_requests": {"x": {"state": "completed", "usage": {"total_tokens": 20}}}
                }
            },
            1,
        ),
    ],
)
def test_response_evidence_requires_settled_original_runtime_request(metadata, expected):
    spec = importlib.util.spec_from_file_location(
        "trial_runner", ROOT / "tests/benchmarks/task_success_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._completed_model_requests(metadata) == expected


@pytest.mark.parametrize(
    "workflow_path",
    [
        ROOT / ".github/workflows/intent-benchmark.yml",
        ROOT.parent / ".github/workflows/fhd-intent-benchmark.yml",
    ],
)
@pytest.mark.parametrize("job_name", ["acceptance", "task-holdout"])
def test_workflow_preserves_raw_evidence_and_uses_one_verification_gate(workflow_path, job_name):
    job = yaml.safe_load(workflow_path.read_text())["jobs"][job_name]
    steps = job["steps"]
    holdout = job_name == "task-holdout"
    verifier_id = "holdout_evidence" if holdout else "acceptance_evidence"
    runner = next(s for s in steps if "tests/benchmarks/test_task_success.py" in s.get("run", ""))
    verifier = next(s for s in steps if s.get("id") == verifier_id)
    runner_env = {**job.get("env", {}), **runner.get("env", {})}
    verifier_env = {**job.get("env", {}), **verifier.get("env", {})}
    assert runner_env["TASK_BENCHMARK_TRIALS"] == "3"
    assert runner_env["TASK_BENCHMARK_MODE"] == ("observe" if holdout else "gate")
    assert runner_env["XCAGI_SKIP_INTENT_LLM"] in {"", "0"}
    assert not runner.get("continue-on-error") and not verifier.get("continue-on-error")
    command = next(line for line in verifier["run"].splitlines() if line.startswith("python "))
    expected = ["python", "scripts/dev/verify_task_benchmark_evidence.py", "--set"]
    if holdout:
        assert runner_env["TASK_BENCHMARK_HOLDOUT_MIN_PASS"] == "0"
        expected += ["holdout"]
    else:
        assert (
            runner_env["TASK_BENCHMARK_MIN_PASS"]
            == verifier_env["TASK_BENCHMARK_MIN_PASS"]
            == "0.4"
        )
        expected += ["golden", "--minimum", "$TASK_BENCHMARK_MIN_PASS"]
    assert shlex.split(command) == expected

    commit = next(s for s in steps if "git commit" in s.get("run", ""))
    condition = f"steps.{verifier_id}.outcome == 'success'"
    assert commit["if"] == (
        f"steps.creds.outputs.available == 'true' && {condition}" if holdout else condition
    )
    assert steps.index(runner) < steps.index(verifier) < steps.index(commit)
    assert not commit.get("continue-on-error")
    report = "task_holdout_report.json" if holdout else "task_benchmark_report.json"
    marker = "task_holdout_run_mode.json" if holdout else "benchmark_run_mode.json"
    assert report in commit["run"] and marker in commit["run"]
    assert 'cp "test_reports/$f" "metrics/$f"' in commit["run"]
    artifact = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    paths = artifact["with"]["path"].splitlines()
    assert {
        f"FHD/test_reports/{report}",
        f"FHD/test_reports/{marker}",
        "FHD/test_reports/task_benchmark_trial_*.jsonl",
    } <= set(paths)
    assert artifact["with"]["if-no-files-found"] == "error"
