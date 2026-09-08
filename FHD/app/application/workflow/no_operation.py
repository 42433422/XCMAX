"""Explicit non-execution outcomes, recognized before model or tool planning."""

from __future__ import annotations

import re

from app.domain.neuro.greeting import is_standalone_greeting

from .types import PlanGraph

_PROHIBITION = re.compile(
    r"^(?:请)?(?:不要|别|不用|无需)(?:再)?"
    r"(?:新建|新增|创建|添加|删除|修改|更新|查询|查|导出|导入)"
    r"(?:任何|所有|全部)?(?:客户|产品|商品|订单|库存|数据|文件)"
    r"[。！!\s]*$"
)


def no_operation_plan(plan_id: str, message: str) -> PlanGraph | None:
    text = str(message or "").strip()
    if is_standalone_greeting(text):
        reason, response = "greeting", "你好，请告诉我需要办理什么业务。"
    elif _PROHIBITION.fullmatch(text):
        reason, response = "explicit_prohibition", "收到，本次不执行业务操作。"
    else:
        return None
    return PlanGraph(
        plan_id=plan_id,
        intent="no_operation",
        nodes=[],
        risk_level="low",
        metadata={"planner": "deterministic", "reason": reason, "response": response},
    )
