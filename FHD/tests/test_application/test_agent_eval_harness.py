from __future__ import annotations

import json

from evals import run_agent_eval as eval_module
from evals.run_agent_eval import DEFAULT_TASKS_PATH, run_eval


def test_agent_eval_harness_baseline_passes() -> None:
    from app.application.agent_orchestrator import orchestrator

    original_executor = orchestrator.AgentToolExecutor
    result = run_eval(DEFAULT_TASKS_PATH)

    assert orchestrator.AgentToolExecutor is original_executor
    assert result["execution_mode"] == "fixture_local"
    assert result["failed"] == 0, result
    assert result["passed"] == 120
    assert result["score"] == 1.0


def test_agent_eval_cli_prints_only_public_summary(monkeypatch, capsys) -> None:
    result = {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "score": 1.0,
        "results": [{"api_key": "must-not-be-printed", "passed": True}],
    }
    monkeypatch.setattr(eval_module, "run_eval", lambda _path: result)

    assert eval_module.main([]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "suite": "agent_platform_minimum",
        "execution_mode": "fixture_local",
        "tasks_path": str(DEFAULT_TASKS_PATH),
        "total": 1,
        "passed": 1,
        "failed": 0,
        "score": 1.0,
    }
    assert "must-not-be-printed" not in output
