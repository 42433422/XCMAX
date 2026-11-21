"""AI 员工执行结果验收。"""

from __future__ import annotations

from typing import Any

from app.domain.task_lifecycle.results import (
    execution_result_awaits_approval as execution_result_awaits_approval,
)
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_error,
    execution_result_pending_state,
)
from app.domain.task_lifecycle.results import (
    execution_result_requires_reconciliation as execution_result_requires_reconciliation,
)


def pending_employee_result(data: dict[str, Any]) -> dict[str, Any]:
    """Preserve the original execution identity when a child has not finished."""
    state = execution_result_pending_state(data)
    if not state:
        return {}
    result: dict[str, Any] = {"execution_state": state, "retryable": False}
    if state == "unknown":
        result["reconciliation_required"] = True
    elif state == "waiting_approval":
        result["pending_approval"] = True
    elif state == "waiting_input":
        result["needs_user_input"] = True
    elif state == "waiting_auth":
        result["requires_token"] = True
    for receipt in execution_result_envelopes(data):
        run_id = receipt.get("agent_run_id") or receipt.get("run_id")
        if run_id and "agent_run_id" not in result:
            result.update(agent_run_id=str(run_id), run_id=str(run_id))
        for key in ("task_id", "turn_id", "plan_id", "approval_request_id", "approval_request_ids"):
            if receipt.get(key) and key not in result:
                result[key] = receipt[key]
    return result


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
