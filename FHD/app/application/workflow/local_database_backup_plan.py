"""Admit official local database backup commands before model planning."""

from __future__ import annotations

import re

from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

_CREATE = re.compile(
    r"(?:备份(?:一下|下|一次|一回)?数据库)|(?:创建.{0,12}(?:本机)?数据库备份)|(?:本机数据库备份)"
)
_RESTORE_OR_DELETE = re.compile(r"恢复|还原|删除")
_VIEW = re.compile(r"查看|查询|列出|有哪些")
_DEST = re.compile(r"到\s*(U\s*盘|优盘|usb|硬盘|网盘|外置)", re.I)
_NEGATE = re.compile(r"不要|别再|禁止|取消备份")
_UNSUPPORTED = "当前只支持创建本机数据库备份，不能把备份直接写到指定外部位置。请改口为创建本机备份。"
_NEGATED = "已按你的要求，不会创建数据库备份。"


def classify_local_database_backup(message: str) -> str | None:
    text = str(message or "").strip()
    if not text or not _CREATE.search(text):
        return None
    if _RESTORE_OR_DELETE.search(text):
        return None
    if _VIEW.search(text) and "创建" not in text and "备份数据库" not in text:
        return None
    if _NEGATE.search(text):
        return "negated"
    if _DEST.search(text):
        return "unsupported_destination"
    return "backup"


def local_database_backup_plan(message: str, plan_id: str) -> PlanGraph | None:
    kind = classify_local_database_backup(message)
    if kind is None:
        return None
    if kind != "backup":
        reason = _NEGATED if kind == "negated" else _UNSUPPORTED
        return PlanGraph(
            plan_id=plan_id,
            intent="system_maintenance_backup_database",
            metadata={"planning_rejected": True, "rejection_reason": reason, "planning_source": "deterministic_command"},
        )
    return PlanGraph(
        plan_id=plan_id,
        intent="system_maintenance_backup_database",
        todo_steps=["创建一次本机数据库备份"],
        nodes=[WorkflowNode(node_id="backup_database", tool_id="system_maintenance", action="backup_database", params={}, risk="medium")],
        metadata={"planning_source": "deterministic_command"},
        risk_level="medium",
    )
