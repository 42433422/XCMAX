import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from scripts.dev.verify_task_holdout_evidence import write_holdout_evidence

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "response,expected",
    [
        (None, False),
        ({"error": "unauthorized"}, False),
        ({"choices": []}, False),
        ({"choices": [{"message": {"content": ""}}]}, False),
        ({"choices": [{"message": {"content": "invalid plan, genuine response"}}]}, True),
    ],
)
def test_response_evidence_requires_provider_content(response, expected):
    spec = importlib.util.spec_from_file_location(
        "trial_runner", ROOT / "tests/benchmarks/task_success_runner.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._model_response_received(response) is expected


@pytest.mark.parametrize("responses,status", [(0, "UNVERIFIED"), (1, "VERIFIED")])
def test_failed_trials_do_not_certify_an_unresponsive_model(
    tmp_path, monkeypatch, responses, status
):
    workflow = yaml.safe_load((ROOT / ".github/workflows/intent-benchmark.yml").read_text())
    step = next(
        s
        for job in workflow["jobs"].values()
        for s in job["steps"]
        if s.get("name", "").startswith("Verify holdout evidence")
    )
    assert "python scripts/dev/verify_task_holdout_evidence.py" in step["run"]
    monkeypatch.chdir(tmp_path)
    Path("test_reports").mkdir()
    Path("tests/benchmarks").mkdir(parents=True)
    Path("test_reports/task_holdout_report.json").write_text(
        json.dumps({"total_tasks": 1, "pass_k": 0, "model_responses": responses})
    )
    Path("tests/benchmarks/task_holdout_set.json").write_text(json.dumps({"tasks": [{}]}))
    write_holdout_evidence()
    marker = json.loads(Path("test_reports/task_holdout_run_mode.json").read_text())
    assert marker["status"] == status
    assert marker["llm_verified"] is bool(responses)


def test_missing_or_mismatched_report_is_not_certified(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError):
        write_holdout_evidence()
    Path("test_reports").mkdir()
    Path("tests/benchmarks").mkdir(parents=True)
    Path("test_reports/task_holdout_report.json").write_text(
        json.dumps({"total_tasks": 2, "model_responses": 1})
    )
    Path("tests/benchmarks/task_holdout_set.json").write_text(json.dumps({"tasks": [{}]}))
    with pytest.raises(AssertionError):
        write_holdout_evidence()
    assert not Path("test_reports/task_holdout_run_mode.json").exists()
