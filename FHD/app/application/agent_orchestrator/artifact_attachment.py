from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.agent_orchestrator.artifact_ingestion import stage_artifact_for_confirmation
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

        approval_step_ids = (
            [step.step_id for step in run.steps if not self._can_auto_execute(step)]
            if source == "plan.metadata"
            else []
        )
        for item in artifact_items:
            artifact = artifact_from_dict(item)
            if not artifact.artifact_type:
                continue
            artifact.source = artifact.source or source
            if extra_metadata:
                merged_metadata = dict(artifact.metadata or {})
                merged_metadata.update(extra_metadata)
                artifact.metadata = merged_metadata
            if approval_step_ids:
                stage_artifact_for_confirmation(run, artifact, approval_step_ids)
            elif (
                extra_metadata
                and extra_metadata.get("step_id")
                and (
                    payload.get("success") is not True
                    or payload.get("outcome") == "unknown"
                    or payload.get("reconciliation_required")
                    or payload.get("outcome_unknown")
                    or payload.get("requires_reconciliation")
                )
            ):
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
            self._ingest_artifact_to_dataset(run, artifact)
        if artifact_items:
            self._refresh_artifact_metadata(run)

    def _ingest_confirmed_plan_artifacts(self, run: AgentRun) -> None:
        if run.status != "completed":
            return
        approved = {
            event.data.get("step_id") for event in run.events if event.event_type == "step.approved"
        }
        completed = {
            step.step_id
            for step in run.steps
            if step.status == "completed"
            and step.output.get("success") is True
            and step.output.get("outcome") != "unknown"
            and not step.output.get("reconciliation_required")
            and not step.output.get("outcome_unknown")
            and not step.output.get("requires_reconciliation")
        }
        for artifact in run.artifacts:
            pending = artifact.metadata.get("dataset_ingest_pending_step_ids")
            if not isinstance(pending, list) or not pending:
                continue
            if not set(pending).issubset(approved & completed):
                continue
            artifact.metadata.pop("dataset_ingest_pending_step_ids")
            artifact.metadata["dataset_ingest_approved_step_ids"] = list(pending)
            self._ingest_artifact_to_dataset(run, artifact)

    @staticmethod
    def _refresh_artifact_metadata(run: AgentRun) -> None:
        run.metadata["artifact_count"] = len(run.artifacts)
