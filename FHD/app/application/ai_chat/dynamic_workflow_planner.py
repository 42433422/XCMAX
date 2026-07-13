"""Planner, risk gate, confirmation, and execution for dynamic workflows."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from app.application.ai_chat.excel_import_policy import (
    _enrich_confirmation_inner,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class AIChatWorkflowPlannerExecutor:
    def __init__(
        self,
        *,
        workflow_planner: Any,
        risk_gate: Any,
        approval_service: Any,
        workflow_engine: Any,
        pending_workflows: dict[str, dict[str, Any]],
        merge_tool_runtime_context: Callable[..., dict[str, Any]],
        build_workflow_thinking_steps: Callable[..., str],
        format_agent_run_response: Callable[..., dict[str, Any]],
        format_workflow_run_response: Callable[..., dict[str, Any]],
        start_agentic_workflow_agent_run: Callable[..., Any],
        bridge_agentic_workflow_result_to_agent_run: Callable[..., Any],
    ) -> None:
        self.workflow_planner = workflow_planner
        self.risk_gate = risk_gate
        self.approval_service = approval_service
        self.workflow_engine = workflow_engine
        self._pending_workflows = pending_workflows
        self._merge_tool_runtime_context = merge_tool_runtime_context
        self._build_workflow_thinking_steps = build_workflow_thinking_steps
        self._format_agent_run_response = format_agent_run_response
        self._format_workflow_run_response = format_workflow_run_response
        self._start_agentic_workflow_agent_run = start_agentic_workflow_agent_run
        self._bridge_agentic_workflow_result_to_agent_run = (
            bridge_agentic_workflow_result_to_agent_run
        )

    def plan_and_execute(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # 动态规划：不依赖关键词硬编码决策
        from app.application.facades.tools_facade import get_workflow_tool_registry

        tool_registry = get_workflow_tool_registry()
        plan = self.workflow_planner.plan(
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context,
        )

        decision = self.risk_gate.evaluate(plan=plan, context=context)
        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["dynamic_workflow"] = True
        thinking_steps = self._build_workflow_thinking_steps(
            plan=plan, decision_reason=decision.reason
        )

        approval_required_nodes = self.approval_service.get_approval_required_nodes(plan)
        has_approval_requirement = bool(approval_required_nodes)
        approval_info = ""
        if has_approval_requirement:
            approval_node_names = [f"{n.tool_id}.{n.action}" for n in approval_required_nodes]
            approval_info = "\n以下操作需要审批后执行：" + "、".join(approval_node_names)

        use_agentic = bool((runtime_ctx.get("excel_analysis") or {}).get("file_path"))
        if not has_approval_requirement and not use_agentic:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self._format_agent_run_response(
                    plan,
                    agent_run,
                    thinking_steps=thinking_steps,
                    user_message=str(message or ""),
                )
            blocking_nodes = [
                step.node_id
                for step in getattr(agent_run, "steps", []) or []
                if step.status == "waiting_user"
            ]
            self._pending_workflows[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run.run_id,
                "thinking_steps": thinking_steps,
                "approval_required": False,
                "approval_nodes": [],
            }
            todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
            reason = decision.reason or "工具策略要求用户确认"
            response_text = (
                "我已根据语义生成动态工作流计划：\n"
                f"{thinking_steps}\n\n"
                f"{todo_text}\n\n"
                f"检测到需确认步骤（{', '.join(blocking_nodes) or 'workflow'}），"
                "回复「确认」继续执行，回复「取消」终止。"
            )
            confirm_inner = {
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "thinking_steps": thinking_steps,
                "todo": plan.todo_steps,
                "blocking_nodes": blocking_nodes,
                "reason": reason,
                "approval_required": False,
                "approval_nodes": [],
            }
            return {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "data": _enrich_confirmation_inner(
                        confirm_inner, action="workflow_confirmation_required"
                    ),
                },
            }

        agent_run_id = ""
        if decision.requires_confirmation and not has_approval_requirement:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self._format_agent_run_response(
                    plan,
                    agent_run,
                    thinking_steps=thinking_steps,
                    user_message=str(message or ""),
                )
            agent_run_id = agent_run.run_id

        if decision.requires_confirmation or has_approval_requirement:
            self._pending_workflows[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run_id,
                "thinking_steps": thinking_steps,
                "approval_required": has_approval_requirement,
                "approval_nodes": [
                    {
                        "node_id": n.node_id,
                        "tool_id": n.tool_id,
                        "action": n.action,
                        "params": n.params,
                    }
                    for n in approval_required_nodes
                ],
            }
            todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
            response_text = (
                "我已根据语义生成动态工作流计划：\n"
                f"{thinking_steps}\n\n"
                f"{todo_text}\n\n"
                f"检测到中高风险步骤（{', '.join(decision.blocking_nodes)}），"
                "回复「确认」继续执行，回复「取消」终止。"
                f"{approval_info if has_approval_requirement else ''}"
            )
            risk_inner = {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "thinking_steps": thinking_steps,
                "todo": plan.todo_steps,
                "blocking_nodes": decision.blocking_nodes,
                "reason": decision.reason,
                "approval_required": has_approval_requirement,
                "approval_nodes": [
                    {"node_id": n.node_id, "tool_id": n.tool_id, "action": n.action}
                    for n in approval_required_nodes
                ],
            }
            payload: dict[str, Any] = {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "data": _enrich_confirmation_inner(
                        risk_inner, action="workflow_confirmation_required"
                    ),
                },
            }
            if agent_run_id:
                payload["run_id"] = agent_run_id
                payload["agent_run_id"] = agent_run_id
                payload["data"]["run_id"] = agent_run_id
                payload["data"]["agent_run_id"] = agent_run_id
                payload["data"]["data"]["run_id"] = agent_run_id
                payload["data"]["data"]["agent_run_id"] = agent_run_id
            return payload

        agentic_pre_run = None
        if use_agentic:
            try:
                agentic_pre_run = self._start_agentic_workflow_agent_run(
                    user_id=user_id,
                    message=message,
                    plan=plan,
                    runtime_context=runtime_ctx,
                )
                runtime_ctx["run_id"] = agentic_pre_run.run_id
                runtime_ctx["agent_run_id"] = agentic_pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("Agentic workflow AgentRun pre-create skipped", exc_info=True)

        run_result = self.workflow_engine.run(
            plan=plan,
            runtime_context=runtime_ctx,
            max_retries=1,
            agentic_loop=use_agentic,
            tool_registry=tool_registry,
            user_id=user_id,
        )
        if use_agentic:
            agent_run = self._bridge_agentic_workflow_result_to_agent_run(
                user_id=user_id,
                message=message,
                plan=plan,
                run_result=run_result,
                runtime_context=runtime_ctx,
                agent_run=agentic_pre_run,
            )
            return self._format_agent_run_response(
                plan,
                agent_run,
                thinking_steps=thinking_steps,
                user_message=str(message or ""),
            )
        return self._format_workflow_run_response(
            plan,
            run_result,
            thinking_steps=thinking_steps,
            user_message=str(message or ""),
        )


__all__ = ["AIChatWorkflowPlannerExecutor"]
