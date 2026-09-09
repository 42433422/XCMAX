"""Explicit non-execution outcomes, recognized before model or tool planning."""

from __future__ import annotations

import re

from app.domain.neuro.action_negation import has_denied_action
from app.domain.neuro.greeting import is_standalone_greeting

from .types import PlanGraph

_PROHIBITION = re.compile(
    r"^(?:请)?(?:不要|别|不用|无需)(?:再)?"
    r"(?:新建|新增|创建|添加|删除|修改|更新|查询|查|导出|导入)"
    r"(?:任何|所有|全部)?(?:客户|产品|商品|订单|库存|数据|文件)"
    r"[。！!\s]*$"
)


_RAW_SQL = re.compile(
    r"\b(?:delete\s+from|insert\s+into|update\s+[\w.]+\s+set|"
    r"(?:drop|alter|truncate)\s+table|select\s+.+?\s+from)\b",
    re.IGNORECASE | re.DOTALL,
)


def _requests_raw_sql(text: str) -> bool:
    match = _RAW_SQL.search(text)
    if match is None:
        return False
    prefix = text[: match.start()].strip(" `\n\t")
    return not prefix or bool(re.search(r"执行|运行|\b(?:execute|run)\b", prefix, re.IGNORECASE))


def no_operation_plan(plan_id: str, message: str) -> PlanGraph | None:
    text = str(message or "").strip()
    if _requests_raw_sql(text):
        reason = "unsupported_raw_sql"
        response = (
            "当前业务工作流不执行原始 SQL。请说明具体业务操作和目标记录，本次未执行数据库操作。"
        )
    elif is_standalone_greeting(text):
        reason, response = "greeting", "你好，请告诉我需要办理什么业务。"
    elif _PROHIBITION.fullmatch(text):
        reason, response = "explicit_prohibition", "收到，本次不执行业务操作。"
    elif has_denied_action(text):
        reason = "negated_action"
        response = "本次未执行业务操作。请说明需要保留的操作，或确认取消本次任务。"
    else:
        return None
    return PlanGraph(
        plan_id=plan_id,
        intent="no_operation",
        nodes=[],
        risk_level="low",
        metadata={"planner": "deterministic", "reason": reason, "response": response},
    )
