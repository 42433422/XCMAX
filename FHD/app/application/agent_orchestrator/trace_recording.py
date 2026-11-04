"""Record observed evidence with injected model accounting, artifact ingestion and tool metadata."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .run_models import AgentArtifact, AgentRun, AgentStep, ToolCall, utc_now_iso
from .tool_spec import ToolActionSpecV2
from .trace_artifacts import (
    _append_artifacts_to_final_output,
    _artifact_signature,
    _extract_artifacts,
    _refresh_artifact_metadata,
)
from .trace_memory import (
    _append_memory_references_to_final_output,
    _append_memory_references_to_run,
    _extract_memory_references,
)
from .trace_model_usage import ModelUsageRecorder, _extract_llm_calls
from .trace_retrieval import (
    _append_retrieval_calls_to_final_output,
    _append_retrieval_calls_to_run,
    _extract_retrieval_calls,
)
from .trace_tools import _normalized_record_payload

logger = logging.getLogger(__name__)


class TraceRecorder:
    def __init__(
        self,
        model_usage: ModelUsageRecorder,
        ingest_artifact: Callable[[AgentRun, AgentArtifact], dict[str, Any] | None],
        tool_spec: Callable[[str, str], ToolActionSpecV2 | None],
    ) -> None:
        self.model_usage = model_usage
        self.ingest_artifact = ingest_artifact
        self.tool_spec = tool_spec

    def enrich(self, run: AgentRun, payload: dict[str, Any], *, query: str) -> None:
        self.model_usage.append(run, _extract_llm_calls(payload))
        _append_retrieval_calls_to_run(run, _extract_retrieval_calls(payload, query=query))
        _append_memory_references_to_run(run, _extract_memory_references(payload, query=query))
        self.append_artifacts(run, _extract_artifacts(payload))

    def finalize(self, run: AgentRun) -> None:
        self.model_usage.finalize(run)
        _append_retrieval_calls_to_final_output(run)
        _append_memory_references_to_final_output(run)
        _append_artifacts_to_final_output(run)

    def append_artifacts(self, run: AgentRun, artifacts: list[AgentArtifact]) -> None:
        existing = {_artifact_signature(artifact) for artifact in run.artifacts}
        for artifact in artifacts:
            signature = _artifact_signature(artifact)
            if signature in existing:
                continue
            existing.add(signature)
            run.artifacts.append(artifact)
            logger.info(
                "agent artifact recorded: run_id=%s artifact_id=%s artifact_type=%s name=%s uri=%s",
                run.run_id,
                artifact.artifact_id,
                artifact.artifact_type,
                artifact.name,
                artifact.uri,
            )
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
            self.ingest_artifact(run, artifact)
        if run.artifacts:
            _refresh_artifact_metadata(run)

    def observe_tools(
        self, run: AgentRun, records: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], int]:
        node_outputs: dict[str, Any] = {}
        total_cost = 0
        for idx, record in enumerate(records, start=1):
            (tool_id, action, params, output) = _normalized_record_payload(record)
            if not tool_id:
                continue
            spec = self.tool_spec(tool_id, action)
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
            logger.info(
                "agent tool call: run_id=%s tool_id=%s action=%s status=%s duration_ms=%s",
                run.run_id,
                step.tool_id,
                step.action,
                call.status,
                call.duration_ms,
            )
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
            self.append_artifacts(run, _extract_artifacts(output))
        return (node_outputs, total_cost)
