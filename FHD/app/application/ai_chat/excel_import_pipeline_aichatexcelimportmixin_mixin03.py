# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat.excel_import_pipeline")


class _AIChatExcelImportMixinPart03Mixin:
    @staticmethod
    def _attach_deterministic_workflow_trace(
        payload: dict[str, _facade().Any],
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, _facade().Any] | None,
        intent: str,
        file_context: dict[str, _facade().Any] | None = None,
    ) -> dict[str, _facade().Any]:
        try:
            from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("AgentRun 追踪模块不可用，跳过 deterministic workflow trace")
            return payload
        runtime_context = dict(context or {}) if isinstance(context, dict) else {}
        runtime_context["workflow_intent"] = intent
        runtime_context["workflow_trace_mode"] = "deterministic_shortcut"
        if isinstance(file_context, dict) and file_context:
            runtime_context["file_context"] = file_context
        return attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel="deterministic_workflow",
            intent=intent,
        )

    def _start_deterministic_import_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, _facade().Any] | None,
        file_context: dict[str, _facade().Any] | None,
        plan,
        thinking_steps: str,
    ) -> dict[str, _facade().Any]:
        from app.application.agent_orchestrator import AgentOrchestrator

        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["deterministic_workflow"] = True
        if isinstance(file_context, dict) and file_context:
            runtime_ctx["file_context"] = dict(file_context)
        agent_run = AgentOrchestrator().start_run_from_plan(
            user_id=user_id,
            message=message,
            plan=plan,
            runtime_context=runtime_ctx,
            auto_execute=True,
        )
        if agent_run.status != "waiting_user":
            return self._format_agent_run_response(
                plan, agent_run, thinking_steps=thinking_steps, user_message=str(message or "")
            )
        blocking_nodes = [step.node_id for step in agent_run.steps if step.status == "waiting_user"]
        artifact_payloads = [
            artifact.to_dict() for artifact in getattr(agent_run, "artifacts", []) or []
        ]
        self._pending_workflows[user_id] = {
            "plan": plan,
            "runtime_context": runtime_ctx,
            "pending_id": _facade().uuid.uuid4().hex,
            "agent_run_id": agent_run.run_id,
            "thinking_steps": thinking_steps,
            "approval_required": False,
            "approval_nodes": [],
        }
        todo_text = "\n".join(f"- {step}" for step in getattr(plan, "todo_steps", None) or [])
        response_text = f"我已生成导入工作流计划：\n{thinking_steps}\n\n{todo_text}\n\n检测到写库步骤（{', '.join(blocking_nodes) or 'import'}），回复「确认」继续执行，回复「取消」终止。"
        inner = {
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "thinking_steps": thinking_steps,
            "todo": plan.todo_steps,
            "artifact_count": len(artifact_payloads),
            "artifacts": artifact_payloads,
            "blocking_nodes": blocking_nodes,
            "reason": "导入会写入业务数据库，需确认后执行",
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
                "data": _facade()._enrich_confirmation_inner(
                    inner, action="workflow_confirmation_required"
                ),
            },
        }
