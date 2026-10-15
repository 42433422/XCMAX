# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


def resolve_legacy_approval(
    request_id: str,
    context: dict[str, _facade().Any],
    result: _facade().Any = None,
    *,
    run_before_restore: _facade().AgentRun | None = None,
) -> str:
    """记录已执行审批的真实结果；仅更新同账号/租户/Mod且精确匹配审批的观察任务。"""
    from app.application.agent_orchestrator.unified_task import (
        UnifiedTaskConflictError,
        _assert_reused_run_scope,
    )

    run_id = str(context.get("agent_run_id") or "")
    if not run_id:
        return ""
    repo = _facade().get_agent_run_repository()
    run = repo.get(run_id) or run_before_restore
    if (
        run is None
        or run.run_id != run_id
        or run.intent not in {"legacy_chat_adapter", "legacy_tool_chain"}
        or run.status != "waiting_user"
    ):
        return ""
    try:
        _assert_reused_run_scope(
            run,
            user_id=_facade()._resolved_user_id(runtime_context=context, user_id=None),
            tenant_id=str(context.get("tenant_id") or ""),
            runtime_context=context,
        )
    except UnifiedTaskConflictError:
        return ""
    original = run.metadata.get("runtime_context") or {}
    if any(
        str(original.get(key) or "") != str(context.get(key) or "")
        for key in (
            "task_id",
            "session_id",
            "conversation_id",
            "turn_id",
        )
    ):
        return ""
    calls = [
        call
        for call in run.tool_calls
        if call.output.get("pending_approval") is True
        and request_id in (call.output.get("approval") or {}).get("approval_request_ids", [])
    ]
    if len(calls) != 1:
        return ""
    call = calls[0]
    nodes = [
        node
        for node in (result.node_results if result else [])
        if node.tool_id == call.params.get("tool_id", call.tool_id)
        and node.action == call.params.get("action", call.action)
    ]
    if result and len(nodes) != 1:
        return ""
    success = bool(result and result.success and nodes[0].success)
    outputs = [dict(getattr(node, "output", {}) or {}) for node in nodes]
    output = {
        "success": success,
        "pending_approval": False,
        "message": "审批业务执行完成" if success else "审批业务失败或已拒绝",
        "data": outputs[0].get("data", outputs[0]) if outputs else {},
    }
    run.add_event(
        "approval.resolved",
        output["message"],
        {"approval_request_id": request_id, "previous_output": call.output, "success": success},
    )
    call.output, call.status, call.error = (
        output,
        "completed" if success else "failed",
        "" if success else output["message"],
    )
    for step in run.steps:
        if step.step_id == call.step_id:
            step.output, step.status = output, call.status
    run.final_output.setdefault("node_outputs", {})[call.node_id] = output
    run.final_output["chat_payload"] = output
    run.final_output["tool_calls"] = [item.to_dict() for item in run.tool_calls]
    run.final_output.pop("business_result", None)
    remaining = any(item.output.get("pending_approval") is True for item in run.tool_calls)
    run.status = (
        "waiting_user"
        if remaining
        else ("completed" if success else ("failed" if result else "cancelled"))
    )
    run.error = "" if success or remaining else output["message"]
    if not remaining:
        run.add_event(f"run.{run.status}", output["message"], {"approval_request_id": request_id})
    if result:
        for node in nodes:
            _facade()._append_artifacts_to_run(
                run, _facade()._extract_artifacts(dict(getattr(node, "output", {}) or {}))
            )
    _facade()._append_artifacts_to_final_output(run)
    repo.save(run)
    return run.run_id


def finalize_legacy_chat_run(
    run_id: str,
    payload: dict[str, _facade().Any],
    *,
    message: str,
    runtime_context: dict[str, _facade().Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, _facade().Any]:
    if not isinstance(payload, dict):
        return payload
    repository = _facade().get_agent_run_repository()
    run = repository.get(run_id)
    if run is None:
        return _facade().attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )
    status = _facade()._payload_status(payload)
    records = _facade()._extract_legacy_tool_records(payload)
    run.status = status
    run.error = ""
    run.metadata["channel"] = channel
    run.metadata["source"] = str(source or "").strip()
    run.metadata["trace_mode"] = "legacy_planner_run"
    run.metadata["runtime_context"] = _facade()._trace_safe_value(runtime_context or {})
    run.add_event(
        "planner.completed",
        "执行计划已生成",
        {"status": status, "observed_tool_records": len(records)},
    )
    node_outputs: dict[str, _facade().Any] = {}
    total_cost = 0
    if records:
        run.metadata["trace_mode"] = "legacy_planner_run_with_tools"
        (node_outputs, total_cost) = _facade()._append_legacy_tool_records_to_run(run, records)
        if status == "completed" and any(step.status == "failed" for step in run.steps):
            run.status = "failed"
            run.error = "legacy planner tool failed"
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(
        run, _facade()._extract_retrieval_calls(payload, query=message)
    )
    _facade()._append_memory_references_to_run(
        run, _facade()._extract_memory_references(payload, query=message)
    )
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    run.metadata["tool_call_count"] = len(run.tool_calls)
    run.metadata["cost_units_total"] = total_cost
    run.final_output = {
        "chat_payload": _facade()._trace_safe_value(payload),
        "node_outputs": node_outputs,
        "tool_calls": [call.to_dict() for call in run.tool_calls],
        "cost_units_total": total_cost,
    }
    _facade()._append_llm_calls_to_final_output(run)
    _facade()._append_retrieval_calls_to_final_output(run)
    _facade()._append_memory_references_to_final_output(run)
    _facade()._append_artifacts_to_final_output(run)
    if run.status == "waiting_user":
        run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
    elif run.status == "failed":
        run.error = run.error or _facade()._payload_error_message(payload)
        run.add_event("run.failed", run.error, run.final_output)
    else:
        run.add_event("run.completed", "智能任务执行完成", run.final_output)
    repository.save(run)
    return _facade()._attach_run_id(payload, run.run_id)


def create_chat_trace_run(
    payload: dict[str, _facade().Any],
    *,
    message: str,
    runtime_context: dict[str, _facade().Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> _facade().AgentRun:
    repository = _facade().get_agent_run_repository()
    observed = _facade()._create_legacy_tool_records_run(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        repository=repository,
        intent=str(intent or "").strip()
        if str(intent or "").strip() and str(intent or "").strip() != "legacy_chat_adapter"
        else "legacy_tool_chain",
    )
    if observed is not None:
        return observed
    orchestrated = _facade()._create_tool_call_agent_run(
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
    status = _facade()._payload_status(payload)
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    text = str(payload.get("response") or _facade()._payload_data(payload).get("text") or "")
    run = _facade().AgentRun(
        user_id=resolved_user_id,
        message=str(message or ""),
        status=status,
        intent=str(intent or "legacy_chat_adapter").strip() or "legacy_chat_adapter",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "post_execution",
            "runtime_context": _facade()._trace_safe_value(runtime_context or {}),
        },
        final_output={"chat_payload": _facade()._trace_safe_value(payload)},
    )
    _facade().apply_task_context(run, runtime_context)
    run.add_event(
        "run.created",
        "Chat 请求已进入 AgentRun 追踪",
        {"channel": channel, "source": str(source or "").strip()},
    )
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(
        run, _facade()._extract_retrieval_calls(payload, query=message)
    )
    _facade()._append_memory_references_to_run(
        run, _facade()._extract_memory_references(payload, query=message)
    )
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    _facade()._append_llm_calls_to_final_output(run)
    _facade()._append_retrieval_calls_to_final_output(run)
    _facade()._append_memory_references_to_final_output(run)
    _facade()._append_artifacts_to_final_output(run)
    if status == "waiting_user":
        run.add_event(
            "step.waiting_user",
            str(payload.get("message") or "等待用户授权"),
            {
                "token_name": payload.get("token_name")
                or _facade()._payload_data(payload).get("token_name"),
                "token_description": payload.get("token_description")
                or _facade()._payload_data(payload).get("token_description"),
            },
        )
    elif status == "failed":
        run.error = _facade()._payload_error_message(payload)
        run.add_event("run.failed", run.error, {"response_preview": text[:500]})
    else:
        run.add_event("run.completed", "Chat 响应已完成", {"response_preview": text[:500]})
    return repository.save(run)


def attach_chat_trace_run(
    payload: dict[str, _facade().Any],
    *,
    message: str,
    runtime_context: dict[str, _facade().Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, _facade().Any]:
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and (data.get("run_id") or data.get("agent_run_id")):
        return payload
    if payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        run = _facade().create_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("failed to attach AgentRun trace to chat response")
        return payload
    return _facade()._attach_run_id(payload, run.run_id)
