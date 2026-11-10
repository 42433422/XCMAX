"""Record observed evidence with injected model accounting, artifact ingestion and tool metadata."""

from __future__ import annotations

import logging
from typing import Any

from .run_models import (
    AgentArtifact,
    AgentRun,
)
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

logger = logging.getLogger(__name__)


class TraceRecorder:
    def __init__(self, model_usage: ModelUsageRecorder) -> None:
        self.model_usage = model_usage

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
            # A response-side artifact is evidence, not an execution grant.
            artifact.metadata = {**artifact.metadata, "skip_dataset_ingest": True}
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
        if run.artifacts:
            _refresh_artifact_metadata(run)
