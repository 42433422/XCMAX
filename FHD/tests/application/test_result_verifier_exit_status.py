"""exit_status / max_iterations 验收。"""

from __future__ import annotations

from app.application.employee_runtime.result_verifier import verify_employee_run_result


def test_verifier_fails_on_max_iterations_exit_status() -> None:
    ok, reason = verify_employee_run_result(
        "emp1",
        {
            "result": {
                "ok": False,
                "exit_status": "max_iterations",
                "max_iterations_reached": True,
                "error": "exhausted",
            }
        },
        require_non_empty=False,
    )
    assert ok is False
    assert ok is False and reason


def test_verifier_fails_on_max_rounds_exit_status() -> None:
    ok, reason = verify_employee_run_result(
        "emp1",
        {"result": {"ok": False, "exit_status": "max_rounds", "error": "rounds"}},
        require_non_empty=False,
    )
    assert ok is False
    assert reason


def test_verifier_allows_completed() -> None:
    ok, _ = verify_employee_run_result(
        "emp1",
        {"result": {"ok": True, "exit_status": "completed", "summary": "done"}},
        require_non_empty=False,
    )
    assert ok is True
