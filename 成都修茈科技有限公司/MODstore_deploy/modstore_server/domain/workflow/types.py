"""Workflow domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Workflow:
    """Workflow definition aggregate (graph metadata)."""

    workflow_id: int
    owner_user_id: int
    name: str = ""
    graph: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowExecution:
    """A single workflow run."""

    workflow_id: int
    execution_id: int
    user_id: int
    status: WorkflowRunStatus
    input_data: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
