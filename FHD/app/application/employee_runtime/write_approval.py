"""员工写操作审批门（接 ApprovalGatedEngine 语义，轻量 tool_call 级 gate）。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.application.employee_runtime.tool_scope import CODE_WRITE_TOOLS, WRITE_TOOLS
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def build_write_approval_gate(
    employee_id: str,
    input_data: dict[str, Any] | None = None,
):
    """返回 agent_loop gate：(tool_name, args) -> {ok, reason}。

    代码修改工具（``patch_file`` / ``write_file``）统一委托 autonomy_guard；
    写库类业务工具（``import_excel_to_database`` / ``products_bulk_import``）只接受
    ApprovalGatedEngine 中已持久化的审批结果。模型参数和员工输入不能自我声明批准，
    也不能携带服务端写令牌绕过审批。
    """
    payload = dict(input_data or {})

    def gate(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        name = str(tool_name or "").strip()
        if name not in WRITE_TOOLS and name not in CODE_WRITE_TOOLS:
            return {"ok": True}
        if name in CODE_WRITE_TOOLS:
            from app.domain.autonomy.autonomy_guard import evaluate_risk

            decision = evaluate_risk(
                "code_write",
                {**payload, "tool": name},
                action_id=str(payload.get("action_id") or "") or None,
                source=f"employee_write:{employee_id}",
            )
            if decision.allowed:
                return {"ok": True, "risk_decision": decision.to_dict()}
            return {
                "ok": False,
                "reason": decision.reason,
                "blocked": not decision.requires_confirmation,
                "pending_approval": decision.requires_confirmation,
                "risk_decision": decision.to_dict(),
            }
        try:
            from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
            from app.application.workflow.engine import WorkflowEngine
            from app.application.workflow.types import PlanGraph, WorkflowNode
            from resources.config.risk_actions_loader import get_action_risk

            write_action = "execute"
            if name in ("import_excel_to_database", "products_bulk_import"):
                write_action = "import"
            risk = get_action_risk(name, write_action, default="high")
            plan = PlanGraph(
                plan_id=f"emp-write-{employee_id}-{uuid.uuid4().hex[:8]}",
                intent=f"员工 {employee_id} 写操作审批",
                nodes=[
                    WorkflowNode(
                        node_id="write",
                        tool_id=name,
                        action=write_action,
                        params=dict(args or {}),
                        risk=risk,
                    )
                ],
                risk_level=risk,
            )
            gated = ApprovalGatedEngine(WorkflowEngine(lambda **kw: {"success": True}))
            decision = gated.evaluate_plan(plan, runtime_context=payload, strategy="interactive")
            if decision.all_approved and not decision.any_rejected:
                return {"ok": True}
            if decision.pending_approval:
                return {
                    "ok": False,
                    "reason": "写操作待审批（请在审批工作台通过后重试）",
                    "pending_approval": True,
                    "approval_request_ids": list(decision.approval_request_ids or []),
                }
        except RECOVERABLE_ERRORS:
            logger.debug(
                "write approval gate fallback emp=%s tool=%s", employee_id, name, exc_info=True
            )

        try:
            from app.application.employee_runtime.metrics import record_write_block

            record_write_block(employee_id)
        except RECOVERABLE_ERRORS:
            pass
        return {
            "ok": False,
            "reason": (
                f"写库工具 {name} 被审批门拦截：需在审批工作台通过"
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
