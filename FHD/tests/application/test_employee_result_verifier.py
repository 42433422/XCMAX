from __future__ import annotations

import pytest

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
        {"status": "completed", "outcome": "unknown"},
        {"execution_state": "completed", "status": "unknown"},
        {"outcome": " UNKNOWN "},
        {"requires_reconciliation": True},
        {"status": "accepted"},
        {"reconciliation_required": True},
    ):
        result = {
            "success": True,
            "result": {"summary": "done", "outputs": [{"ok": True, "output": child}]},
        }
        assert verify_employee_run_result("employee", result)[0] is False


def test_unknown_identity_variants_are_not_verified_and_require_reconciliation():
    from app.application.employee_runtime.result_verifier import (
        execution_result_requires_reconciliation,
    )

    for marker in ({"outcome": "unknown"}, {"requires_reconciliation": True}):
        child = {"success": True, "status": "completed", "summary": "done", **marker}
        for result in (child, {"success": True, "result": {"outputs": [{"output": child}]}}):
            assert verify_employee_run_result("employee", result)[0] is False
            assert execution_result_requires_reconciliation(result) is True


@pytest.mark.parametrize(
    "child,approval,reconcile",
    [
        ({"state": "waiting_approval"}, True, False),
        ({"status": "awaiting_approval"}, True, False),
        ({"execution_status": "waiting_approval"}, True, False),
        ({"exit_status": "waiting_approval"}, True, False),
        ({"requires_token": True}, True, False),
        ({"pending_approval": True}, True, False),
        ({"execution_outcome": "unknown"}, False, True),
        ({"state": "processing"}, False, True),
        ({"status": "queued"}, False, True),
        ({"status": "waiting_user"}, False, False),
        ({"status": "paused"}, False, False),
        ({"status": "rejected"}, False, False),
        ({"status": "approval_required"}, True, False),
        ({"status": "authorization_required"}, True, False),
        ({"status": "outcome_unknown"}, False, True),
        ({"status": "in_progress"}, False, True),
        ({"status": "inflight"}, False, True),
        ({"status": "partial"}, False, True),
        ({"status": "partial_success"}, False, True),
        ({"status": "blocked"}, False, True),
        ({"status": "error"}, False, False),
        ({"status": "failure"}, False, False),
    ],
)
@pytest.mark.parametrize("key", ["result", "output", "data", "payload"])
def test_success_envelopes_preserve_waits_and_unfinished_execution(child, approval, reconcile, key):
    from app.domain.task_lifecycle.results import (
        execution_result_awaits_approval,
        execution_result_requires_reconciliation,
    )

    result = {
        "success": True,
        "summary": "delivered",
        "outputs": [{key: {"success": True, **child}}],
    }
    assert verify_employee_run_result("employee", result)[0] is False
    assert execution_result_awaits_approval(result) is approval
    assert execution_result_requires_reconciliation(result) is reconcile


def test_business_row_status_does_not_become_execution_status():
    result = {"success": True, "result": {"items": [{"status": "pending", "name": "order"}]}}
    assert verify_employee_run_result("employee", result) == (True, "ok")


@pytest.mark.parametrize("key", ["outputs", "node_outputs"])
def test_mapping_of_execution_outputs_preserves_unknown_child(key):
    from app.domain.task_lifecycle.results import execution_result_requires_reconciliation

    result = {
        "success": True,
        "summary": "done",
        "final_output": {key: {"first": {"success": True, "outcome": "outcome_unknown"}}},
    }
    assert verify_employee_run_result("employee", result)[0] is False
    assert execution_result_requires_reconciliation(result) is True


@pytest.mark.parametrize(
    "body,reason",
    [
        ({"requires_token": True}, "authorization"),
        ({"state": "waiting_authorization"}, "authorization"),
        ({"status": "waiting_approval"}, "approval"),
        ({"status": "waiting_user"}, "input"),
        ({"state": "waiting_input"}, "input"),
        ({"needs_user_input": True}, "input"),
        ({"state": "paused"}, "paused"),
    ],
)
def test_wait_reason_preserves_authorization_approval_input_and_pause(body, reason):
    from app.domain.task_lifecycle.results import execution_result_wait_reason

    result = {"success": True, "data": {"payload": body}}
    assert execution_result_wait_reason(result) == reason
    assert verify_employee_run_result("employee", result, require_non_empty=False)[0] is False


def test_result_envelopes_are_cycle_safe_and_bound_unknown_depth():
    from app.domain.task_lifecycle.results import (
        execution_result_envelopes,
        execution_result_requires_reconciliation,
    )

    result = {"success": True}
    result["output"] = result
    assert list(execution_result_envelopes(result)) == [result]
    deep = {"success": True}
    for _ in range(300):
        deep = {"result": deep}
    assert execution_result_requires_reconciliation(deep) is True
    assert verify_employee_run_result("employee", deep, require_non_empty=False)[0] is False
