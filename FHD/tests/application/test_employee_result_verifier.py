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
