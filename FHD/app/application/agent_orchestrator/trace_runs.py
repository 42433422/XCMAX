"""Lifecycle of observed chat runs, with explicit persistence, recording and plan-execution ports."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

from .run_models import AgentRun
from .run_repository import AgentRunRepository
from .task_context import apply_task_context
from .trace_payloads import (
    _attach_run_id,
    _extract_legacy_tool_records,
    _payload_data,
    _payload_error_message,
    _payload_status,
    _resolved_user_id,
    _trace_safe_value,
)
from .trace_recording import TraceRecorder
from .trace_tools import _extract_low_risk_tool_call


class ExecuteObservedPlan(Protocol):
    def __call__(
        self,
        *,
        repository: AgentRunRepository,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: dict[str, Any],
        auto_execute: bool,
    ) -> AgentRun: ...


class TraceRunService:
    def __init__(
        self,
        repository: AgentRunRepository,
        recording: TraceRecorder,
        execute_plan: ExecuteObservedPlan,
    ) -> None:
        self.repository = repository
        self.recording = recording
        self.execute_plan = execute_plan

    def start(
        self,
        *,
        message: str,
        runtime_context: dict[str, Any] | None = None,
        user_id: str | None = None,
        source: str | None = None,
        channel: str = "compat_chat",
        intent: str = "legacy_chat_adapter",
    ) -> AgentRun:
        resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
        run = AgentRun(
            user_id=resolved_user_id,
            message=str(message or ""),
            status="running",
            intent=str(intent or "legacy_chat_adapter").strip() or "legacy_chat_adapter",
            metadata={
                "channel": channel,
                "source": str(source or "").strip(),
                "trace_mode": "legacy_planner_run",
                "runtime_context": _trace_safe_value(runtime_context or {}),
            },
        )
        apply_task_context(run, runtime_context)
        run.add_event(
            "run.created",
            "智能任务已创建",
            {"channel": channel, "source": str(source or "").strip()},
        )
        run.add_event(
            "planner.started",
            "正在生成执行计划",
            {"channel": channel, "source": str(source or "").strip()},
        )
        return self.repository.save(run)

    def create_observed_tools(
        self,
        payload: dict[str, Any],
        *,
        message: str,
        runtime_context: dict[str, Any] | None,
        user_id: str | None,
        source: str | None,
        channel: str,
        intent: str = "legacy_tool_chain",
    ) -> AgentRun | None:
        records = _extract_legacy_tool_records(payload)
        if not records:
            return None
        resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
        status = _payload_status(payload)
        run = AgentRun(
            user_id=resolved_user_id,
            message=str(message or ""),
            status=status,
            intent=str(intent or "legacy_tool_chain").strip() or "legacy_tool_chain",
            metadata={
                "channel": channel,
                "source": str(source or "").strip(),
                "trace_mode": "legacy_tool_records",
                "runtime_context": _trace_safe_value(runtime_context or {}),
            },
            final_output={"chat_payload": _trace_safe_value(payload)},
        )
        apply_task_context(run, runtime_context)
        run.add_event(
            "run.created",
            "Legacy planner 工具调用已进入 AgentRun 追踪",
            {"channel": channel, "source": str(source or "").strip(), "observed": True},
        )
        (node_outputs, total_cost) = self.recording.observe_tools(run, records)
        self.recording.enrich(run, payload, query=message)
        if (
            run.steps
            and status == "completed"
            and any(step.status == "failed" for step in run.steps)
        ):
            run.status = "failed"
            run.error = "legacy planner tool failed"
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = total_cost
        run.final_output = {
            "chat_payload": _trace_safe_value(payload),
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "cost_units_total": total_cost,
        }
        self.recording.finalize(run)
        if run.status == "failed":
            run.add_event(
                "run.failed", run.error or "Legacy planner 工具调用失败", run.final_output
            )
        elif run.status == "waiting_user":
            run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
        else:
            run.add_event("run.completed", "Legacy planner 工具调用追踪完成", run.final_output)
        return self.repository.save(run)

    def create_tool_plan(
        self,
        payload: dict[str, Any],
        *,
        message: str,
        runtime_context: dict[str, Any] | None,
        user_id: str | None,
        source: str | None,
        channel: str,
    ) -> AgentRun | None:
        extracted = _extract_low_risk_tool_call(payload)
        if extracted is None:
            return None
        (tool_id, action, params, raw_tool_call) = extracted
        resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
        runtime = dict(runtime_context or {})
        runtime.update(
            {
                "channel": channel,
                "source": str(source or "").strip(),
                "trace_mode": "orchestrated_tool_call",
                "legacy_tool_call": _trace_safe_value(raw_tool_call),
            }
        )
        plan = PlanGraph(
            plan_id=f"compat-tool-{uuid4().hex[:12]}",
            intent=f"{tool_id}_{action}",
            todo_steps=[f"执行兼容工具 {tool_id}.{action}"],
            nodes=[
                WorkflowNode(
                    node_id=f"{tool_id}_{action}",
                    tool_id=tool_id,
                    action=action,
                    params=params,
                    risk="low",
                    idempotent=True,
                    description=f"兼容 toolCall 接管: {tool_id}.{action}",
                )
            ],
            risk_level="low",
            metadata={
                "channel": channel,
                "source": str(source or "").strip(),
                "trace_mode": "orchestrated_tool_call",
                "legacy_tool_call": _trace_safe_value(raw_tool_call),
            },
        )
        run = self.execute_plan(
            repository=self.repository,
            user_id=resolved_user_id,
            message=str(message or ""),
            plan=plan,
            runtime_context=runtime,
            auto_execute=True,
        )
        run.metadata["channel"] = channel
        run.metadata["source"] = str(source or "").strip()
        run.metadata["trace_mode"] = "orchestrated_tool_call"
        self.recording.enrich(run, payload, query=message)
        self.recording.finalize(run)
        return self.repository.save(run)

    def create(
        self,
        payload: dict[str, Any],
        *,
        message: str,
        runtime_context: dict[str, Any] | None = None,
        user_id: str | None = None,
        source: str | None = None,
        channel: str = "compat_chat",
        intent: str = "legacy_chat_adapter",
    ) -> AgentRun:
        observed = self.create_observed_tools(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=str(intent or "").strip()
            if str(intent or "").strip() and str(intent or "").strip() != "legacy_chat_adapter"
            else "legacy_tool_chain",
        )
        if observed is not None:
            return observed
        orchestrated = self.create_tool_plan(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
        )
        if orchestrated is not None:
            return orchestrated
        status = _payload_status(payload)
        resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
        text = str(payload.get("response") or _payload_data(payload).get("text") or "")
        run = AgentRun(
            user_id=resolved_user_id,
            message=str(message or ""),
            status=status,
            intent=str(intent or "legacy_chat_adapter").strip() or "legacy_chat_adapter",
            metadata={
                "channel": channel,
                "source": str(source or "").strip(),
                "trace_mode": "post_execution",
                "runtime_context": _trace_safe_value(runtime_context or {}),
            },
            final_output={"chat_payload": _trace_safe_value(payload)},
        )
        apply_task_context(run, runtime_context)
        run.add_event(
            "run.created",
            "Chat 请求已进入 AgentRun 追踪",
            {"channel": channel, "source": str(source or "").strip()},
        )
        self.recording.enrich(run, payload, query=message)
        self.recording.finalize(run)
        from app.application.agent_orchestrator.business_harness import mark_unexecuted_order_run

        if mark_unexecuted_order_run(run, message):
            status = "failed"
        if status == "waiting_user":
            run.add_event(
                "step.waiting_user",
                str(payload.get("message") or "等待用户授权"),
                {
                    "token_name": payload.get("token_name")
                    or _payload_data(payload).get("token_name"),
                    "token_description": payload.get("token_description")
                    or _payload_data(payload).get("token_description"),
                },
            )
        elif status == "failed":
            run.error = run.error or _payload_error_message(payload)
            run.add_event("run.failed", run.error, {"response_preview": text[:500]})
        else:
            run.add_event("run.completed", "Chat 响应已完成", {"response_preview": text[:500]})
        return self.repository.save(run)

    def finalize(
        self,
        run: AgentRun,
        payload: dict[str, Any],
        *,
        message: str,
        runtime_context: dict[str, Any] | None = None,
        user_id: str | None = None,
        source: str | None = None,
        channel: str = "compat_chat",
        intent: str = "legacy_chat_adapter",
    ) -> dict[str, Any]:
        status = _payload_status(payload)
        records = _extract_legacy_tool_records(payload)
        run.status = status
        run.error = ""
        run.metadata["channel"] = channel
        run.metadata["source"] = str(source or "").strip()
        run.metadata["trace_mode"] = "legacy_planner_run"
        run.metadata["runtime_context"] = _trace_safe_value(runtime_context or {})
        run.add_event(
            "planner.completed",
            "执行计划已生成",
            {"status": status, "observed_tool_records": len(records)},
        )
        node_outputs: dict[str, Any] = {}
        total_cost = 0
        if records:
            run.metadata["trace_mode"] = "legacy_planner_run_with_tools"
            (node_outputs, total_cost) = self.recording.observe_tools(run, records)
            if status == "completed" and any(step.status == "failed" for step in run.steps):
                run.status = "failed"
                run.error = "legacy planner tool failed"
        self.recording.enrich(run, payload, query=message)
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = total_cost
        run.final_output = {
            "chat_payload": _trace_safe_value(payload),
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "cost_units_total": total_cost,
        }
        self.recording.finalize(run)
        from app.application.agent_orchestrator.business_harness import mark_unexecuted_order_run

        mark_unexecuted_order_run(run, message)
        if run.status == "waiting_user":
            run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
        elif run.status == "failed":
            run.error = run.error or _payload_error_message(payload)
            run.add_event("run.failed", run.error, run.final_output)
        else:
            run.add_event("run.completed", "智能任务执行完成", run.final_output)
        self.repository.save(run)
        return _attach_run_id(payload, run.run_id)
