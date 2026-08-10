"""EventBus/StateEvent ports — contract for workflow state events.

The application workflow layer emits ``state.update`` events as nodes complete
(see ``WorkflowEngine._emit_state_update``). It must not import ``app.neuro_bus``
directly; instead it depends on ``StateEventPublisher`` here, which is bridged
to NeuroBus by an infrastructure adapter (``neuro_bus_bridge``).

The payload DTOs below are plain ``dataclasses`` + ``TypedDict`` — no
``app.neuro_bus`` / ``langgraph`` / ``sqlalchemy`` / ``fastapi`` imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

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