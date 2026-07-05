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
    if data.get("ok") is False:
        return False, str(data.get("error") or data.get("summary") or "员工返回 ok=false")
    if require_non_empty:
        if not data and not data.get("items") and not data.get("summary"):
            return False, "员工输出为空"
    summary = str(data.get("summary") or "").strip()
    if require_non_empty and not summary and not data.get("items") and not data.get("sheets"):
        return False, "缺少 summary/items/sheets"
    return True, "ok"
