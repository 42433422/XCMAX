"""Strict terminal receipts for strategy execution, without changing employee callers.

The employee phase-04 wrapper exposes control evidence under result.outputs,
result.verification and result.path_guard. Business output is opaque here: its
domain fields must not masquerade as execution state or a delivery receipt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ExecutionReceipt:
    status: Literal["completed", "failed", "pending", "unknown"]
    reason: str


def _pending_control(value: dict[str, Any]) -> bool:
    status = value.get("status")
    status = status.strip().lower() if isinstance(status, str) else ""
    return (
        status in {"pending", "queued", "running", "in_progress"}
        or status.startswith(("pending_", "waiting_"))
        or value.get("status_code") == 202
        or value.get("status") == 202
        or any(value.get(key) is True for key in ("queued", "requires_reconciliation"))
        or value.get("completed") is False
        or (
            value.get("accepted") is True
            and value.get("completed") is not True
            and status != "completed"
        )
    )


def _control(value: dict[str, Any], source: str) -> ExecutionReceipt | None:
    if any(
        value.get(key)
        for key in ("error", "cognition_error", "handler_failed", "blocked_by_risk_gate")
    ):
        return ExecutionReceipt("failed", f"{source}_error")
    for key in ("ok", "success"):
        if value.get(key) is False:
            return ExecutionReceipt("failed", f"{source}_{key}_false")
        if key in value and type(value[key]) is not bool:
            return ExecutionReceipt("unknown", f"{source}_{key}_unverified")
    status = value.get("status")
    for code in (value.get("status_code"), status if type(status) is int else None):
        if code is not None:
            if type(code) is not int:
                return ExecutionReceipt("unknown", f"{source}_http_status_invalid")
            if code == 202:
                return ExecutionReceipt("pending", "downstream_execution_receipt_pending")
            if not 200 <= code < 300:
                return ExecutionReceipt("failed", f"{source}_http_status_{code}")
    if isinstance(status, str):
        status = status.strip().lower()
        if status in {
            "failed",
            "failure",
            "error",
            "blocked",
            "rejected",
            "cancelled",
            "canceled",
            "timeout",
            "timed_out",
        }:
            return ExecutionReceipt("failed", f"{source}_status_{status}")
        if status in {"pending", "queued", "running", "in_progress"} or status.startswith(
            ("pending_", "waiting_")
        ):
            return ExecutionReceipt("pending", "downstream_execution_receipt_pending")
        if status not in {
            "",
            "ok",
            "success",
            "succeeded",
            "completed",
            "complete",
            "passed",
            "done",
            "sent",
        }:
            return ExecutionReceipt("unknown", f"{source}_status_unverified")
    elif status is not None and type(status) is not int:
        return ExecutionReceipt("unknown", f"{source}_status_invalid")
    if (
        any(value.get(key) is True for key in ("queued", "requires_reconciliation"))
        or value.get("completed") is False
    ):
        return ExecutionReceipt("pending", "downstream_execution_receipt_pending")
    if (
        value.get("accepted") is True
        and value.get("completed") is not True
        and status != "completed"
    ):
        return ExecutionReceipt("pending", "downstream_execution_receipt_pending")
    return None


def _verification(value: Any) -> ExecutionReceipt | None:
    if not isinstance(value, dict):
        return ExecutionReceipt("unknown", "execution_verification_missing")
    control = _control(value, "verification")
    if control is not None:
        return control
    if value.get("passed") is False:
        return ExecutionReceipt("failed", "execution_verification_failed")
    checks = value.get("checks")
    if (
        value.get("passed") is not True
        or not isinstance(checks, list)
        or not checks
        or any(
            not isinstance(check, dict)
            or ("skipped" in check and type(check["skipped"]) is not bool)
            for check in checks
        )
        or any(
            type(value.get(key)) is not int for key in ("ok_count", "total_count", "failed_count")
        )
    ):
        return ExecutionReceipt("unknown", "execution_verification_unverified")
    active = [check for check in checks if check.get("skipped") is not True]
    if not active or any(type(check.get("ok")) is not bool for check in active):
        return ExecutionReceipt("unknown", "execution_verification_checks_unverified")
    passed = sum(check["ok"] is True for check in active)
    failed = len(active) - passed
    if (value["ok_count"], value["total_count"], value["failed_count"]) != (
        passed,
        len(active),
        failed,
    ):
        return ExecutionReceipt("unknown", "execution_verification_counts_inconsistent")
    if failed:
        return ExecutionReceipt("failed", "execution_verification_failed")
    return None


def _path_guard(value: Any) -> ExecutionReceipt | None:
    if not isinstance(value, dict):
        return ExecutionReceipt("unknown", "execution_path_guard_missing")
    if value.get("ok") is False or value.get("violations"):
        return ExecutionReceipt("failed", "execution_path_guard_failed")
    if (
        value.get("ok") is not True
        or value.get("checked") is not True
        or value.get("violations") != []
    ):
        return ExecutionReceipt("unknown", "execution_path_guard_unverified")
    return _control(value, "path_guard")


def evaluate_execution_receipt(result: Any) -> ExecutionReceipt:
    """Accept only the native verified wrapper or a trusted worker's explicit terminal marker."""
    if not isinstance(result, dict) or not result:
        return ExecutionReceipt("unknown", "execution_receipt_missing")
    inner = result.get("result")
    payload: dict[str, Any] = result
    native = False
    if isinstance(inner, dict) and any(
        key in inner for key in ("outputs", "verification", "path_guard")
    ):
        payload, native = inner, True
    native = native or any(key in result for key in ("outputs", "verification", "path_guard"))
    controls: list[dict[str, Any]] = [result] if payload is result else [result, payload]
    issues = [
        issue
        for index, value in enumerate(controls)
        if (issue := _control(value, f"execution_{index}")) is not None
    ]
    outputs = payload.get("outputs")
    if isinstance(outputs, list):
        for index, output in enumerate(outputs):
            if (
                not isinstance(output, dict)
                or not isinstance(output.get("handler"), str)
                or not output["handler"].strip()
            ):
                issues.append(ExecutionReceipt("unknown", "execution_handler_receipt_invalid"))
            elif (issue := _control(output, f"handler_{index}")) is not None:
                issues.append(issue)
            elif not (
                output.get("ok") is True
                or output.get("success") is True
                or output.get("completed") is True
                or output.get("status")
                in {"ok", "success", "succeeded", "completed", "complete", "passed", "done", "sent"}
                or type(output.get("status_code")) is int
                or any(output.get(key) for key in ("output", "response", "answer", "summary"))
            ):
                issues.append(ExecutionReceipt("unknown", "execution_handler_outcome_missing"))
    pending = next((issue for issue in issues if issue.status == "pending"), None)
    if pending is None and any(
        _pending_control(value)
        for value in [*controls, *(outputs if isinstance(outputs, list) else [])]
        if isinstance(value, dict)
    ):
        pending = ExecutionReceipt("pending", "downstream_execution_receipt_pending")
    failed = next((issue for issue in issues if issue.status == "failed"), None)
    if pending and failed:
        return ExecutionReceipt("unknown", "execution_pending_with_failed_handler")
    if failed is not None:
        return failed
    if pending is not None:
        return pending
    if issues:
        return issues[0]
    if native:
        if not isinstance(outputs, list) or not outputs:
            return ExecutionReceipt("unknown", "execution_handlers_missing")
        for control in controls:
            if control is payload:
                continue
            for key, validate in (("verification", _verification), ("path_guard", _path_guard)):
                if key in control and (issue := validate(control[key])) is not None:
                    return issue
        for issue in (
            _verification(payload.get("verification")),
            _path_guard(payload.get("path_guard")),
        ):
            if issue is not None:
                return issue
        return ExecutionReceipt("completed", "employee_execution_verified")
    if result.get("ok") is True and (
        result.get("completed") is True or result.get("status") == "completed"
    ):
        return ExecutionReceipt("completed", "trusted_worker_completed")
    return ExecutionReceipt("unknown", "execution_terminal_receipt_unverified")
