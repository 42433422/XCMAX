"""Extracted helpers for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def _append_legacy_tool_records_to_run(
    run: AgentRun,
    records: list[dict[str, Any]],
    *,
    runtime_context: dict[str, Any] | None = None,
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
        orchestration = build_orchestration_evidence(
            step.tool_id,
            step.action,
            params,
            output,
            runtime_context,
            status="completed" if step.status == "completed" else "failed",
        )
        call.metadata["orchestration"] = orchestration
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
                "orchestration": orchestration,
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
                "orchestration": orchestration,
            },
        )
        _append_artifacts_to_run(run, _extract_artifacts(output))
    return node_outputs, total_cost


sync_module_functions(
    target=globals(),
    source_module="app.application.agent_orchestrator.chat_trace",
    function_names=("_append_legacy_tool_records_to_run",),
)
