from __future__ import annotations

from pathlib import Path

from app.application.employee_runtime.executor import (
    _actions_fhd,
    _handlers_execution_ok,
)
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


def test_rejects_error_only_handler_output() -> None:
    ok, reason = verify_employee_run_result(
        "emp",
        {
            "success": True,
            "result": {
                "summary": "executed 1 handlers",
                "outputs": [{"handler": "unknown_handler", "error": "unsupported handler"}],
            },
        },
    )
    assert ok is False
    assert reason == "unsupported handler"


def test_unknown_handler_is_hard_failure_end_to_end() -> None:
    result = _actions_fhd(
        {"actions": {"handlers": ["unknown_handler"]}},
        {},
        "task",
        "emp-1",
        Path("/tmp"),
        None,
    )
    assert result["outputs"][0]["ok"] is False
    assert _handlers_execution_ok(result) is False
    ok, reason = verify_employee_run_result("emp-1", {"success": False, "result": result})
    assert ok is False
    assert reason
