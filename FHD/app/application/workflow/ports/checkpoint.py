"""CheckpointStore port — contract for workflow checkpoint persistence.

Defines the checkpoint persistence contract consumed by the application layer.
The legacy ``WorkflowCheckpointer`` / ``DatabaseWorkflowCheckpointer`` and the
LangGraph checkpoint bridge (``infrastructure/workflow/checkpoint_bridge.py``)
are adapters behind this port.

A checkpoint is a plain dict snapshot holding ``plan_id``, ``checkpoint_id``,
``step_index``, ``runtime_context``, ``executed_nodes`` and ``blocked`` — the
shape produced by the legacy checkpointer and consumed by ``WorkflowEngine``
(``save_checkpoint`` / ``get_checkpoint`` / ``list_checkpoints`` /
``latest_checkpoint``).

This port depends only on application/domain types and ``Any`` — never on
``app.infrastructure``, ``app.neuro_bus``, ``langgraph``, ``sqlalchemy``, or
``fastapi``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

Checkpoint = dict[str, Any]


@runtime_checkable
class CheckpointStore(Protocol):
    """Store and retrieve step-indexed checkpoints for a ``plan_id``."""

    def save_checkpoint(
        self,
        plan_id: str,
        step_index: int,
        runtime_context: dict[str, Any],
        executed_nodes: list[str] | set[str],
        *,
        blocked: list[str] | set[str] | None = None,
    ) -> str:
        """Record a checkpoint and return its unique ``checkpoint_id``."""
        ...

    def get_checkpoint(self, plan_id: str, checkpoint_id: str) -> Checkpoint | None:
        """Return the snapshot for ``checkpoint_id`` under ``plan_id``, or ``None``."""
        ...

    def list_checkpoints(self, plan_id: str) -> list[Checkpoint]:
        """List all checkpoints for ``plan_id`` ordered by ``step_index`` ascending."""
        ...

    def latest_checkpoint(self, plan_id: str) -> Checkpoint | None:
        """Return the most advanced checkpoint for ``plan_id``, or ``None``."""
        ...