"""AI 员工执行结果验收。"""

from __future__ import annotations

from typing import Any

from app.domain.task_lifecycle.results import (
    execution_result_awaits_approval as execution_result_awaits_approval,
)
from app.domain.task_lifecycle.results import (
    execution_result_error,
)
from app.domain.task_lifecycle.results import (
    execution_result_requires_reconciliation as execution_result_requires_reconciliation,
)


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
