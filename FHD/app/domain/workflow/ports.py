"""Workflow bounded-context ports (canonical for checkpoint/events/tools).

``WorkflowRuntime`` stays in ``app.application.workflow.ports`` because it
references application-layer plan/result types; new non-typed contracts land here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

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


from typing import Any, Protocol, runtime_checkable

StateUpdateStatus = Literal["succeeded", "failed", "running"]


class StateUpdatePayload(TypedDict, total=False):
    """Shape of a ``state.update`` event emitted after a node completes."""

    type: Literal["state.update"]
    node_id: str
    status: StateUpdateStatus
    output_summary: str
    runtime: str
    plan_id: str


@dataclass(frozen=True)
class StateUpdateEvent:
    """Typed DTO for a ``state.update`` event.

    Mirrors the ``state.update`` dict emitted by ``WorkflowEngine``; the optional
    ``payload`` carries the raw dict for consumers that prefer the original shape.
    """

    type: str = "state.update"
    node_id: str = ""
    status: str = "succeeded"
    output_summary: str = ""
    runtime: str = ""
    plan_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class StateEventPublisher(Protocol):
    """Publish ``state.update`` state events for streaming/aggregation consumers."""

    def publish_state_update(self, event: StateUpdateEvent) -> None:
        """Publish a single ``state.update`` event; must never raise to the caller."""
        ...


@runtime_checkable
class EventBusPort(Protocol):
    """Port over the event subsystem (e.g. NeuroBus) for workflow events.

    Implementations bridge to the infrastructure event bus; ``publish`` must be
    best-effort and fail-soft (log-and-continue) so a temporary bus outage never
    breaks the workflow run.
    """

    def publish(self, event: StateUpdateEvent | StateUpdatePayload | dict[str, Any]) -> None:
        """Publish an event; accepts a typed event or a raw state-update dict."""
        ...


from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ToolCall(Protocol):
    """A single tool invocation intent (tool_id + action + params)."""

    tool_id: str
    action: str
    params: dict[str, Any]


@runtime_checkable
class ToolResult(Protocol):
    """A tool invocation result. ``success`` is the only guaranteed field."""

    success: bool
    output: dict[str, Any]


@runtime_checkable
class ToolDispatcher(Protocol):
    """Dispatcher that resolves a tool action and executes it.

    ``_runtime_context`` is injected into ``params`` by the engine so the tool
    can access the current workflow runtime context.
    """

    def __call__(self, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch ``tool_id.action`` with ``params`` and return the result dict."""
        ...
