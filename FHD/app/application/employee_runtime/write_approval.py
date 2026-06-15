# -*- coding: utf-8 -*-
"""员工写操作审批门（接 ApprovalGatedEngine 语义，轻量 tool_call 级 gate）。"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from app.application.employee_runtime.tool_scope import WRITE_TOOLS
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def build_write_approval_gate(
    employee_id: str,
    input_data: dict[str, Any] | None = None,
):
    """返回 agent_loop gate：(tool_name, args) -> {ok, reason}。

    写库类工具（``import_excel_to_database`` / ``products_bulk_import``）需满足其一：
    - 输入 ``approved_write=True`` / ``allow_write=True``
    - 环境变量 ``FHD_DB_WRITE_TOKEN`` 已配置（与 workflow 工具一致）
    - ApprovalGatedEngine 评估为 auto-approve（strategy=auto，演示/CLI）
    """
    payload = dict(input_data or {})
    env_token = (os.environ.get("FHD_DB_WRITE_TOKEN") or "").strip()

    def gate(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        name = str(tool_name or "").strip()
        if name not in WRITE_TOOLS:
            return {"ok": True}
        if payload.get("approved_write") or payload.get("allow_write"):
            return {"ok": True}
        if env_token:
            return {"ok": True}
        token = str(args.get("db_write_token") or payload.get("db_write_token") or "").strip()
        if token and token == env_token:
            return {"ok": True}
        try:
            from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
            from app.application.workflow.engine import WorkflowEngine
            from app.application.workflow.types import PlanGraph, WorkflowNode

            plan = PlanGraph(
                plan_id=f"emp-write-{employee_id}-{uuid.uuid4().hex[:8]}",
                intent=f"员工 {employee_id} 写操作审批",
                nodes=[
                    WorkflowNode(
                        node_id="write",
                        tool_id=name,
                        action="execute",
                        params=dict(args or {}),
                        risk="high",
                    )
                ],
                risk_level="high",
            )
            gated = ApprovalGatedEngine(WorkflowEngine(lambda **kw: {"success": True}))
            decision = gated.evaluate_plan(plan, runtime_context=payload, strategy="auto")
            if decision.all_approved and not decision.any_rejected:
                return {"ok": True}
            if decision.pending_approval:
                return {
                    "ok": False,
                    "reason": "写操作待审批（请在审批工作台通过后重试，或传 approved_write=True）",
                    "pending_approval": True,
                    "approval_request_ids": list(decision.approval_request_ids or []),
                }
        except RECOVERABLE_ERRORS:
            logger.debug("write approval gate fallback emp=%s tool=%s", employee_id, name, exc_info=True)

        try:
            from app.application.employee_runtime.metrics import record_write_block

            record_write_block(employee_id)
        except RECOVERABLE_ERRORS:
            pass
        return {
            "ok": False,
            "reason": (
                f"写库工具 {name} 被审批门拦截：需 approved_write=True、"
                "FHD_DB_WRITE_TOKEN 或审批通过"
            ),
        }

    return gate


def compose_gates(*gates: Any) -> Any:
    """合并多个 gate（WorkspaceGuard + write approval 等）。"""
    active = [g for g in gates if g is not None]
    if not active:
        return None

    def combined(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        for g in active:
            try:
                verdict = g(tool_name, args)
            except RECOVERABLE_ERRORS:
                continue
            if not verdict.get("ok", True):
                return verdict
        return {"ok": True}

    return combined


__all__ = ["build_write_approval_gate", "compose_gates"]
