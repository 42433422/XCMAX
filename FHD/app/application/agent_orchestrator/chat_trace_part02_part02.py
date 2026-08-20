# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


def _iter_inferred_artifacts(
    payload: dict[str, _facade().Any],
) -> _facade().Iterator[_facade().AgentArtifact]:
    for item in _facade()._iter_payload_dicts(payload):
        for key in ("ocr_result", "ocr", "recognized_text"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _facade()._artifact_from_ocr_payload(nested)
                if artifact is not None:
                    yield artifact
        for key in ("file_analysis", "analysis_result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _facade()._artifact_from_file_analysis_payload(nested)
                if artifact is not None:
                    yield artifact
        for key in ("document", "generated_document", "office_document"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _facade()._artifact_from_generated_document_payload({"document": nested})
                if artifact is not None:
                    yield artifact
        excel_analysis = item.get("excel_analysis")
        if isinstance(excel_analysis, dict):
            artifact = _facade()._artifact_from_excel_analysis_payload(excel_analysis)
            if artifact is not None:
                yield artifact
        for factory in (
            _facade()._artifact_from_ocr_payload,
            _facade()._artifact_from_file_analysis_payload,
            _facade()._artifact_from_generated_document_payload,
            _facade()._artifact_from_excel_analysis_payload,
        ):
            artifact = factory(item)
            if artifact is not None:
                yield artifact


def _extract_artifacts(payload: dict[str, _facade().Any]) -> list[_facade().AgentArtifact]:
    artifacts: list[_facade().AgentArtifact] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for explicit in _facade()._iter_explicit_artifact_payloads(payload):
        artifact = _facade().artifact_from_dict(explicit)
        if not artifact.artifact_type:
            continue
        signature = _facade()._artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)
    for artifact in _facade()._iter_inferred_artifacts(payload):
        if not artifact.artifact_type:
            continue
        signature = _facade()._artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)
    return artifacts


def _refresh_artifact_metadata(run: _facade().AgentRun) -> None:
    run.metadata["artifact_count"] = len(run.artifacts)
    run.metadata["artifact_types"] = sorted({artifact.artifact_type for artifact in run.artifacts})


def _append_artifacts_to_run(
    run: _facade().AgentRun, artifacts: list[_facade().AgentArtifact]
) -> None:
    existing = {_facade()._artifact_signature(artifact) for artifact in run.artifacts}
    for artifact in artifacts:
        signature = _facade()._artifact_signature(artifact)
        if signature in existing:
            continue
        existing.add(signature)
        run.artifacts.append(artifact)
        run.add_event(
            "artifact.attached",
            f"Artifact 已附加: {artifact.artifact_type}",
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "name": artifact.name,
                "source": artifact.source,
                "uri": artifact.uri,
            },
        )
        _facade().ingest_artifact_to_dataset(run, artifact)
    if run.artifacts:
        _facade()._refresh_artifact_metadata(run)


def _append_artifacts_to_final_output(run: _facade().AgentRun) -> None:
    if not run.artifacts:
        return
    final_output = dict(run.final_output or {})
    final_output["artifacts"] = [artifact.to_dict() for artifact in run.artifacts]
    final_output["artifact_count"] = len(run.artifacts)
    if run.metadata.get("dataset_ingests"):
        final_output["dataset_ingests"] = run.metadata["dataset_ingests"]
        final_output["dataset_ingest_count"] = run.metadata.get("dataset_ingest_count", 0)
    run.final_output = final_output


def _normalized_record_payload(
    record: dict[str, _facade().Any],
) -> tuple[str, str, dict[str, _facade().Any], dict[str, _facade().Any]]:
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
    run: _facade().AgentRun, records: list[dict[str, _facade().Any]]
) -> tuple[dict[str, _facade().Any], int]:
    node_outputs: dict[str, _facade().Any] = {}
    total_cost = 0
    for idx, record in enumerate(records, start=1):
        (tool_id, action, params, output) = _facade()._normalized_record_payload(record)
        if not tool_id:
            continue
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        spec = get_tool_action_spec(tool_id, action)
        node_id = f"legacy_{idx}_{tool_id}_{action}".replace(".", "_")
        step = _facade().AgentStep(
            node_id=node_id,
            tool_id=tool_id,
            action=getattr(spec, "action", action) if spec is not None else action,
            params=params,
            risk=getattr(spec, "risk", "medium") if spec is not None else "medium",
            idempotent=bool(getattr(spec, "idempotent", False)) if spec is not None else False,
            description="legacy planner 已执行工具调用",
            status="completed" if output.get("success") is not False else "failed",
            output=output,
            finished_at=_facade().utc_now_iso(),
        )
        call = _facade().ToolCall(
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
        _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(output))
    return (node_outputs, total_cost)


def _create_legacy_tool_records_run(
    payload: dict[str, _facade().Any],
    *,
    message: str,
    runtime_context: dict[str, _facade().Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: _facade().AgentRunRepository,
    intent: str = "legacy_tool_chain",
) -> _facade().AgentRun | None:
    records = _facade()._extract_legacy_tool_records(payload)
    if not records:
        return None
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    status = _facade()._payload_status(payload)
    run = _facade().AgentRun(
        user_id=resolved_user_id,
        message=str(message or ""),
        status=status,
        intent=str(intent or "legacy_tool_chain").strip() or "legacy_tool_chain",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "legacy_tool_records",
            "runtime_context": _facade()._trace_safe_value(runtime_context or {}),
        },
        final_output={"chat_payload": _facade()._trace_safe_value(payload)},
    )
    _facade().apply_task_context(run, runtime_context)
    run.add_event(
        "run.created",
        "Legacy planner 工具调用已进入 AgentRun 追踪",
        {"channel": channel, "source": str(source or "").strip(), "observed": True},
    )
    (node_outputs, total_cost) = _facade()._append_legacy_tool_records_to_run(run, records)
    _facade()._append_llm_calls_to_run(run, _facade()._extract_llm_calls(payload))
    _facade()._append_retrieval_calls_to_run(
        run, _facade()._extract_retrieval_calls(payload, query=message)
    )
    _facade()._append_memory_references_to_run(
        run, _facade()._extract_memory_references(payload, query=message)
    )
    _facade()._append_artifacts_to_run(run, _facade()._extract_artifacts(payload))
    if run.steps and status == "completed" and any(step.status == "failed" for step in run.steps):
        run.status = "failed"
        run.error = "legacy planner tool failed"
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
    if run.status == "failed":
        run.add_event("run.failed", run.error or "Legacy planner 工具调用失败", run.final_output)
    elif run.status == "waiting_user":
        run.add_event("step.waiting_user", str(payload.get("message") or "等待用户授权"), {})
    else:
        run.add_event("run.completed", "Legacy planner 工具调用追踪完成", run.final_output)
    return repository.save(run)


def _create_tool_call_agent_run(
    payload: dict[str, _facade().Any],
    *,
    message: str,
    runtime_context: dict[str, _facade().Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: _facade().AgentRunRepository,
) -> _facade().AgentRun | None:
    extracted = _facade()._extract_low_risk_tool_call(payload)
    if extracted is None:
        return None
    (tool_id, action, params, raw_tool_call) = extracted
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.workflow.types import PlanGraph, WorkflowNode

    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    runtime = dict(runtime_context or {})
    runtime.update(
        {
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "orchestrated_tool_call",
            "legacy_tool_call": _facade()._trace_safe_value(raw_tool_call),
        }
    )
    plan = PlanGraph(
        plan_id=f"compat-tool-{_facade().uuid4().hex[:12]}",
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
            "legacy_tool_call": _facade()._trace_safe_value(raw_tool_call),
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
    return repository.save(run)


def _attach_run_id(payload: dict[str, _facade().Any], run_id: str) -> dict[str, _facade().Any]:
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
    runtime_context: dict[str, _facade().Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> _facade().AgentRun:
    resolved_user_id = _facade()._resolved_user_id(runtime_context=runtime_context, user_id=user_id)
    run = _facade().AgentRun(
        user_id=resolved_user_id,
        message=str(message or ""),
        status="running",
        intent=str(intent or "legacy_chat_adapter").strip() or "legacy_chat_adapter",
        metadata={
            "channel": channel,
            "source": str(source or "").strip(),
            "trace_mode": "legacy_planner_run",
            "runtime_context": _facade()._trace_safe_value(runtime_context or {}),
        },
    )
    _facade().apply_task_context(run, runtime_context)
    run.add_event(
        "run.created", "智能任务已创建", {"channel": channel, "source": str(source or "").strip()}
    )
    run.add_event(
        "planner.started",
        "正在生成执行计划",
        {"channel": channel, "source": str(source or "").strip()},
    )
    return _facade().get_agent_run_repository().save(run)
