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
        {"outcome_unknown": True},
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
        ({"outcome_unknown": True}, False, True),
        ({"execution_accepted": True}, False, True),
        ({"agent_status": "running"}, False, True),
        ({"run_status": "queued"}, False, True),
        ({"status": "in_progress"}, False, True),
        ({"status": "inflight"}, False, True),
        ({"status": "partial"}, False, True),
        ({"status": "partial_success"}, False, True),
        ({"execution_status": "timeout"}, False, True),
        ({"execution_status": "timed_out"}, False, True),
        ({"status": "blocked"}, False, True),
        ({"status": "error"}, False, False),
        ({"status": "failure"}, False, False),
    ],
)
@pytest.mark.parametrize("key", ["result", "output", "data", "payload", "business_result"])
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


@pytest.mark.parametrize("status", ["cancelled", "pending", "failed"])
@pytest.mark.parametrize("traced", [False, True])
def test_cancel_order_contract_preserves_business_status_and_original_receipt(status, traced):
    from copy import deepcopy

    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.agent_orchestrator.trace_payloads import _attach_run_id
    from app.domain.task_lifecycle.results import (
        execution_result_requires_reconciliation,
        normalize_execution_result,
    )

    spec = get_tool_action_spec("purchase", "cancel_order")
    result = deepcopy(spec.contract_samples[0]["output"])
    result["data"]["status"] = status
    if traced:
        result = _attach_run_id(result, "order-cancellation-trace")
    before = deepcopy(result)
    assert normalize_execution_result(result) == before
    assert result == before and result["success"] is True
    assert execution_result_requires_reconciliation(result) is False
    assert verify_employee_run_result("employee", result, require_non_empty=False) == (True, "ok")


@pytest.mark.parametrize("identity", ["task_id", "execution_id", "run_id", "agent_run_id"])
def test_independent_child_execution_keeps_pending_state(identity):
    from app.domain.task_lifecycle.results import normalize_execution_result

    result = {
        "success": True,
        "run_id": "parent-run",
        "data": {identity: "child-run", "status": "pending"},
    }
    normalized = normalize_execution_result(result)
    assert normalized["success"] is False and normalized["outcome"] == "unknown"
    assert normalized["retryable"] is False and normalized["data"] == result["data"]


def test_employee_execution_contract_does_not_claim_accepted_run_completed():
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.domain.task_lifecycle.results import normalize_execution_result

    result = get_tool_action_spec("employee", "execute").contract_samples[0]["output"]
    normalized = normalize_execution_result(result)
    assert normalized["success"] is False and normalized["outcome"] == "unknown"
    assert normalized["retryable"] is False and normalized["employee_id"] == result["employee_id"]


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


@pytest.mark.parametrize(
    "marker",
    [
        {"verification": {"verified": False}},
        {"verification": {"status": "failed", "verified": True}},
        {"verification": {"status": "pending"}},
        {"verification": {"status": "inconclusive"}},
        {"verification": {"status": "unverified"}},
        {"verification": {"verdict": "fail"}},
        {"verification": {"passed": False}},
        {"verification": {"accepted": False}},
        {"verification": False},
        {"artifact_postcondition": {"verified": False}},
        {"business_result": {"status": "partial", "success": True}},
        {"business_result": {"status": "completed", "success": False}},
    ],
)
def test_success_wrapper_preserves_explicit_verification_and_business_failures(marker):
    from app.domain.task_lifecycle.results import execution_result_error

    result = {"success": True, "result": {"summary": "done", "outputs": [{"output": marker}]}}
    assert execution_result_error(result)
    assert verify_employee_run_result("employee", result)[0] is False


def test_artifact_failure_reason_survives_success_wrapper():
    result = {
        "success": True,
        "summary": "done",
        "artifact_postcondition": {"verified": False, "reason": "输出文件不存在或为空"},
    }
    assert verify_employee_run_result("employee", result) == (False, "输出文件不存在或为空")


@pytest.mark.parametrize("status", ["verified", "not_required"])
def test_compatibility_check_keeps_verification_exemption_distinct_from_failure(status):
    result = {
        "success": True,
        "summary": "read completed",
        "verification": {"status": status, "verified": status == "verified"},
        "items": [
            {"employee_id": "other", "status": "pending", "verification": {"verified": False}}
        ],
    }
    assert verify_employee_run_result("employee", result) == (True, "ok")
    assert result["verification"]["status"] == status


@pytest.mark.parametrize("key", [None, "result"])
def test_declared_employee_identity_must_match_requested_employee(key):
    payload = {"employee_id": "other", "summary": "done"}
    result = {"success": True, key: payload} if key else {"success": True, **payload}
    assert verify_employee_run_result("employee", result) == (False, "员工输出身份与执行员工不一致")


def test_matching_employee_identity_preserves_legacy_and_delegated_result_compatibility():
    result = {"success": True, "employee_id": "employee", "result": {"summary": "done"}}
    result["result"]["outputs"] = [{"employee_id": "delegate", "success": True}]
    assert verify_employee_run_result("employee", result) == (True, "ok")
