"""员工写操作审批门，使用确定性风险策略和审批服务。"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_GATE_INVOCATION_ERRORS = (TypeError,) + RECOVERABLE_ERRORS


def build_write_approval_gate(
    employee_id: str,
    input_data: dict[str, Any] | None = None,
    *,
    runtime_context: dict[str, Any] | None = None,
):
    """返回 agent_loop gate：(tool_name, args) -> {ok, reason}。

    代码修改工具（``patch_file`` / ``write_file``）统一委托 autonomy_guard；
    业务写操作从当前注册契约解析动作，绑定原 AgentRun 后持久化审批。
    模型参数和员工输入不能自我声明批准，也不能携带服务端写令牌绕过审批。
    """
    # Legacy positional input is model/user data, never approval evidence.
    trusted_context = dict(runtime_context or {})

    def gate(
        tool_name: str,
        args: dict[str, Any],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from resources.config.risk_actions_loader import (
            list_code_write_tools,
            list_write_tools,
        )

        name = str(tool_name or "").strip()
        code_writes = list_code_write_tools()
        if name not in list_write_tools() and name not in code_writes:
            return {"ok": True}
        if runtime_context is not None and not str(runtime_context.get("call_id") or "").strip():
            return {
                "ok": False,
                "blocked": True,
                "execution_state": "blocked",
                "retryable": False,
                "reason": "写操作缺少当前工具调用标识，未创建审批或执行，不能复用父调用标识。",
            }
        # The loop supplies its current tool-call identity separately from model
        # arguments. Keep this exact scope when staging the original approval.
        payload = {**trusted_context, **dict(runtime_context or {}), "employee_id": employee_id}
        if name in code_writes:
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
        from app.application.employee_runtime.result_verifier import pending_employee_result
        from app.application.tools.registered_capabilities import execute_registered_capability
        from resources.config.risk_actions_loader import (
            get_action_approval,
            get_action_risk,
            get_workflow_tools_from_registry,
            requires_write_approval,
        )

        try:
            actions = (get_workflow_tools_from_registry().get(name) or {}).get("actions") or {}
            action = str(args.get("action") or "").strip()
            if not action and len(actions) == 1:
                action = next(iter(actions))
            if not action or action not in actions:
                return {
                    "ok": False,
                    "blocked": True,
                    "reason": "工具缺少明确的已登记动作，未执行或创建审批；请使用已登记能力，导入可先发起 ELT 预演。",
                }
            if (
                not requires_write_approval(name, action)
                and get_action_approval(name, action) not in {"always", "interactive"}
                and get_action_risk(name, action) == "low"
                and actions[action].get("idempotent") is True
            ):
                return {"ok": True}
            params = (
                dict(args["params"])
                if isinstance(args.get("params"), dict)
                else {key: value for key, value in args.items() if key != "action"}
            )
            receipt = json.loads(
                execute_registered_capability(
                    {"tool_id": name, "action": action, "params": params},
                    workspace_root=payload.get("workspace_root"),
                    runtime_context=payload,
                    require_approval=True,
                )
            )
            return {
                "ok": False,
                "reason": str(
                    receipt.get("message") or receipt.get("error") or "请查询原任务回执。"
                ),
                "execution_result": receipt,
                **pending_employee_result(receipt),
            }
        except RECOVERABLE_ERRORS:
            logger.exception(
                "employee approval receipt unavailable emp=%s tool=%s", employee_id, name
            )
            return {
                "ok": False,
                "reason": "原任务审批回执尚未确认，请核对原任务，勿重复提交。",
                "execution_state": "unknown",
                "retryable": False,
                "requires_reconciliation": True,
            }

    return gate


def invoke_employee_gate(
    gate: Any,
    tool_name: str,
    args: dict[str, Any],
    *,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adapt legacy validation gates before invocation, never retry after a call."""
    try:
        signature = inspect.signature(gate)
        context_param = signature.parameters.get("runtime_context")
        accepts_context = (
            context_param is not None
            and context_param.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        ) or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        options: dict[str, Any] = {"runtime_context": runtime_context} if accepts_context else {}
        signature.bind(tool_name, args, **options)
    except (TypeError, ValueError):
        return {"ok": False, "blocked": True, "reason": "工具授权接口无效，未调用"}
    try:
        return cast("dict[str, Any]", gate(tool_name, args, **options))
    except _GATE_INVOCATION_ERRORS:
        # A write gate can already have published an approval. Losing its return
        # value is not evidence that nothing happened and cannot trigger replay.
        return {
            "ok": False,
            "execution_state": "unknown",
            "retryable": False,
            "requires_reconciliation": True,
            "reason": "工具授权回执尚未确认，请核对原任务，勿重复提交。",
        }


def compose_gates(*gates: Any) -> Any:
    """合并多个 gate（WorkspaceGuard + write approval 等）。"""
    active = [g for g in gates if g is not None]
    if not active:
        return None

    def combined(
        tool_name: str,
        args: dict[str, Any],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for g in active:
            try:
                verdict = invoke_employee_gate(g, tool_name, args, runtime_context=runtime_context)
            except RECOVERABLE_ERRORS:
                return {"ok": False, "reason": "工具授权检查失败，未执行"}
            if not isinstance(verdict, dict) or type(verdict.get("ok")) is not bool:
                return {"ok": False, "reason": "工具授权结果无效，未执行"}
            if verdict["ok"] is not True:
                return cast("dict[str, Any]", verdict)
        return {"ok": True}

    return combined


__all__ = ["build_write_approval_gate", "compose_gates", "invoke_employee_gate"]
