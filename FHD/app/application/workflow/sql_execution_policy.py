"""Reject direct SQL execution requests before generating business tool calls."""

from __future__ import annotations

import re
from typing import Any

from app.application.workflow.types import PlanGraph, WorkflowNode

REFUSAL_CODE = "raw_sql_execution_not_supported"
REFUSAL_MESSAGE = "不能直接执行数据库 SQL。请使用具体的业务操作，并先确认操作对象和影响范围。"


def database_restore_plan(message: str, plan_id: str, registry: dict[str, Any]) -> PlanGraph | None:
    if not re.match(r"^\s*(?:(?:请|麻烦|你|帮我|现在|先|只|立即)\s*)*(?:恢复|还原)(?:一次)?数据库", message):
        return None
    # Conditional failure instructions do not report a past failed restore.
    request = re.split(r"如果|若|一旦", message, maxsplit=1)[0]
    if re.search(r"如何|怎样|怎么|解释|介绍|只查看|是否|能否|可否|可以吗|能不能|吗[？?]?$", request):
        return None
    if re.search(r"(?:恢复|还原)(?:一次)?数据库[^。；;]*(?:失败|报错)|(?:排查|诊断)(?:原因|故障)", request):
        return None
    filename = re.search(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.bak\b", message)
    available = "restore_database" in registry.get("system_maintenance", {}).get("actions", {})
    if not filename or not available:
        node = WorkflowNode(
            "clarify_restore",
            "clarify",
            "ask",
            params={"question": "请提供备份列表中的文件名，并确认当前账号可使用数据库恢复功能。"},
            risk="low",
            idempotent=True,
        )
    else:
        node = WorkflowNode(
            "restore_database",
            "system_maintenance",
            "restore_database",
            params={"backup_file": filename.group()},
            risk="high",
            idempotent=False,
            description="通过正常审批后恢复一次指定数据库备份",
        )
    return PlanGraph(plan_id=plan_id, intent="database_restore", nodes=[node], risk_level=node.risk)


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
