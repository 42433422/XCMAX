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
    if data.get("success") is False:
        return False, str(
            data.get("error")
            or data.get("message")
            or data.get("summary")
            or "员工返回 success=false"
        )
    if data.get("ok") is False:
        return False, str(data.get("error") or data.get("summary") or "员工返回 ok=false")

    # ``EmployeeAgent.run`` wraps the handler payload under ``result``.  The
    # admin execution route must validate that canonical envelope instead of
    # incorrectly rejecting a successful direct_python run for lacking
    # top-level summary/items/sheets.
    nested = data.get("result")
    payload = nested if isinstance(nested, dict) else data
    if payload.get("ok") is False:
        return False, str(payload.get("error") or payload.get("summary") or "员工结果返回 ok=false")
    outputs = payload.get("outputs")
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict) and item.get("ok") is False:
                child = item.get("output") if isinstance(item.get("output"), dict) else {}
                return False, str(
                    item.get("error")
                    or child.get("error")
                    or child.get("summary")
                    or "员工处理器执行失败"
                )
    if require_non_empty:
        if not payload and not payload.get("items") and not payload.get("summary"):
            return False, "员工输出为空"
    summary = str(payload.get("summary") or "").strip()
    data_receipt = payload.get("data")
    has_data_receipt = (
        isinstance(data_receipt, dict)
        and bool(data_receipt)
        or isinstance(data_receipt, list)
        and bool(data_receipt)
    )
    if (
        require_non_empty
        and not summary
        and not payload.get("items")
        and not payload.get("sheets")
        and not outputs
        and not has_data_receipt
    ):
        return False, "缺少 summary/items/sheets/outputs/data"
    return True, "ok"
