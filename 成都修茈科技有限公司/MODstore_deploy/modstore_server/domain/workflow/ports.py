"""Workflow domain ports."""

from __future__ import annotations

from typing import Any, Protocol

from modstore_server.domain.workflow.types import Workflow, WorkflowExecution


class WorkflowRepository(Protocol):
    def get(self, workflow_id: int) -> Workflow | None: ...

    def save(self, workflow: Workflow) -> None: ...


class WorkflowExecutionRepository(Protocol):
    def save(self, execution: WorkflowExecution) -> None: ...

    def get(self, execution_id: int) -> WorkflowExecution | None: ...

    def list_for_workflow(self, workflow_id: int, *, limit: int = 50) -> list[dict[str, Any]]: ...


__all__ = ["WorkflowRepository", "WorkflowExecutionRepository"]
