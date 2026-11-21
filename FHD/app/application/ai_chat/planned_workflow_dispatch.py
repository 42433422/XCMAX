"""Dispatch planned chat workflows through explicit risk and approval boundaries."""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any, Protocol

from app.application.ai_chat.excel_import_policy import _enrich_confirmation_inner
from app.application.ai_chat.workflow_session import workflow_run_note

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
    def _no_write_execution(context: dict[str, Any]) -> dict[str, Any]:
        """规划/模型阶段失败时明确记录：本回合没有产生任何业务写入。"""
        return {
            "idempotency_key": str(context.get("idempotency_key") or context.get("turn_id") or ""),
            "intent": "chat_turn",
            "committed": False,
            "effect": "none",
            "outcome": "not_executed",
        }

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
                "execution": PlannedWorkflowDispatch._no_write_execution(context),
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
                "execution": PlannedWorkflowDispatch._no_write_execution(context),
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
                "execution": PlannedWorkflowDispatch._no_write_execution(context),
                "data": {"action": "model_reply_failed", "execution_started": False},
            }
        return {
            "success": True,
            "message": "回复完成",
            "response": text,
            "execution": PlannedWorkflowDispatch._no_write_execution(context),
            "data": {
                "text": text,
                "action": "model_reply",
                "execution_started": False,
                "workflow_runtime": "xcagi-langgraph",
                "plan_audit": result.final_context.get("plan_audit") or {},
                "workflow_trace": result.final_context.get("workflow_trace") or [],
            },
        }

    def _run_admitted_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: dict[str, Any],
        thinking_steps: str = "",
        decision_reason: str = "",
        approval_nodes: list[dict[str, Any]] | None = None,
        continuation: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
        from app.infrastructure.chat_stream_lifetime import publish_stream_note

        orchestrator = AgentOrchestrator()
        if continuation:
            from app.application.agent_orchestrator.business_action_ledger import canonical_hash

            original = continuation["run"]
            original_plan = plan_from_dict(original.metadata.get("plan"))
            if original_plan is None:
                return self._risk_rejection(
                    "workflow_confirmation_stale",
                    "原澄清计划缺失，未执行本次操作。",
                    runtime_context,
                    continuation=continuation,
                )
            agent_run = orchestrator.continue_planning_clarification(
                original.run_id,
                answered_by=self.callbacks._task_owner_id(user_id, runtime_context),
                clarification_step_id=continuation["step_id"],
                expected_plan_sha256=plan_fingerprint(original_plan),
                expected_snapshot_sha256=canonical_hash(original.to_dict()),
                plan=plan,
                answer=continuation["answer"],
                runtime_context=runtime_context,
            )
            if agent_run is None:
                return self._risk_rejection(
                    "workflow_confirmation_stale",
                    "原澄清已被处理或发生变化，本次未重复执行；请查看原任务。",
                    runtime_context,
                    continuation=continuation,
                )
            plan = plan_from_dict(agent_run.metadata.get("plan")) or plan
        else:
            agent_run = orchestrator.start_run_from_plan(
                user_id=self.callbacks._task_owner_id(user_id, runtime_context),
                message=message,
                plan=plan,
                runtime_context=runtime_context,
                auto_execute=True,
            )
        publish_stream_note(workflow_run_note(agent_run.status))
        if agent_run.status == "waiting_user":
            interaction = self.callbacks._capture_agent_run_interaction(
                user_id=user_id,
                agent_run=agent_run,
                runtime_context=runtime_context,
                thinking_steps=thinking_steps,
                decision_reason=decision_reason,
                approval_nodes=approval_nodes or [],
            )
            if interaction is not None:
                interaction.setdefault("run_id", agent_run.run_id)
                interaction.setdefault("agent_run_id", agent_run.run_id)
                current = orchestrator.get_run(agent_run.run_id)
                if (
                    current is not None
                    and current.status == "waiting_user"
                    and interaction.get("success")
                ):
                    interaction.setdefault("status", "waiting_user")
                    interaction.setdefault("execution_state", "waiting_user")
                    interaction["needs_user_input"] = True
            return interaction
        result = self.callbacks._format_agent_run_response(
            plan, agent_run, thinking_steps=thinking_steps, user_message=message
        )
        if continuation:
            saved = self.callbacks._persist_plan_state(
                plan,
                runtime_context,
                status="succeeded" if agent_run.status == "completed" else agent_run.status,
                message=str(agent_run.error or ""),
            )
            if saved:
                self.pending.pop(user_id, None)
            else:
                warning = "任务回执已保存，但待办索引更新失败；请查看原任务，勿重复执行。"
                result["response"] = f"{result.get('response') or ''}\n\n{warning}".strip()
                result.setdefault("data", {})["workflow_state_persistence_failed"] = True
        return result

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
                "execution": self._no_write_execution(context),
                "data": {"error_code": "attachment_reupload_required", "execution_started": False},
            }
        pending_handled, pending_result = self.callbacks._resume_pending_dynamic_workflow(
            user_id, message, text, context
        )
        planning_continuation = (pending_result or {}).get("_planning_clarification")
        continuation_reference = {}
        if isinstance(planning_continuation, dict):
            from app.application.agent_orchestrator.tool_permission import overlay_resume_context

            original = planning_continuation["run"]
            continuation_reference = {
                "run_id": original.run_id,
                "agent_run_id": original.run_id,
            }
            incoming = context
            context = overlay_resume_context(original.metadata.get("runtime_context"), incoming)
            # This answer is a new chat turn, never a replay of the question's turn.
            for key in ("turn_id", "idempotency_key", "_conversation_input_fingerprint"):
                if key in incoming:
                    context[key] = incoming[key]
                else:
                    context.pop(key, None)
            previous = (original.metadata.get("runtime_context") or {}).get(
                "planning_clarification"
            )
            previous = previous if isinstance(previous, dict) else {}
            exchanges = previous.get("exchanges")
            exchanges = exchanges if isinstance(exchanges, list) else []
            context["planning_clarification"] = {
                "original_request": original.message,
                "exchanges": [
                    *exchanges,
                    {
                        "question": planning_continuation["question"],
                        "answer": planning_continuation["answer"],
                    },
                ],
            }
            # Accepted answers are durable task facts, not a rolling chat tail.
            # Keep this whole request in the gateway's protected latest turn:
            # if it cannot fit, preserve the wait instead of forgetting scope.
            message = json.dumps(context["planning_clarification"], ensure_ascii=False)
            pending_handled = False
        plan = None
        continuation_task: dict[str, Any] = {}
        if pending_handled:
            detail = ((pending_result or {}).get("data") or {}).get("data") or {}
            if (
                text.strip().rstrip("。.!！") != "继续"
                or detail.get("reason") != "no_pending_workflow"
            ):
                return pending_result
            from app.application.elt.batch_continuation import (
                BatchContinuationBlocked,
                active_batch_turn,
                build_batch_continuation,
            )

            current = None
            if type(context.get("_conversation_revision")) is int:
                current = active_batch_turn(
                    owner=self.callbacks._task_owner_id(user_id, context),
                    tenant=str(context.get("tenant_id") or ""),
                    mod=str(context.get("mod_id") or context.get("active_mod_id") or ""),
                    session=str(context.get("session_id") or context.get("conversation_id") or ""),
                    revision=context["_conversation_revision"],
                )
                if current and current["status"] in {"queued", "running", "retrying"}:
                    text = "原导入任务正在后台处理，已恢复查看原任务。"
                    return {
                        "success": True,
                        "message": text,
                        "response": text,
                        "run_id": current["run_id"],
                        "status": current["status"],
                        "active_turn": current,
                        "data": {"action": "workflow_waiting", "execution_started": False},
                    }
            try:
                continuation = build_batch_continuation(context)
            except BatchContinuationBlocked as exc:
                if current and current["status"] == "blocked":
                    return {
                        "success": True,
                        "message": str(exc),
                        "response": str(exc),
                        "run_id": current["run_id"],
                        "status": current["status"],
                        "active_turn": current,
                        "data": {"action": "workflow_waiting", "execution_started": False},
                    }
                return {
                    "success": False,
                    "response": str(exc),
                    "message": str(exc),
                    "execution": self._no_write_execution(context),
                    "data": {"action": "workflow_continuation_blocked", "execution_started": False},
                }
            if continuation is None:
                return pending_result
            plan, continuation_task = continuation
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
                    **continuation_reference,
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
        from app.application.workflow.workflow_types import PlanGraph
        from app.infrastructure.chat_stream_lifetime import publish_stream_note

        if plan is None:
            from app.application.ai_chat.dialogue_memory import last_assistant_question
            from app.application.workflow.clarification_selection import (
                build_continuation_message,
                looks_like_continuation_reply,
            )

            if looks_like_continuation_reply(message):
                prior_question = last_assistant_question(context)
                if prior_question:
                    planner_message = build_continuation_message(planner_message, prior_question)
            publish_stream_note("正在分析需求，生成执行计划…")
            plan = self.planner.plan(
                user_id=user_id,
                message=planner_message,
                tool_registry=tool_registry,
                context=context,
            )
        else:
            publish_stream_note(plan.intent)
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
                **continuation_reference,
                "message": message_text,
                "response": message_text,
                "execution": self._no_write_execution(context),
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
            failure_kind = str((plan.metadata or {}).get("planning_failure_kind") or "")
            coverage_rejected = (plan.metadata or {}).get("goal_coverage_rejected") is True
            failure_code = (plan.metadata or {}).get("planning_failure_code")
            deterministic = (plan.metadata or {}).get("planning_source") == "deterministic_command"
            if deterministic and reason:
                message_text = reason
            elif failure_code == "model_response_incomplete":
                warning = "模型回复未完整生成，请重试。"
                prefix = str((plan.metadata or {}).get("partial_reply") or "")
                message_text = f"{prefix}\n\n{warning}" if prefix else warning
            elif coverage_rejected:
                message_text = (
                    "这次任务的目标、条件或先后顺序尚未核对完整，本次没有执行任何业务操作。"
                    "请核对并补充任务要求后重试。"
                )
                reason = "任务目标、条件或顺序尚未核对完整"
            elif failure_code == "context_window_exceeded" or (
                unavailable and "余额不足" in reason
            ):
                message_text = f"{reason.rstrip('。')}。本次没有执行任何业务操作。"
            elif failure_kind == "plan_repair_failed":
                message_text = (
                    "模型已返回任务计划，但计划校验和自动修复均未成功。"
                    "本次没有执行任何业务操作。请重试。"
                )
            elif failure_kind == "plan_format_invalid":
                message_text = "规划输出未通过格式校验，本次没有执行任何业务操作。请重试。"
            elif failure_kind == "planner_error":
                message_text = (
                    f"{(reason or '规划服务处理失败').rstrip('。')}。本次没有执行任何业务操作。"
                )
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
                **continuation_reference,
                "message": message_text,
                "response": message_text,
                "execution": self._no_write_execution(context),
                "data": {
                    "text": message_text,
                    "action": "workflow_planning_failed",
                    "error_code": "workflow_goal_coverage_rejected"
                    if coverage_rejected
                    else "model_response_incomplete"
                    if failure_code == "model_response_incomplete"
                    else "context_window_exceeded"
                    if failure_code == "context_window_exceeded"
                    else "workflow_plan_unavailable"
                    if unavailable
                    else "workflow_plan_rejected",
                    "execution_started": False,
                    **({"reason": reason[:240]} if reason else {}),
                    **({"planning_failure_kind": failure_kind} if failure_kind else {}),
                    **(
                        {"planning_diagnostics": plan.metadata["plan_repair"]}
                        if isinstance((plan.metadata or {}).get("plan_repair"), dict)
                        else {}
                    ),
                },
            }
        if (plan.metadata or {}).get("response_mode") == "reply" and not planning_continuation:
            result = self._execute_reply_plan(plan, context)
            if attachments and result.get("success"):
                result["data"]["artifacts"] = attachments
            return result
        if planning_continuation and (plan.metadata or {}).get("response_mode") == "reply":
            runtime_ctx = self.callbacks._merge_tool_runtime_context(user_id, message, context)
            runtime_ctx["planning_clarification"] = context["planning_clarification"]
            return self._run_admitted_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                continuation=planning_continuation,
            )
        from app.application.elt.batch_continuation import (
            BatchContinuationBlocked,
            bind_durable_batch,
        )

        try:
            bind_durable_batch(plan, context)
        except BatchContinuationBlocked as exc:
            return self._risk_rejection(
                "elt_attachment_binding_failed",
                str(exc),
                context,
                continuation=planning_continuation,
            )
        node_labels = [f"{node.tool_id}.{node.action}" for node in plan.nodes]
        publish_stream_note(f"已生成 {len(node_labels)} 步执行计划：" + "、".join(node_labels))
        from app.domain.autonomy.autonomy_guard import ProhibitedActionError

        try:
            decision = self.risk_gate.evaluate(plan=plan, context=context)
        except ProhibitedActionError as exc:
            return self._risk_rejection(
                "workflow_action_prohibited",
                str(getattr(exc, "reason", "操作命中禁止边界")),
                context,
                continuation=planning_continuation,
            )
        plan_node_ids = {str(node.node_id) for node in plan.nodes}
        denied_nodes = decision.denied_nodes or []
        blocking_nodes = decision.blocking_nodes or []
        if not isinstance(denied_nodes, (list, tuple, set, frozenset)) or not isinstance(
            blocking_nodes, (list, tuple, set, frozenset)
        ):
            return self._risk_rejection(
                "workflow_risk_denied",
                "风险审核结果格式无效",
                context,
                continuation=planning_continuation,
            )
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
                context,
                continuation=planning_continuation,
            )
        runtime_ctx = self.callbacks._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx.update(continuation_task)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["dynamic_workflow"] = True
        if planning_continuation:
            runtime_ctx["planning_clarification"] = context["planning_clarification"]
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
        # Both model plans and receipt-bound continuations use the durable approval path.
        auto_approval = str(runtime_ctx.get("chat_approval_mode") or "").strip().lower() == "auto"
        if (
            not has_approval_requirement
            or auto_approval
            or plan.metadata.get("durable_elt_batch") is True
            or any(node.tool_id == "clarify" and node.action == "ask" for node in plan.nodes)
            or planning_continuation
        ):
            if has_approval_requirement:
                plan.metadata["approval_required_node_ids"] = sorted(approval_ids)
            publish_stream_note(
                "正在核对计划的审批要求…" if has_approval_requirement else "计划无需审批，开始执行…"
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
            return self._run_admitted_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                thinking_steps=thinking_steps,
                decision_reason=decision.reason,
                approval_nodes=approval_metadata,
                continuation=planning_continuation,
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
        if not self.callbacks._persist_plan_state(plan, runtime_ctx, status="pending_awaiting"):
            self.pending.pop(user_id, None)
            message_text = "待确认计划未能保存，本次没有执行任何业务操作；请稍后重试。"
            return {
                "success": False,
                "message": message_text,
                "response": message_text,
                "execution": self._no_write_execution(context),
                "data": {
                    "action": "workflow_persistence_failed",
                    "plan_id": plan.plan_id,
                    "execution_started": False,
                },
            }
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
    def _risk_rejection(
        code: str,
        reason: str,
        context: dict[str, Any] | None = None,
        *,
        continuation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        message = "计划未通过系统风险审核，本次没有执行任何业务操作。"
        # Only the verified durable continuation supplies identity, never client context.
        original = continuation["run"] if continuation else None
        return {
            "success": False,
            "execution_state": "blocked",
            **({"run_id": original.run_id, "agent_run_id": original.run_id} if original else {}),
            "message": message,
            "response": message,
            "execution": PlannedWorkflowDispatch._no_write_execution(context or {}),
            "data": {
                "text": message,
                "action": "workflow_risk_rejected",
                "error_code": code,
                "reason": str(reason or "")[:240],
                "execution_started": False,
            },
        }
