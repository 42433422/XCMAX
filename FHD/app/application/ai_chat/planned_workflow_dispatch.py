"""Dispatch planned chat workflows through explicit risk and approval boundaries."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Protocol

from app.application.ai_chat.excel_import_policy import _enrich_confirmation_inner

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow.risk_gate import HybridRiskGate
    from app.application.workflow.workflow_types import PlanGraph

logger = logging.getLogger(__name__)


class WorkflowDispatchCallbacks(Protocol):
    def _build_workflow_thinking_steps(self, plan: PlanGraph, decision_reason: str) -> str: ...
    def _format_agent_run_response(
        self, plan: PlanGraph, agent_run: AgentRun, thinking_steps: str = "", user_message: str = ""
    ) -> dict[str, Any]: ...
    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...
    def _capture_agent_run_interaction(
        self,
        *,
        user_id: str,
        agent_run: AgentRun,
        runtime_context: dict[str, Any],
        thinking_steps: str = "",
        decision_reason: str = "",
        approval_nodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None: ...
    def _persist_plan_state(
        self,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None,
        status: str,
        message: str | None = None,
    ) -> bool: ...
    def _resume_pending_dynamic_workflow(
        self, user_id: str, message: str, text: str, context: dict[str, Any] | None = None
    ) -> tuple[bool, dict[str, Any] | None]: ...
    @staticmethod
    def _task_owner_id(user_id: str, runtime_context: dict[str, Any]) -> str: ...


class PlannedWorkflowDispatch:
    def __init__(
        self,
        pending: dict[str, dict[str, Any]],
        callbacks: WorkflowDispatchCallbacks,
        planner: LLMWorkflowPlanner,
        risk_gate: HybridRiskGate,
        approval: ApprovalService,
    ) -> None:
        self.pending = pending
        self.callbacks = callbacks
        self.planner = planner
        self.risk_gate = risk_gate
        self.approval = approval

    @staticmethod
    def _execute_reply_plan(plan: PlanGraph, context: dict[str, Any]) -> dict[str, Any]:
        """Run a model-authored plain reply through the same LangGraph runtime."""
        from app.infrastructure.workflow.langgraph_runtime import XCAGILangGraphRuntime

        if len(plan.nodes) != 1 or (plan.nodes[0].tool_id, plan.nodes[0].action) != (
            "conversation",
            "reply",
        ):
            return {
                "success": False,
                "execution_state": "failed",
                "message": "普通回复图必须只包含受限的 conversation.reply 节点",
                "response": "平台模型回复未通过 LangGraph 校验。",
                "data": {"action": "model_reply_failed", "execution_started": False},
            }

        def dispatch(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
            if (tool_id, action) != ("conversation", "reply"):
                return {
                    "success": False,
                    "error_code": "reply_plan_action_invalid",
                    "message": "普通回复图包含未授权的内部动作",
                }
            response = str(params.get("response") or "").strip()
            if not response or len(response) > 12_000:
                return {
                    "success": False,
                    "error_code": "reply_plan_payload_invalid",
                    "message": "平台模型没有生成有效回复",
                }
            return {"success": True, "response": response}

        result = XCAGILangGraphRuntime(tool_dispatcher=dispatch).run(
            plan,
            runtime_context={
                "turn_id": str(context.get("turn_id") or ""),
                "source": str(context.get("source") or ""),
            },
            max_retries=0,
            parallel=False,
        )
        if not result.success:
            return {
                "success": False,
                "execution_state": "failed",
                "message": result.message or "平台模型回复未通过 LangGraph 校验",
                "response": result.message or "平台模型回复未通过 LangGraph 校验",
                "data": {
                    "action": "model_reply_failed",
                    "execution_started": False,
                    "workflow_status": result.final_context.get("workflow_status") or {},
                },
            }
        outputs = result.final_context.get("node_outputs")
        reply = outputs.get(plan.nodes[0].node_id) if isinstance(outputs, dict) else None
        text = str(reply.get("response") or "").strip() if isinstance(reply, dict) else ""
        if not text:
            return {
                "success": False,
                "execution_state": "failed",
                "message": "平台模型没有返回可用回复",
                "response": "平台模型没有返回可用回复，请重试。",
                "data": {"action": "model_reply_failed", "execution_started": False},
            }
        return {
            "success": True,
            "message": "回复完成",
            "response": text,
            "data": {
                "text": text,
                "action": "model_reply",
                "workflow_runtime": "xcagi-langgraph",
                "plan_audit": result.final_context.get("plan_audit") or {},
                "workflow_trace": result.final_context.get("workflow_trace") or [],
            },
        }

    def handle(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None:
        from app.application.agent_orchestrator.attachment_inputs import (
            AttachmentInputError,
            resolve_attachment_context,
        )

        try:
            context, attachments = resolve_attachment_context(context)
        except AttachmentInputError as exc:
            return {
                "success": False,
                "execution_state": "blocked",
                "message": str(exc),
                "response": str(exc),
                "data": {"error_code": "attachment_reupload_required", "execution_started": False},
            }
        pending_handled, pending_result = self.callbacks._resume_pending_dynamic_workflow(
            user_id, message, text, context
        )
        if pending_handled:
            return pending_result
        from app.application.facades.tools_facade import get_workflow_tool_registry

        tool_registry = get_workflow_tool_registry()
        planner_message = message
        from app.domain.conversation.services.chat_tool_intent import (
            references_recent_business_record,
        )

        if references_recent_business_record(str(message or "")):
            from app.domain.shared_services.tools_workflow_registered import (
                get_recent_business_db_target,
            )

            recent_target = get_recent_business_db_target(user_id)
            if recent_target is None:
                return {
                    "success": True,
                    "message": "需要澄清",
                    "response": "当前会话没有可安全引用的上一条数据库记录，请提供实体名称和唯一 ID。",
                    "data": {
                        "text": "当前会话没有可安全引用的上一条数据库记录，请提供实体名称和唯一 ID。",
                        "action": "clarification_required",
                        "data": {
                            "requires_confirmation": True,
                            "reason": "missing_recent_database_target",
                            "field": "id",
                        },
                    },
                }
            entity_labels = {
                "customers": "客户",
                "products": "产品",
                "materials": "原材料",
                "shipment_records": "发货记录",
            }
            entity = str(recent_target.get("entity") or "")
            planner_message = f"{message}；数据库{entity_labels.get(entity, entity)} ID: {int(recent_target['id'])}"
        plan = self.planner.plan(
            user_id=user_id, message=planner_message, tool_registry=tool_registry, context=context
        )
        from app.application.workflow.workflow_types import PlanGraph

        if not isinstance(plan, PlanGraph):
            logger.warning("工作流规划器返回无效计划类型: %s", type(plan).__name__)
            # A business-domain request that failed planning must not fall through
            # to the general chat completion path, which has no verified tool
            # result and could otherwise answer from model priors.
            message_text = (
                "平台模型未生成可执行计划，本次没有执行任何业务操作。请重试或补充具体查询条件。"
            )
            return {
                "success": False,
                "execution_state": "failed",
                "message": message_text,
                "response": message_text,
                "data": {
                    "text": message_text,
                    "action": "workflow_planning_failed",
                    "error_code": "workflow_plan_unavailable",
                    "execution_started": False,
                },
            }
        if attachments:
            plan.metadata["artifacts"] = attachments
        if (plan.metadata or {}).get("planning_rejected") is True:
            reason = str((plan.metadata or {}).get("rejection_reason") or "").strip()
            unavailable = (plan.metadata or {}).get("planning_unavailable") is True
            if unavailable and "余额不足" in reason:
                message_text = f"{reason.rstrip('。')}。本次没有执行任何业务操作。"
            elif unavailable:
                message_text = (
                    "平台模型暂时没有返回可用结果，请检查模型连接后重试。本次没有执行任何业务操作。"
                )
            else:
                message_text = (
                    "平台模型计划未通过系统校验，本次没有执行任何业务操作。请补充条件后重试。"
                )
            return {
                "success": False,
                "execution_state": "failed",
                "message": message_text,
                "response": message_text,
                "data": {
                    "text": message_text,
                    "action": "workflow_planning_failed",
                    "error_code": "workflow_plan_unavailable"
                    if unavailable
                    else "workflow_plan_rejected",
                    "execution_started": False,
                    **({"reason": reason[:240]} if reason else {}),
                },
            }
        if (plan.metadata or {}).get("response_mode") == "reply":
            result = self._execute_reply_plan(plan, context)
            if attachments and result.get("success"):
                result["data"]["artifacts"] = attachments
            return result
        from app.domain.autonomy.autonomy_guard import ProhibitedActionError

        try:
            decision = self.risk_gate.evaluate(plan=plan, context=context)
        except ProhibitedActionError as exc:
            return self._risk_rejection(
                "workflow_action_prohibited",
                str(getattr(exc, "reason", "操作命中禁止边界")),
            )
        plan_node_ids = {str(node.node_id) for node in plan.nodes}
        denied_nodes = decision.denied_nodes or []
        blocking_nodes = decision.blocking_nodes or []
        if not isinstance(denied_nodes, (list, tuple, set, frozenset)) or not isinstance(
            blocking_nodes, (list, tuple, set, frozenset)
        ):
            return self._risk_rejection("workflow_risk_denied", "风险审核结果格式无效")
        denied_ids = {str(node_id) for node_id in denied_nodes if str(node_id)}
        blocking_ids = {str(node_id) for node_id in blocking_nodes if str(node_id)}
        if (
            denied_ids
            or (not decision.allowed and not decision.requires_confirmation)
            or (decision.requires_confirmation and not blocking_ids)
            or not blocking_ids <= plan_node_ids
        ):
            return self._risk_rejection(
                "workflow_risk_denied",
                str(decision.reason or "计划未通过自主执行风险策略"),
            )
        runtime_ctx = self.callbacks._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["dynamic_workflow"] = True
        thinking_steps = self.callbacks._build_workflow_thinking_steps(
            plan=plan, decision_reason=decision.reason
        )
        approval_required_nodes = self.approval.get_approval_required_nodes(plan)
        approval_ids = {str(node.node_id) for node in approval_required_nodes}
        approval_ids.update(blocking_ids)
        approval_required_nodes = [node for node in plan.nodes if str(node.node_id) in approval_ids]
        has_approval_requirement = bool(approval_required_nodes)
        approval_info = ""
        if has_approval_requirement:
            approval_node_names = [f"{n.tool_id}.{n.action}" for n in approval_required_nodes]
            approval_info = "\n以下操作需要审批后执行：" + "、".join(approval_node_names)
        # The LLM has already produced the bounded business plan above. Excel
        # analysis must execute that same durable AgentRun graph as every other
        # workflow; the former second, model-directed tool loop had no complete
        # approval/permission/receipt boundary and is retired.
        if not has_approval_requirement or any(
            node.tool_id == "clarify" and node.action == "ask" for node in plan.nodes
        ):
            from app.application.agent_orchestrator import AgentOrchestrator

            if has_approval_requirement:
                plan.metadata["approval_required_node_ids"] = sorted(approval_ids)

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=self.callbacks._task_owner_id(user_id, runtime_ctx),
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self.callbacks._format_agent_run_response(
                    plan, agent_run, thinking_steps=thinking_steps, user_message=str(message or "")
                )
            approval_metadata = [
                {
                    "node_id": node.node_id,
                    "tool_id": node.tool_id,
                    "action": node.action,
                    "params": node.params,
                }
                for node in approval_required_nodes
            ]
            return self.callbacks._capture_agent_run_interaction(
                user_id=user_id,
                agent_run=agent_run,
                runtime_context=runtime_ctx,
                thinking_steps=thinking_steps,
                decision_reason=decision.reason,
                approval_nodes=approval_metadata,
            )
        approval_metadata = [
            {
                "node_id": node.node_id,
                "tool_id": node.tool_id,
                "action": node.action,
                "params": node.params,
            }
            for node in approval_required_nodes
        ]
        self.pending[user_id] = {
            "plan": plan,
            "runtime_context": runtime_ctx,
            "pending_id": uuid.uuid4().hex,
            "agent_run_id": "",
            "thinking_steps": thinking_steps,
            "kind": "workflow",
            "approval_required": True,
            "approval_nodes": approval_metadata,
        }
        self.callbacks._persist_plan_state(plan, runtime_ctx, status="pending_awaiting")
        todo_text = "\n".join(f"- {step}" for step in plan.todo_steps or [])
        response_text = (
            f"我已根据语义生成动态工作流计划：\n{thinking_steps}\n\n{todo_text}\n\n"
            f"此计划包含需审批的操作（{', '.join(decision.blocking_nodes or approval_node_names)}），"
            "回复「确认」提交执行计划，回复「取消」终止。"
            f"{approval_info}"
        )
        approval_inner = {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "thinking_steps": thinking_steps,
            "todo": plan.todo_steps,
            "blocking_nodes": decision.blocking_nodes,
            "reason": decision.reason,
            "approval_required": True,
            "approval_nodes": [
                {"node_id": node.node_id, "tool_id": node.tool_id, "action": node.action}
                for node in approval_required_nodes
            ],
        }
        return {
            "success": True,
            "message": "等待确认",
            "execution_state": "waiting_user",
            "execution_started": False,
            "response": response_text,
            "data": {
                "text": response_text,
                "action": "workflow_confirmation_required",
                "data": _enrich_confirmation_inner(
                    approval_inner, action="workflow_confirmation_required"
                ),
            },
        }

    @staticmethod
    def _risk_rejection(code: str, reason: str) -> dict[str, Any]:
        message = "计划未通过系统风险审核，本次没有执行任何业务操作。"
        return {
            "success": False,
            "execution_state": "blocked",
            "message": message,
            "response": message,
            "data": {
                "text": message,
                "action": "workflow_risk_rejected",
                "error_code": code,
                "reason": str(reason or "")[:240],
                "execution_started": False,
            },
        }
