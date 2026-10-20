from __future__ import annotations

from app.application.employee_runtime.result_verifier import verify_employee_run_result


def test_accepts_employee_agent_result_envelope() -> None:
    ok, reason = verify_employee_run_result(
        "csv-full-read-employee",
        {
            "success": True,
            "result": {
                "summary": "executed 1 handlers",
                "outputs": [{"handler": "direct_python", "ok": True, "output": {"ok": True}}],
            },
        },
    )
    assert (ok, reason) == (True, "ok")


def test_rejects_top_level_employee_failure() -> None:
    ok, reason = verify_employee_run_result(
        "csv-full-read-employee", {"success": False, "error": "员工包未安装"}
    )
    assert ok is False
    assert reason == "员工包未安装"


def test_rejects_nested_handler_failure() -> None:
    ok, reason = verify_employee_run_result(
        "csv-full-read-employee",
        {
            "success": True,
            "result": {
                "outputs": [
                    {
                        "handler": "direct_python",
                        "ok": False,
                        "output": {"ok": False, "error": "文件不存在"},
                    }
                ]
            },
        },
    )
    assert ok is False
    assert reason == "文件不存在"


def test_error_only_unknown_handler_is_not_success():
    from pathlib import Path

    from app.application.employee_runtime.executor import _actions_fhd, _handlers_execution_ok

    result = _actions_fhd(
        {"actions": {"handlers": ["unknown_handler"]}}, {}, "task", "employee", Path("/tmp"), None
    )
    assert result["outputs"][0]["ok"] is False
    assert _handlers_execution_ok(result) is False
    assert verify_employee_run_result("employee", {"success": True, "result": result})[0] is False


def test_success_wrapper_cannot_hide_nested_error_or_unfinished_action():
    for child in (
        {"error": "private failure"},
        {"success": False},
        {"status": "unknown"},
        {"status": "accepted"},
        {"reconciliation_required": True},
    ):
        result = {
            "success": True,
            "result": {"summary": "done", "outputs": [{"ok": True, "output": child}]},
        }
        assert verify_employee_run_result("employee", result)[0] is False
