from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.agent_orchestrator.run_models import AgentRun, artifact_from_dict


class ArtifactAttachmentMixin:
    """Attach tool artifacts to a run and maintain its artifact metadata."""

    if TYPE_CHECKING:
        _can_auto_execute: Any
        _ingest_artifact_to_dataset: Any

    def _attach_artifacts_from_payload(
        self,
        run: AgentRun,
        payload: dict[str, Any],
        *,
        source: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        artifacts = payload.get("artifacts")
        if artifacts is None:
            artifacts = payload.get("artifact")
        if isinstance(artifacts, dict):
            artifact_items = [artifacts]
        elif isinstance(artifacts, list):
            artifact_items = [item for item in artifacts if isinstance(item, dict)]
        else:
            artifact_items = []

        for item in artifact_items:
            artifact = artifact_from_dict(item)
            if not artifact.artifact_type:
                continue
            artifact.source = source if source == "plan.metadata" else artifact.source or source
            if extra_metadata:
                merged_metadata = dict(artifact.metadata or {})
                merged_metadata.update(extra_metadata)
                artifact.metadata = merged_metadata
            # Tools perform authorized writes themselves. Attaching their output
            # must neither repeat that write nor infer a new knowledge operation.
            artifact.metadata = {**artifact.metadata, "skip_dataset_ingest": True}
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
        if artifact_items:
            self._refresh_artifact_metadata(run)

    def _ingest_confirmed_plan_artifacts(self, run: AgentRun) -> None:
        if run.status != "completed":
            return
        # Old persisted plans may still carry deferred ingestion markers. An
        # unrelated business approval must not grant knowledge-write authority.
        for artifact in run.artifacts:
            if artifact.metadata.get("dataset_ingest_pending_step_ids"):
                artifact.metadata.pop("dataset_ingest_pending_step_ids")
                artifact.metadata["skip_dataset_ingest"] = True

    @staticmethod
    def _refresh_artifact_metadata(run: AgentRun) -> None:
        run.metadata["artifact_count"] = len(run.artifacts)
