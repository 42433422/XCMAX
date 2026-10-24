"""Reject direct SQL execution requests before generating business tool calls."""

from __future__ import annotations

import re
from typing import Any

from app.application.workflow.types import PlanGraph, WorkflowNode

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


def _backup_filename(request: str) -> str | None:
    """Find the first `.bak` filename with a linear scan over untrusted text."""
    allowed = "_.-"
    for end in range(len(request) - 3):
        if request[end : end + 4].lower() != ".bak":
            continue
        after = end + 4
        if after < len(request) and (request[after] == "_" or request[after].isalnum()):
            continue
        start = end
        while start > 0:
            char = request[start - 1]
            if char.isascii() and (char.isalnum() or char in allowed):
                start -= 1
            else:
                break
        if (
            start < end
            and (start == 0 or request[start - 1] not in "/\\:")
            and request[start].isascii()
            and request[start].isalnum()
        ):
            return request[start : end + 4]
    return None


def database_maintenance_request(message: str) -> tuple[str, str] | None:
    command = (
        r"^\s*(?:(?:请|麻烦|你|帮我|现在|先|只|立即)\s*)*"
        r"(?:(恢复|还原|备份)(?:一次)?(?:当前)?(?:本机|本地)?数据库"
        r"|(?:创建|生成|做)(?:一次|一份)?(?:当前)?(?:本机|本地)?数据库备份)"
    )
    match = re.match(command, message)
    if not match:
        return None
    # Conditional failure instructions do not report a past failed restore.
    request = re.split(r"如果|若|一旦", message, maxsplit=1)[0]
    question = r"如何|怎样|怎么|什么|解释|介绍|只查看|是否|能否|可否|可以吗|能不能|吗[？?]?$"
    diagnostic = r"失败|报错|卡住|异常|排查|诊断"
    if re.search(question, request) or re.search(diagnostic, request):
        return None
    return ("restore_database" if match[1] in {"恢复", "还原"} else "backup_database", request)


def database_maintenance_plan(
    message: str, plan_id: str, registry: dict[str, Any]
) -> PlanGraph | None:
    parsed = database_maintenance_request(message)
    if parsed is None:
        return None
    action, request = parsed
    restore = action == "restore_database"
    filename = _backup_filename(request) if restore else None
    available = action in registry.get("system_maintenance", {}).get("actions", {}) and (
        not restore or bool(filename)
    )
    question = "请确认账号可使用数据库维护功能；恢复时请提供备份列表中的文件名。"
    node = WorkflowNode(
        action if available else "clarify_maintenance",
        "system_maintenance" if available else "clarify",
        action if available else "ask",
        params=({"backup_file": filename} if filename else {})
        if available
        else {"question": question},
        risk=("high" if restore else "medium") if available else "low",
        idempotent=not available,
        description="通过正常审批执行一次数据库维护操作",
    )
    return PlanGraph(
        plan_id=plan_id,
        intent="database_restore" if restore else "database_backup",
        nodes=[node],
        risk_level=node.risk,
    )


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
