"""Extracted methods for an existing public service."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_mixin_methods


class AIChatAgentBridgeMixin:
    def _start_agentic_workflow_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        runtime_context: dict[str, Any],
    ):
        from app.application.agent_orchestrator.run_models import AgentRun
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository

        repository = get_agent_run_repository()
        run = AgentRun(
            user_id=str(user_id or ""),
            message=str(message or ""),
            status="running",
            plan_id=str(getattr(plan, "plan_id", "") or ""),
            intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
            metadata={
                "runtime_context": dict(runtime_context or {}),
                "trace_mode": "agentic_loop_bridge",
                "plan": {
                    "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                    "risk_level": str(getattr(plan, "risk_level", "") or ""),
                    "metadata": dict(getattr(plan, "metadata", {}) or {}),
                },
            },
        )
        run.add_event("run.created", "Agentic workflow run 已创建")
        run.add_event(
            "planner.completed",
            "Agentic workflow 计划已接管",
            {
                "plan_id": run.plan_id,
                "intent": run.intent,
                "source": "workflow_engine.agentic_loop",
            },
        )
        run.add_event(
            "agentic_loop.started",
            "Agentic workflow loop 开始执行",
            {"observed": True},
        )
        return repository.save(run)

    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        run_result,
        runtime_context: dict[str, Any],
        agent_run=None,
    ):
        from app.application.agent_orchestrator.run_models import (
            AgentRun,
            AgentStep,
            ToolCall,
            artifact_from_dict,
        )
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        repository = get_agent_run_repository()
        runtime_ctx = dict(runtime_context or {})
        run = agent_run
        if run is None:
            run = AgentRun(
                user_id=str(user_id or ""),
                message=str(message or ""),
                status="running",
                plan_id=str(getattr(plan, "plan_id", "") or ""),
                intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
                metadata={
                    "runtime_context": dict(runtime_ctx),
                    "trace_mode": "agentic_loop_bridge",
                    "plan": {
                        "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                        "risk_level": str(getattr(plan, "risk_level", "") or ""),
                        "metadata": dict(getattr(plan, "metadata", {}) or {}),
                    },
                },
            )
            run.add_event("run.created", "Agentic workflow run 已创建")
            run.add_event(
                "planner.completed",
                "Agentic workflow 计划已接管",
                {
                    "plan_id": run.plan_id,
                    "intent": run.intent,
                    "source": "workflow_engine.agentic_loop",
                },
            )
            run.add_event(
                "agentic_loop.started",
                "Agentic workflow loop 开始执行",
                {"observed": True},
            )
        run.metadata["runtime_context"] = dict(runtime_ctx)
        run.metadata["trace_mode"] = "agentic_loop_bridge"
        run.add_event(
            "agentic_loop.completed",
            str(getattr(run_result, "message", "") or "AgenticLoop 已完成"),
            {"observed": True},
        )

        node_outputs: dict[str, Any] = {}
        for result in getattr(run_result, "node_results", []) or []:
            spec = get_tool_action_spec(result.tool_id, result.action)
            status = "completed" if bool(getattr(result, "success", False)) else "failed"
            step = AgentStep(
                node_id=str(result.node_id or f"agent_{result.tool_id}_{result.action}"),
                tool_id=str(result.tool_id or ""),
                action=str(getattr(spec, "action", "") or result.action or ""),
                params=dict(getattr(result, "params", {}) or {}),
                risk=str(getattr(spec, "risk", "") or "medium"),
                idempotent=bool(getattr(spec, "idempotent", False)),
                description="agentic loop observed tool execution",
                status=status,
                output=dict(getattr(result, "output", {}) or {}),
                error=str(getattr(result, "error", "") or ""),
                started_at=str(getattr(result, "started_at", "") or ""),
                finished_at=str(getattr(result, "finished_at", "") or ""),
                duration_ms=int(getattr(result, "duration_ms", 0) or 0),
            )
            if status == "failed" and not step.error:
                step.error = self._workflow_output_message(step.output) or "tool failed"
            call = ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params or {}),
                status="completed" if status == "completed" else "failed",
                output=dict(step.output or {}),
                error=step.error,
                cost_units=int(getattr(spec, "cost_units", 0) or 0),
                permission=str(getattr(spec, "permission", "") or ""),
                started_at=step.started_at or "",
                finished_at=step.finished_at or "",
                duration_ms=step.duration_ms,
                metadata={
                    "observed": True,
                    "trace_mode": "agentic_loop_bridge",
                    "retryable": bool(getattr(result, "retryable", True)),
                    "retries": int(getattr(result, "retries", 0) or 0),
                    "recovery_hint": str(getattr(result, "recovery_hint", "") or ""),
                },
            )
            run.steps.append(step)
            run.tool_calls.append(call)
            node_outputs[step.node_id] = step.output
            run.add_event(
                "tool.started",
                f"观察到 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "cost_units": call.cost_units,
                    "permission": call.permission,
                    "observed": True,
                },
            )
            run.add_event(
                "tool.completed" if status == "completed" else "tool.failed",
                f"记录 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "duration_ms": step.duration_ms,
                    "cost_units": call.cost_units,
                    "observed": True,
                    "error": step.error,
                },
            )
            for artifact_payload in self._iter_agentic_artifact_payloads(step.output):
                artifact = artifact_from_dict(artifact_payload)
                if not artifact.artifact_type:
                    continue
                artifact.source = artifact.source or f"{step.tool_id}.{step.action}"
                artifact.metadata = {
                    **dict(artifact.metadata or {}),
                    "step_id": step.step_id,
                    "call_id": call.call_id,
                    "trace_mode": "agentic_loop_bridge",
                }
                run.artifacts.append(artifact)
                run.add_event(
                    "artifact.attached",
                    f"Artifact 已附加: {artifact.artifact_type}",
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "name": artifact.name,
                        "source": artifact.source,
                    },
                )

        cost_units_total = sum(int(call.cost_units or 0) for call in run.tool_calls)
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = cost_units_total
        run.metadata["artifact_count"] = len(run.artifacts)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": cost_units_total,
            "workflow_result": {
                "success": bool(getattr(run_result, "success", False)),
                "message": str(getattr(run_result, "message", "") or ""),
                "workflow_status": dict(
                    (getattr(run_result, "final_context", {}) or {}).get("workflow_status") or {}
                ),
            },
        }
        run.status = "completed" if bool(getattr(run_result, "success", False)) else "failed"
        if run.status == "failed":
            run.error = str(getattr(run_result, "message", "") or "Agentic workflow failed")
            run.add_event("run.failed", run.error, run.final_output)
        else:
            run.add_event("run.completed", "Agentic workflow run 执行完成", run.final_output)
        return repository.save(run)

    @staticmethod
    def _iter_agentic_artifact_payloads(output: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(output, dict):
            return []
        artifacts = output.get("artifacts")
        if artifacts is None:
            artifacts = output.get("artifact")
        if isinstance(artifacts, dict):
            return [artifacts]
        if isinstance(artifacts, list):
            return [item for item in artifacts if isinstance(item, dict)]
        return []

    @staticmethod
    def _agent_plan_can_auto_execute(plan) -> bool:
        nodes = getattr(plan, "nodes", None)
        if not isinstance(nodes, (list, tuple)) or not nodes:
            return False
        try:
            from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        except RECOVERABLE_ERRORS:
            return False
        for node in nodes:
            spec = get_tool_action_spec(getattr(node, "tool_id", ""), getattr(node, "action", ""))
            risk = str(getattr(spec, "risk", "") or getattr(node, "risk", "") or "").lower()
            idempotent = bool(getattr(spec, "idempotent", getattr(node, "idempotent", False)))
            if risk != "low" or not idempotent:
                return False
        return True

    def _dispatch_workflow_tool(
        self, tool_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool

            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except RECOVERABLE_ERRORS as err:
            logger.error(
                "workflow 工具调度失败 tool=%s action=%s err=%s",
                tool_id,
                action,
                err,
                exc_info=True,
            )
            return {"success": False, "message": str(err)}

    def _handle_confirmation_flow(
        self, user_id: str, message: str, file_context: dict[str, Any] | None
    ) -> None:
        """处理确认流程"""
        if not file_context:
            return

        if message not in ("是", "好的", "确认", "yes", "ok", "好"):
            return

        saved_name = file_context.get("saved_name")
        unit_name = file_context.get("unit_name_guess") or file_context.get("unit_name", "")
        suggested_use = file_context.get("suggested_use", "")

        if saved_name and suggested_use == "unit_products_db" and unit_name:
            self.ai_service.set_pending_confirmation(
                user_id,
                {
                    "type": "import_unit_products",
                    "tool_key": "sqlite_import_unit_products",
                    "params": {
                        "saved_name": saved_name,
                        "unit_name": unit_name,
                    },
                    "description": f"导入 {unit_name} 的产品",
                },
            )
            logger.info("用户 %s 确认导入文件：%s -> %s", user_id, saved_name, unit_name)


sync_mixin_methods(
    AIChatAgentBridgeMixin,
    target=globals(),
    source_module="app.application.ai_chat_app_service",
    method_names=(
        "_start_agentic_workflow_agent_run",
        "_bridge_agentic_workflow_result_to_agent_run",
        "_iter_agentic_artifact_payloads",
        "_agent_plan_can_auto_execute",
        "_dispatch_workflow_tool",
        "_handle_confirmation_flow",
    ),
)
