"""Reject direct SQL execution requests before generating business tool calls."""

from __future__ import annotations

import re
from app.application.workflow.workflow_types import PlanGraph

REFUSAL_CODE = "raw_sql_execution_not_supported"
REFUSAL_MESSAGE = "不能直接执行数据库 SQL。请使用具体的业务操作，并先确认操作对象和影响范围。"


def _without_block_comments(text: str) -> str:
    """Remove non-nested SQL block comments in one forward pass."""
    parts: list[str] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("/*", cursor)
        if start < 0:
            parts.append(text[cursor:])
            break
        parts.append(text[cursor:start])
        end = text.find("*/", start + 2)
        if end < 0:
            parts.append(text[start:])
            break
        parts.append(" ")
        cursor = end + 2
    return "".join(parts)








def rejected_sql_plan(message: str, plan_id: str) -> PlanGraph | None:
    text = _without_block_comments(message)
    statement = re.search(
        r"\b(?:delete\s+from|truncate\s+(?:table\s+)?\w+|drop\s+(?:table|database)|update\s+\w+\s+set|insert\s+into)\b",
        text,
        re.I,
    )
    if statement is None:
        return None
    prefix = text[: statement.start()]
    if prefix.strip() and not re.search(r"执行|运行|\b(?:execute|run)\b", prefix, re.I):
        return None
    return PlanGraph(
        plan_id=plan_id,
        intent="rejected_sql_execution",
        metadata={
            "refusal_code": REFUSAL_CODE,
            "message": REFUSAL_MESSAGE,
        },
    )
