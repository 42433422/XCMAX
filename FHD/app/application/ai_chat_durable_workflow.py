"""Extracted methods for an existing public service."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_mixin_methods


class AIChatDurableWorkflowMixin:
    @staticmethod
    def _should_background_agent_run(
        plan: Any,
        runtime_context: dict[str, Any] | None,
        message: str,
    ) -> bool:
        """Schedule only work that is plausibly long-running.

        Single-record queries and CRUD stay synchronous so the user receives
        the confirmation/result in the current chat turn. Batch, import,
        export, synchronization and explicitly requested background work can
        continue through the durable Agent runtime.
        """

        context = dict(runtime_context or {})
        explicit = context.get("background_execution")
        if isinstance(explicit, bool):
            return explicit

        text = str(message or "").lower()
        if any(
            marker in text
            for marker in (
                "后台运行",
                "后台执行",
                "异步执行",
                "长任务",
                "持续运行",
                "全部文件",
                "所有文件",
                "批量",
                "全量",
            )
        ):
            return True

        nodes = list(getattr(plan, "nodes", None) or [])
        if len(nodes) >= 3:
            return True
        long_actions = {
            "batch_create",
            "batch_delete",
            "import",
            "export",
            "sync",
            "crawl",
            "index",
            "train",
            "evaluate",
        }
        return any(
            str(getattr(node, "action", "") or "").strip().lower() in long_actions for node in nodes
        )

    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_ctx: dict[str, Any] = {"user_id": user_id, "message": message}
        if isinstance(context, dict):
            for key in ("ui_surface", "intent_channel", "tool_execution_profile"):
                if key in context and context[key] is not None:
                    runtime_ctx[key] = context[key]
            # 透传 Excel 分析上下文，支持自然语言按 sheet 入模板库
            for key in ("excel_analysis", "last_excel_analysis_context"):
                if key in context and isinstance(context[key], dict):
                    runtime_ctx[key] = context[key]
        return runtime_ctx

    @staticmethod
    def _workflow_confirmation_request(
        context: dict[str, Any] | None,
    ) -> dict[str, str] | None:
        if not isinstance(context, dict):
            return None
        raw = context.get("workflow_confirmation")
        if not isinstance(raw, dict):
            return None
        action = str(raw.get("action") or "").strip().lower()
        run_id = str(raw.get("agent_run_id") or raw.get("run_id") or "").strip()
        if action not in {"confirm", "cancel", "submit_approval"} or not run_id:
            return None
        return {
            "action": action,
            "agent_run_id": run_id,
            "plan_id": str(raw.get("plan_id") or "").strip(),
            "approved_step_id": str(
                raw.get("approved_step_id") or raw.get("node_id") or ""
            ).strip(),
        }

    @staticmethod
    def _plan_from_agent_run(agent_run: Any) -> Any:
        from app.application.workflow.types import PlanGraph, WorkflowNode

        plan_meta = (
            agent_run.metadata.get("plan")
            if isinstance(getattr(agent_run, "metadata", None), dict)
            else {}
        )
        plan_meta = plan_meta if isinstance(plan_meta, dict) else {}
        raw_risk = str(plan_meta.get("risk_level") or "low").strip().lower()
        risk_level = raw_risk if raw_risk in {"low", "medium", "high"} else "low"
        nodes = []
        for step in getattr(agent_run, "steps", []) or []:
            step_risk = str(getattr(step, "risk", "") or "low").strip().lower()
            nodes.append(
                WorkflowNode(
                    node_id=str(getattr(step, "node_id", "") or ""),
                    tool_id=str(getattr(step, "tool_id", "") or ""),
                    action=str(getattr(step, "action", "") or ""),
                    params=dict(getattr(step, "params", None) or {}),
                    risk=step_risk if step_risk in {"low", "medium", "high"} else "low",
                    idempotent=bool(getattr(step, "idempotent", False)),
                    description=str(getattr(step, "description", "") or ""),
                    depends_on=list(getattr(step, "depends_on", None) or []),
                )
            )
        return PlanGraph(
            plan_id=str(getattr(agent_run, "plan_id", "") or ""),
            intent=str(getattr(agent_run, "intent", "") or ""),
            todo_steps=list(plan_meta.get("todo_steps") or []),
            nodes=nodes,
            risk_level=risk_level,
            metadata=dict(plan_meta.get("metadata") or {}),
        )

    def _handle_durable_workflow_decision(
        self,
        *,
        user_id: str,
        confirmation: dict[str, str] | None,
        action: str,
        authenticated_owner_user_id: int | None,
    ) -> dict[str, Any]:
        from app.application.agent_orchestrator import (
            AgentOrchestrator,
            get_agent_run_runtime,
        )

        orchestrator = AgentOrchestrator()
        requested_action = str(action or "").strip().lower()
        run_id = str((confirmation or {}).get("agent_run_id") or "").strip()
        if not run_id:
            waiting_runs = [
                run
                for run in orchestrator.list_runs(user_id=user_id, limit=20)
                if run.status == "waiting_user"
            ]
            if len(waiting_runs) != 1:
                response = "找不到唯一的待确认任务。请回到对应任务卡片点击“确认执行”或“取消”。"
                return {
                    "success": False,
                    "message": "待确认任务不唯一或不存在",
                    "response": response,
                    "data": {
                        "text": response,
                        "action": "workflow_confirmation_missing",
                        "data": {"waiting_run_count": len(waiting_runs)},
                    },
                }
            run_id = waiting_runs[0].run_id

        agent_run = orchestrator.get_run(run_id)
        if agent_run is None:
            response = "待确认任务不存在或已清理，请重新发起操作。"
            return {
                "success": False,
                "message": "agent run 不存在",
                "response": response,
                "data": {
                    "text": response,
                    "action": "workflow_confirmation_invalid",
                    "data": {"agent_run_id": run_id},
                },
            }

        if str(agent_run.user_id or "") != str(user_id or ""):
            response = "该待确认任务不属于当前会话，已拒绝执行。"
            return {
                "success": False,
                "message": "agent run 归属校验失败",
                "response": response,
                "data": {
                    "text": response,
                    "action": "workflow_confirmation_forbidden",
                    "data": {"agent_run_id": run_id},
                },
            }

        stored_runtime = (
            agent_run.metadata.get("runtime_context")
            if isinstance(agent_run.metadata, dict)
            else {}
        )
        stored_runtime = stored_runtime if isinstance(stored_runtime, dict) else {}
        stored_owner = stored_runtime.get("authenticated_owner_user_id")
        if (
            stored_owner is not None
            and authenticated_owner_user_id is not None
            and str(stored_owner) != str(authenticated_owner_user_id)
        ):
            response = "该待确认任务不属于当前登录账号，已拒绝执行。"
            return {
                "success": False,
                "message": "登录账号归属校验失败",
                "response": response,
                "data": {
                    "text": response,
                    "action": "workflow_confirmation_forbidden",
                    "data": {"agent_run_id": run_id},
                },
            }

        expected_plan_id = str((confirmation or {}).get("plan_id") or "").strip()
        if expected_plan_id and expected_plan_id != str(agent_run.plan_id or ""):
            response = "确认卡片与待执行计划不一致，已拒绝执行。"
            return {
                "success": False,
                "message": "plan_id 校验失败",
                "response": response,
                "data": {
                    "text": response,
                    "action": "workflow_confirmation_invalid",
                    "data": {"agent_run_id": run_id},
                },
            }

        if agent_run.status != "waiting_user":
            response = f"任务当前状态为 {agent_run.status}，不能重复确认。"
            return {
                "success": False,
                "message": "agent run 状态不允许确认",
                "response": response,
                "data": {
                    "text": response,
                    "action": "workflow_confirmation_conflict",
                    "data": {
                        "agent_run_id": run_id,
                        "agent_status": agent_run.status,
                    },
                },
            }

        if requested_action == "submit_approval":
            plan = self._plan_from_agent_run(agent_run)
            approval_nodes = self.approval_service.get_approval_required_nodes(plan)
            if not approval_nodes:
                response = "该任务没有可提交的审批步骤，已拒绝执行。"
                return {
                    "success": False,
                    "message": "审批步骤不存在",
                    "response": response,
                    "data": {
                        "text": response,
                        "action": "workflow_confirmation_invalid",
                        "data": {"agent_run_id": run_id},
                    },
                }

            requested_step = str((confirmation or {}).get("approved_step_id") or "").strip()
            if requested_step and requested_step not in {node.node_id for node in approval_nodes}:
                response = "审批卡片与待审批步骤不一致，已拒绝提交。"
                return {
                    "success": False,
                    "message": "审批步骤校验失败",
                    "response": response,
                    "data": {
                        "text": response,
                        "action": "workflow_confirmation_invalid",
                        "data": {"agent_run_id": run_id},
                    },
                }

            approval_runtime = dict(stored_runtime)
            approval_runtime["agent_run_id"] = run_id
            approval_runtime["approval_submitted_by"] = user_id
            request_ids = []
            for node in approval_nodes:
                node_runtime = dict(approval_runtime)
                node_runtime["approval_node_id"] = node.node_id
                request = self.approval_service.create_approval_request(
                    plan_id=plan.plan_id,
                    node=node,
                    runtime_context=node_runtime,
                    plan=plan,
                )
                request_ids.append(request.request_id)

            pending = self._pending_workflows.get(user_id)
            pending_plan_id = str(getattr((pending or {}).get("plan"), "plan_id", "") or "")
            if pending_plan_id == plan.plan_id:
                self._pending_workflows.pop(user_id, None)

            response = (
                f"已提交 {len(request_ids)} 个审批请求。审批通过后，"
                "系统将恢复当前任务并只执行这张卡片对应的步骤。"
            )
            return {
                "success": True,
                "message": "审批请求已提交",
                "response": response,
                "run_id": run_id,
                "agent_run_id": run_id,
                "data": {
                    "text": response,
                    "action": "approval_submitted",
                    "run_id": run_id,
                    "agent_run_id": run_id,
                    "data": {
                        "run_id": run_id,
                        "agent_run_id": run_id,
                        "plan_id": plan.plan_id,
                        "approval_request_ids": request_ids,
                        "agent_status": agent_run.status,
                    },
                },
            }

        if requested_action == "cancel":
            cancelled = get_agent_run_runtime().cancel(run_id, requested_by=user_id)
            response = "已取消本次工作流执行。"
            return {
                "success": bool(cancelled and cancelled.status == "cancelled"),
                "message": "处理完成",
                "response": response,
                "run_id": run_id,
                "agent_run_id": run_id,
                "data": {
                    "text": response,
                    "action": "workflow_cancelled",
                    "run_id": run_id,
                    "agent_run_id": run_id,
                    "data": {
                        "run_id": run_id,
                        "agent_run_id": run_id,
                        "agent_status": getattr(cancelled, "status", ""),
                    },
                },
            }

        runtime_ctx = dict(stored_runtime)
        if authenticated_owner_user_id is not None:
            runtime_ctx["authenticated_owner_user_id"] = int(authenticated_owner_user_id)
        background_execution = bool(runtime_ctx.get("background_execution"))
        continued = orchestrator.continue_run(
            run_id,
            approved_by=user_id,
            approved_step_id=str((confirmation or {}).get("approved_step_id") or "").strip(),
            runtime_context=runtime_ctx,
            auto_execute=not background_execution,
        )
        if background_execution and continued is not None and continued.status == "queued":
            continued = get_agent_run_runtime().submit(run_id) or continued
        if continued is None:
            return {
                "success": False,
                "message": "任务恢复失败",
                "response": "任务恢复失败，请重新发起操作。",
            }
        return self._format_agent_run_response(
            self._plan_from_agent_run(continued),
            continued,
            thinking_steps="已核对确认卡片与持久化任务，按原计划继续执行。",
            user_message=str(continued.message or ""),
        )


sync_mixin_methods(
    AIChatDurableWorkflowMixin,
    target=globals(),
    source_module="app.application.ai_chat_app_service",
    method_names=(
        "_should_background_agent_run",
        "_merge_tool_runtime_context",
        "_workflow_confirmation_request",
        "_plan_from_agent_run",
        "_handle_durable_workflow_decision",
    ),
)
