"""Reject direct SQL execution requests before generating business tool calls."""

from __future__ import annotations

import re

from app.application.workflow.types import PlanGraph

REFUSAL_CODE = "raw_sql_execution_not_supported"
REFUSAL_MESSAGE = "不能直接执行数据库 SQL。请使用具体的业务操作，并先确认操作对象和影响范围。"


def rejected_sql_plan(message: str, plan_id: str) -> PlanGraph | None:
    text = re.sub(r"/\*.*?\*/", " ", message, flags=re.S)
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
