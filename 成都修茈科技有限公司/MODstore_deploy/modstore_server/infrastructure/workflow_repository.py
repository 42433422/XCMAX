"""Workflow persistence adapters (minimal in-memory for tests)."""

from __future__ import annotations

from modstore_server.domain.workflow.types import Workflow, WorkflowExecution


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self.workflows: dict[int, Workflow] = {}

    def get(self, workflow_id: int) -> Workflow | None:
        return self.workflows.get(workflow_id)

    def save(self, workflow: Workflow) -> None:
        _ = workflow


class InMemoryWorkflowExecutionRepository:
    def __init__(self) -> None:
        self.execs: dict[int, WorkflowExecution] = {}

    def save(self, execution: WorkflowExecution) -> None:
        self.execs[id(execution)] = execution

    def get(self, execution_id: int) -> WorkflowExecution | None:
        return self.execs.get(execution_id)

    def list_for_workflow(self, workflow_id: int, *, limit: int = 50) -> list[dict]:
        return [{"workflow_id": workflow_id, "limit": limit}]


__all__ = [
    "InMemoryWorkflowExecutionRepository",
    "InMemoryWorkflowRepository",
]
