from __future__ import annotations

from evals.run_agent_eval import DEFAULT_TASKS_PATH, run_eval


def test_agent_eval_harness_baseline_passes() -> None:
    result = run_eval(DEFAULT_TASKS_PATH)

    assert result["failed"] == 0, result
    assert result["passed"] == 120
    assert result["score"] == 1.0
