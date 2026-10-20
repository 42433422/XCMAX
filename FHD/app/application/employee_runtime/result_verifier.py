"""AI 员工执行结果验收。"""

from __future__ import annotations

from typing import Any


def verify_employee_run_result(
    employee_id: str,
    output: dict[str, Any] | None,
    *,
    require_non_empty: bool = True,
) -> tuple[bool, str]:
    data = output if isinstance(output, dict) else {}
    error = execution_result_error(data)
    if error:
        return False, error
    nested = data.get("result")
    payload = nested if isinstance(nested, dict) else data
    outputs = payload.get("outputs")
    if require_non_empty:
        if not payload and not payload.get("items") and not payload.get("summary"):
            return False, "员工输出为空"
    summary = str(payload.get("summary") or "").strip()
    if (
        require_non_empty
        and not summary
        and not payload.get("items")
        and not payload.get("sheets")
        and not outputs
    ):
        return False, "缺少 summary/items/sheets"
    return True, "ok"


def execution_result_error(data: dict[str, Any]) -> str:
    """Inspect canonical result envelopes, never infer success from HTTP delivery."""
    if data.get("error"):
        return str(data["error"])
    state = str(data.get("execution_state") or data.get("status") or "")
    if (
        state in {"unknown", "pending", "accepted", "running", "failed", "blocked", "cancelled"}
        or data.get("reconciliation_required")
        or data.get("pending_approval")
    ):
        return str(data.get("message") or "员工执行尚未完成")
    for key in ("result", "output"):
        nested = data.get(key)
        if isinstance(nested, dict):
            error = execution_result_error(nested)
            if error:
                return error
    outputs = data.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if not isinstance(item, dict):
                return "员工处理器结果无效"
            error = execution_result_error(item)
            if error:
                return error
    if data.get("success") is False or data.get("ok") is False:
        return str(data.get("message") or data.get("summary") or "员工执行失败")
    return ""


def execution_result_requires_reconciliation(data: dict[str, Any]) -> bool:
    """Preserve unknown identity through the same envelopes used by verification."""
    state = str(data.get("execution_state") or data.get("status") or "")
    if state in {"unknown", "accepted", "pending", "running"} or data.get(
        "reconciliation_required"
    ):
        return True
    children = [data.get("result"), data.get("output")]
    outputs = data.get("outputs")
    if isinstance(outputs, list):
        children.extend(outputs)
    return any(
        execution_result_requires_reconciliation(item)
        for item in children
        if isinstance(item, dict)
    )


def execution_result_awaits_approval(data: dict[str, Any]) -> bool:
    if data.get("pending_approval"):
        return True
    children = [data.get("result"), data.get("output")]
    outputs = data.get("outputs")
    if isinstance(outputs, list):
        children.extend(outputs)
    return any(
        execution_result_awaits_approval(item) for item in children if isinstance(item, dict)
    )
