"""Dispatch planned chat workflows through explicit risk and approval boundaries."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.application.ai_chat.excel_import_policy import _enrich_confirmation_inner
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import resolve_fhd_repo_root

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow.risk_gate import HybridRiskGate
    from app.application.workflow.types import PlanGraph, WorkflowRunResult

logger = logging.getLogger(__name__)


def _log_price_list_result(result: dict[str, Any]) -> None:
    products = result.get("products")
    product_count = len(products) if isinstance(products, list) else 0
    logger.info(
        "价格表生成已完成 success=%s product_count=%s",
        bool(result.get("success")),
        product_count,
    )


class WorkflowDispatchCallbacks(Protocol):
    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        run_result: WorkflowRunResult,
        runtime_context: dict[str, Any],
        agent_run: AgentRun | None = None,
    ) -> AgentRun: ...
    def _build_response(
        self, ai_result: dict[str, Any], source: str | None, original_message: str = ""
    ) -> dict[str, Any]: ...
    def _build_workflow_thinking_steps(self, plan: PlanGraph, decision_reason: str) -> str: ...
    def _format_agent_run_response(
        self, plan: PlanGraph, agent_run: AgentRun, thinking_steps: str = "", user_message: str = ""
    ) -> dict[str, Any]: ...
    def _format_workflow_run_response(
        self,
        plan: PlanGraph,
        run_result: WorkflowRunResult,
        thinking_steps: str = "",
        user_message: str = "",
        state_updates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str, message: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...
    def _open_clarification_gate(
        self,
        *,
        user_id: str,
        plan: PlanGraph,
        tool_registry: dict[str, Any],
        runtime_context: dict[str, Any],
        thinking_steps: str,
        message: str,
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
    def _run_workflow_with_state_updates(
        self,
        *,
        plan: PlanGraph,
        runtime_context: dict[str, Any],
        max_retries: int = 1,
        resume: bool = False,
        **kwargs: Any,
    ) -> tuple[WorkflowRunResult, list[dict[str, Any]]]: ...
    def _start_agentic_workflow_agent_run(
        self, *, user_id: str, message: str, plan: PlanGraph, runtime_context: dict[str, Any]
    ) -> AgentRun: ...
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

    def handle(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        text: str,
        explicit_workflow_tool_intent: bool,
    ) -> dict[str, Any] | None:
        from app.application.normal_chat_dispatch import (
            build_customers_query_response_dict,
            build_inventory_alert_response_dict,
            build_label_print_response_dict,
            build_product_query_response_dict,
            resolve_tool_execution_profile,
            route_normal_mode_message,
            run_normal_slot_shipment_preview,
        )
        from app.application.workflow.planner import _onboarding_first_order_slots

        profile = resolve_tool_execution_profile(context if isinstance(context, dict) else {})
        # The seeded first order has an existing read/read/write plan. Parsing
        # its whole instruction as a single shipment would discard the reads
        # and the user's explicit confirmation boundary before planning.
        has_onboarding_plan = _onboarding_first_order_slots(text) is not None
        if (
            profile == "normal"
            and not explicit_workflow_tool_intent
            and not has_onboarding_plan
            and user_id not in self.pending
        ):
            rr = route_normal_mode_message(text)
            if rr.get("intent") == "product_query":
                pq = build_product_query_response_dict(rr)
                if pq:
                    return pq
            if rr.get("intent") == "shipment":
                ship = run_normal_slot_shipment_preview(text)
                if ship.get("success"):
                    ship.pop("normal_slot_dispatch", None)
                    return ship
            if rr.get("intent") == "customers_query":
                cq = build_customers_query_response_dict(rr)
                if cq:
                    return cq
            if rr.get("intent") == "inventory_alert":
                ia = build_inventory_alert_response_dict(rr)
                if ia:
                    return ia
            if rr.get("intent") == "label_print":
                lp = build_label_print_response_dict(rr)
                if lp:
                    return lp
            if rr.get("intent") == "price_list":
                customer_name_match = re.search(
                    "([^\\s，,。]{2,}(?:有限公司|集团有限公司|实业有限公司|公司\\s|单位|客户|厂|店))",
                    text,
                )
                keyword_match = re.search("[的的]\\s*([^\\s，,。]+)", text)
                slots = {}
                if customer_name_match:
                    slots["customer_name"] = customer_name_match.group(1)
                if keyword_match:
                    slots["keyword"] = keyword_match.group(1)
                if not slots.get("customer_name"):
                    return {
                        "success": False,
                        "message": "缺少客户名称",
                        "response": "请告诉我您要生成哪家客户的价格表？例如：「打印某某公司的价格表」",
                    }
                try:
                    fhd_root = resolve_fhd_repo_root(anchor=Path(__file__).resolve())
                    from app.application.tools import handle_price_list_export

                    logger.info("价格表生成 - FHD根目录: %s", fhd_root)
                    result = handle_price_list_export(
                        {
                            "customer_name": slots.get("customer_name", ""),
                            "keyword": slots.get("keyword"),
                            "export_date": None,
                        },
                        workspace_root=str(fhd_root) if fhd_root else None,
                    )
                    _log_price_list_result(result)
                    if result.get("success"):
                        product_count = len(result.get("products", []))
                        file_path = result.get("file_path", "")
                        filename = (
                            file_path.split("/")[-1].split("\\")[-1] if file_path else "价格表.docx"
                        )
                        return {
                            "success": True,
                            "message": result.get("message", "价格表已生成"),
                            "response": f"好的，价格表已生成成功！\n\n{result.get('message', '')}\n\n📄 文件名：{filename}\n💡 已在右侧任务面板中添加下载和打印按钮。",
                            "data": {
                                "file_path": file_path,
                                "download_url": result.get("download_url"),
                                "filename": filename,
                                "product_count": product_count,
                                "intent": "price_list",
                                "action": "tool_call",
                                "tool_key": "price_list",
                            },
                        }
                    else:
                        return {
                            "success": False,
                            "message": result.get("error", "价格表生成失败"),
                            "response": f"抱歉，价格表生成失败：{result.get('error', '未知错误')}",
                        }
                except RECOVERABLE_ERRORS:
                    logger.exception("价格表生成异常")
                    return {
                        "success": False,
                        "message": "价格表生成异常",
                        "response": "抱歉，价格表生成时出现错误，请稍后重试。",
                    }
        pending = self.pending.get(user_id) or {}
        if (
            pending.get("kind") == "clarification"
            and (pending.get("clarification") or {}).get("reason") == "missing_required"
        ):
            from app.application.shipment_inputs import shipment_call_payload

            target = next(
                (n for n in pending["plan"].nodes if n.node_id == pending.get("target_node_id")),
                None,
            )
            if (
                target
                and (
                    shipment_call_payload(target.tool_id, target.action, target.params) is not None
                    or (target.tool_id == "sales" and target.action == "create_order")
                )
                and text.lower() not in {"取消", "否", "不要", "停止", "no"}
            ):
                message = text = (
                    f"{message}\n原始业务请求：{pending.get('runtime_context', {}).get('message', '')}"
                )
                self.pending.pop(user_id, None)
        pending_handled, pending_result = self.callbacks._resume_pending_dynamic_workflow(
            user_id, message, text, context
        )
        if pending_handled:
            return pending_result
        if profile == "pro_default" and not has_onboarding_plan:
            rr_pro_ship = route_normal_mode_message(text)
            if rr_pro_ship.get("intent") == "shipment":
                try:
                    from app.application.facades.tools_facade import _parse_order_text

                    parsed_quick = _parse_order_text(text)
                except RECOVERABLE_ERRORS:
                    parsed_quick = {"success": False}
                if parsed_quick.get("success"):
                    quick_ai = {
                        "text": "已识别订单，正在生成发货单…",
                        "action": "tool_call",
                        "data": {
                            "tool_key": "shipment_generate",
                            "intent": "shipment_generate",
                            "slots": {
                                "unit_name": (parsed_quick.get("unit_name") or "").strip(),
                                "products": parsed_quick.get("products") or [],
                            },
                            "hints": [],
                            "habit_suggestion": None,
                        },
                    }
                    return self.callbacks._build_response(quick_ai, source, text)
                return None
        from app.application.facades.tools_facade import get_workflow_tool_registry

        tool_registry = get_workflow_tool_registry()
        planner_message = message
        from app.domain.services.conversation.chat_tool_intent import (
            references_recent_business_record,
        )

        if references_recent_business_record(str(message or "")):
            from app.services.tools_workflow_registered import get_recent_business_db_target

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
        from app.application.workflow.types import PlanGraph

        if not isinstance(plan, PlanGraph):
            logger.warning("工作流规划器返回无效计划类型: %s", type(plan).__name__)
            return None
        decision = self.risk_gate.evaluate(plan=plan, context=context)
        runtime_ctx = self.callbacks._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["dynamic_workflow"] = True
        thinking_steps = self.callbacks._build_workflow_thinking_steps(
            plan=plan, decision_reason=decision.reason
        )
        if user_id not in self.pending:
            clarify_result = self.callbacks._open_clarification_gate(
                user_id=user_id,
                plan=plan,
                tool_registry=tool_registry,
                runtime_context=runtime_ctx,
                thinking_steps=thinking_steps,
                message=message,
            )
            if clarify_result is not None:
                return clarify_result
        approval_required_nodes = self.approval.get_approval_required_nodes(plan)
        has_approval_requirement = bool(approval_required_nodes)
        approval_info = ""
        if has_approval_requirement:
            approval_node_names = [f"{n.tool_id}.{n.action}" for n in approval_required_nodes]
            approval_info = "\n以下操作需要审批后执行：" + "、".join(approval_node_names)
        use_agentic = bool((runtime_ctx.get("excel_analysis") or {}).get("file_path"))
        if not has_approval_requirement and (not use_agentic):
            from app.application.agent_orchestrator import AgentOrchestrator

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
            blocking_nodes = [
                step.node_id
                for step in getattr(agent_run, "steps", []) or []
                if step.status == "waiting_user"
            ]
            self.pending[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run.run_id,
                "thinking_steps": thinking_steps,
                "approval_required": False,
                "approval_nodes": [],
            }
            self.callbacks._persist_plan_state(plan, runtime_ctx, status="pending_awaiting")
            todo_text = "\n".join(f"- {step}" for step in plan.todo_steps or [])
            reason = decision.reason or "工具策略要求用户确认"
            response_text = f"我已根据语义生成动态工作流计划：\n{thinking_steps}\n\n{todo_text}\n\n检测到需确认步骤（{', '.join(blocking_nodes) or 'workflow'}），回复「确认」继续执行，回复「取消」终止。"
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
        if decision.requires_confirmation and (not has_approval_requirement):
            from app.application.agent_orchestrator import AgentOrchestrator

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
            agent_run_id = agent_run.run_id
        if decision.requires_confirmation or has_approval_requirement:
            self.pending[user_id] = {
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
            self.callbacks._persist_plan_state(plan, runtime_ctx, status="pending_awaiting")
            todo_text = "\n".join(f"- {step}" for step in plan.todo_steps or [])
            response_text = f"我已根据语义生成动态工作流计划：\n{thinking_steps}\n\n{todo_text}\n\n检测到中高风险步骤（{', '.join(decision.blocking_nodes or [])}），回复「确认」继续执行，回复「取消」终止。{(approval_info if has_approval_requirement else '')}"
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
            confirmation_payload: dict[str, Any] = {
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
                payload_data = confirmation_payload["data"]
                assert isinstance(payload_data, dict)
                confirmation_data = payload_data["data"]
                assert isinstance(confirmation_data, dict)
                confirmation_payload["run_id"] = agent_run_id
                confirmation_payload["agent_run_id"] = agent_run_id
                payload_data["run_id"] = agent_run_id
                payload_data["agent_run_id"] = agent_run_id
                confirmation_data["run_id"] = agent_run_id
                confirmation_data["agent_run_id"] = agent_run_id
            return confirmation_payload
        agentic_pre_run = None
        if use_agentic:
            try:
                agentic_pre_run = self.callbacks._start_agentic_workflow_agent_run(
                    user_id=user_id, message=message, plan=plan, runtime_context=runtime_ctx
                )
                runtime_ctx["run_id"] = agentic_pre_run.run_id
                runtime_ctx["agent_run_id"] = agentic_pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("Agentic workflow AgentRun pre-create skipped", exc_info=True)
        run_result, state_updates = self.callbacks._run_workflow_with_state_updates(
            plan=plan,
            runtime_context=runtime_ctx,
            max_retries=1,
            agentic_loop=use_agentic,
            tool_registry=tool_registry,
            user_id=user_id,
        )
        if use_agentic:
            agent_run = self.callbacks._bridge_agentic_workflow_result_to_agent_run(
                user_id=user_id,
                message=message,
                plan=plan,
                run_result=run_result,
                runtime_context=runtime_ctx,
                agent_run=agentic_pre_run,
            )
            return self.callbacks._format_agent_run_response(
                plan, agent_run, thinking_steps=thinking_steps, user_message=str(message or "")
            )
        return self.callbacks._format_workflow_run_response(
            plan,
            run_result,
            thinking_steps=thinking_steps,
            user_message=str(message or ""),
            state_updates=state_updates,
        )
