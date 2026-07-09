"""
Legacy planner tool-chain trace and public chat trace APIs.

Split from ``chat_trace.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.application.agent_orchestrator._chat_trace_facade import module as _chat_trace_facade
from app.application.agent_orchestrator.chat_trace_artifact import (
    _append_artifacts_to_final_output,
    _append_artifacts_to_run,
    _extract_artifacts,
)
from app.application.agent_orchestrator.chat_trace_common import (
    _extract_legacy_tool_records,
    _extract_low_risk_tool_call,
    _payload_data,
    _payload_error_message,
    _payload_status,
    _resolved_user_id,
    _trace_safe_value,
)
from app.application.agent_orchestrator.chat_trace_llm import (
    _append_llm_calls_to_final_output,
    _append_llm_calls_to_run,
    _extract_llm_calls,
)
from app.application.agent_orchestrator.chat_trace_memory import (
    _append_memory_references_to_final_output,
    _append_memory_references_to_run,
    _extract_memory_references,
)
from app.application.agent_orchestrator.chat_trace_retrieval import (
    _append_retrieval_calls_to_final_output,
    _append_retrieval_calls_to_run,
    _extract_retrieval_calls,
)
from app.application.agent_orchestrator.run_models import (
    AgentRun,
    AgentStep,
    ToolCall,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_repository import AgentRunRepository

logger = logging.getLogger(__name__)

def _normalized_record_payload(
    record: dict[str, Any],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    tool_id = str(
        record.get("tool_id") or record.get("tool_name") or record.get("tool_key") or ""
    ).strip()
    action = str(record.get("action") or "").strip() or "execute"
    params = record.get("params")
    output = record.get("output")
    return (
        tool_id,
        action,
        dict(params) if isinstance(params, dict) else {},
        dict(output)
        if isinstance(output, dict)
        else {"success": False, "message": str(output or "")},
    )


def _append_legacy_tool_records_to_run(
    run: AgentRun,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    node_outputs: dict[str, Any] = {}
    total_cost = 0
    for idx, record in enumerate(records, start=1):
        tool_id, action, params, output = _normalized_record_payload(record)
        if not tool_id:
            continue
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        spec = get_tool_action_spec(tool_id, action)
        node_id = f"legacy_{idx}_{tool_id}_{action}".replace(".", "_")
        step = AgentStep(
            node_id=node_id,
            tool_id=tool_id,
            action=getattr(spec, "action", action) if spec is not None else action,
            params=params,
            risk=getattr(spec, "risk", "medium") if spec is not None else "medium",
            idempotent=bool(getattr(spec, "idempotent", False)) if spec is not None else False,
            description="legacy planner 已执行工具调用",
            status="completed" if output.get("success") is not False else "failed",
            output=output,
            finished_at=utc_now_iso(),
        )
        call = ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=params,
            status="completed" if step.status == "completed" else "failed",
            output=output,
            error=""
            if step.status == "completed"
            else str(output.get("message") or output.get("error") or ""),
            cost_units=int(getattr(spec, "cost_units", 0) or 0),
            permission=str(getattr(spec, "permission", "") or ""),
            finished_at=step.finished_at,
            metadata={
                "observed": True,
                "legacy_tool_call_id": str(record.get("tool_call_id") or ""),
                "risk": step.risk,
                "idempotent": step.idempotent,
            },
        )
        run.steps.append(step)
        run.tool_calls.append(call)
        node_outputs[step.node_id] = output
        total_cost += call.cost_units
        run.add_event(
            "tool.started",
            f"观察到 legacy 工具 {step.tool_id}.{step.action}",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": call.call_id,
                "cost_units": call.cost_units,
                "permission": call.permission,
                "observed": True,
            },
        )
        event_type = "tool.completed" if step.status == "completed" else "tool.failed"
        run.add_event(
            event_type,
            f"记录 legacy 工具 {step.tool_id}.{step.action}",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": call.call_id,
                "cost_units": call.cost_units,
                "observed": True,
            },
        )
        _append_artifacts_to_run(run, _extract_artifacts(output))
    return node_outputs, total_cost


def _create_legacy_tool_records_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: AgentRunRepository,
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
    run.add_event(
        "run.created",
        "Legacy planner 工具调用已进入 AgentRun 追踪",
        {"channel": channel, "source": str(source or "").strip(), "observed": True},
    )

    node_outputs, total_cost = _append_legacy_tool_records_to_run(run, records)
    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))

    if run.steps and status == "completed" and any(step.status == "failed" for step in run.steps):
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
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)
    if run.status == "failed":
        run.add_event("run.failed", run.error or "Legacy planner 工具调用失败", run.final_output)
    elif run.status == "waiting_user":
        run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
    else:
        run.add_event("run.completed", "Legacy planner 工具调用追踪完成", run.final_output)
    return repository.save(run)


def _create_tool_call_agent_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: AgentRunRepository,
) -> AgentRun | None:
    extracted = _extract_low_risk_tool_call(payload)
    if extracted is None:
        return None

    tool_id, action, params, raw_tool_call = extracted
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode

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
    run = AgentOrchestrator(repository=repository).start_run_from_plan(
        user_id=resolved_user_id,
        message=str(message or ""),
        plan=plan,
        runtime_context=runtime,
        auto_execute=True,
    )
    run.metadata["channel"] = channel
    run.metadata["source"] = str(source or "").strip()
    run.metadata["trace_mode"] = "orchestrated_tool_call"
    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)
    return repository.save(run)


def _attach_run_id(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    payload["run_id"] = run_id
    payload["agent_run_id"] = run_id
    data = payload.get("data")
    if isinstance(data, dict):
        data["run_id"] = run_id
        data["agent_run_id"] = run_id
    else:
        payload["data"] = {"run_id": run_id, "agent_run_id": run_id}
    return payload


def start_legacy_chat_run(
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
    run.add_event(
        "run.created",
        "Legacy planner run 已创建",
        {"channel": channel, "source": str(source or "").strip()},
    )
    run.add_event(
        "planner.started",
        "Legacy planner 开始执行",
        {"channel": channel, "source": str(source or "").strip()},
    )
    return _chat_trace_facade().get_agent_run_repository().save(run)


def finalize_legacy_chat_run(
    run_id: str,
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload

    repository = _chat_trace_facade().get_agent_run_repository()
    run = repository.get(run_id)
    if run is None:
        return attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )

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
        "Legacy planner 执行完成",
        {"status": status, "observed_tool_records": len(records)},
    )

    node_outputs: dict[str, Any] = {}
    total_cost = 0
    if records:
        run.metadata["trace_mode"] = "legacy_planner_run_with_tools"
        node_outputs, total_cost = _append_legacy_tool_records_to_run(run, records)
        if status == "completed" and any(step.status == "failed" for step in run.steps):
            run.status = "failed"
            run.error = "legacy planner tool failed"

    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))
    run.metadata["tool_call_count"] = len(run.tool_calls)
    run.metadata["cost_units_total"] = total_cost
    run.final_output = {
        "chat_payload": _trace_safe_value(payload),
        "node_outputs": node_outputs,
        "tool_calls": [call.to_dict() for call in run.tool_calls],
        "cost_units_total": total_cost,
    }
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)

    if run.status == "waiting_user":
        run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
    elif run.status == "failed":
        run.error = run.error or _payload_error_message(payload)
        run.add_event("run.failed", run.error, run.final_output)
    else:
        run.add_event("run.completed", "Legacy planner run 执行完成", run.final_output)
    repository.save(run)
    return _attach_run_id(payload, run.run_id)


def create_chat_trace_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> AgentRun:
    repository = _chat_trace_facade().get_agent_run_repository()
    observed = _create_legacy_tool_records_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        repository=repository,
        intent=(
            str(intent or "").strip()
            if str(intent or "").strip() and str(intent or "").strip() != "legacy_chat_adapter"
            else "legacy_tool_chain"
        ),
    )
    if observed is not None:
        return observed

    orchestrated = _create_tool_call_agent_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        repository=repository,
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
    run.add_event(
        "run.created",
        "Chat 请求已进入 AgentRun 追踪",
        {"channel": channel, "source": str(source or "").strip()},
    )
    _append_llm_calls_to_run(run, _extract_llm_calls(payload))
    _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=message))
    _append_memory_references_to_run(run, _extract_memory_references(payload, query=message))
    _append_artifacts_to_run(run, _extract_artifacts(payload))
    _append_llm_calls_to_final_output(run)
    _append_retrieval_calls_to_final_output(run)
    _append_memory_references_to_final_output(run)
    _append_artifacts_to_final_output(run)
    if status == "waiting_user":
        run.add_event(
            "step.waiting_user",
            str(payload.get("message") or "等待用户授权"),
            {
                "token_name": payload.get("token_name") or _payload_data(payload).get("token_name"),
                "token_description": payload.get("token_description")
                or _payload_data(payload).get("token_description"),
            },
        )
    elif status == "failed":
        run.error = _payload_error_message(payload)
        run.add_event("run.failed", run.error, {"response_preview": text[:500]})
    else:
        run.add_event("run.completed", "Chat 响应已完成", {"response_preview": text[:500]})

    return repository.save(run)


def attach_chat_trace_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and (data.get("run_id") or data.get("agent_run_id")):
        return payload
    if payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        run = create_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )
    except Exception:  # noqa: BLE001 - tracing must not break the chat response
        logger.exception("failed to attach AgentRun trace to chat response")
        return payload

    return _attach_run_id(payload, run.run_id)
