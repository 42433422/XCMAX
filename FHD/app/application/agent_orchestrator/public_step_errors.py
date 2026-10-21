"""Step failures that may be shown verbatim to the end user.

Tool errors stay behind the generic "详细信息已记录" message by default; only
error codes whose message is produced by our own code for the user are listed.
"""

from __future__ import annotations

from typing import Any

_USER_FACING_CODES = frozenset({"unresolved_param_reference"})
_INVENTORY_GUIDANCE = {
    "inventory_insufficient_stock": "库存不足或无库存记录，请前往「库存管理 → 入库」为该产品办理入库后重试。",
    "inventory_warehouse_missing": "当前企业没有可用仓库，请先在「库存管理」点击「初始化默认仓库」，再为产品入库后重试。",
}


def public_step_error(step: Any, *, allow_reference_message: bool = True) -> str:
    output = getattr(step, "output", None)
    output = output if isinstance(output, dict) else {}
    code = str(output.get("error_code") or "")
    if getattr(step, "tool_id", "") == "inventory" and getattr(step, "action", "") == "stock_out":
        if guidance := _INVENTORY_GUIDANCE.get(code):
            return guidance
    if allow_reference_message and code in _USER_FACING_CODES:
        return str(output.get("message") or "")[:500]
    return ""


def public_run_error(run: Any) -> str:
    for step in getattr(run, "steps", []) or []:
        if getattr(step, "status", "") == "failed" and (text := public_step_error(step)):
            return text
    return ""
