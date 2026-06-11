"""Advanced workflow graph data model.

Compared to the base :class:`VibeWorkflowGraph` the advanced model
supports four extra node kinds:

- :class:`NodeKind.task` — same as the base; runs a single skill or
  callable.
- :class:`NodeKind.parallel` — wraps a :class:`ParallelGroup`; the
  group's children execute concurrently and the parent's output
  aggregates them.
- :class:`NodeKind.spawn` — dynamic subgraph. The node's runner returns
  a list of follow-up :class:`AdvancedNode` instances; the executor
  splices them into the live graph.
- :class:`NodeKind.event` — waits on a :class:`TriggerSpec` (an external
  signal published to the :class:`EventBus`).

Edges retain the base ``condition`` field so DAG-style guards still
work. ``inputs`` lets a node pull arbitrary fields from upstream
outputs into its kwargs (the base engine only forwards via the run
context).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

NodeRunner = Callable[[dict[str, Any], "WorkflowExecution"], dict[str, Any]]
"""Sync runner signature: (input_kwargs, execution_state) -> output_dict."""


class NodeKind(str, enum.Enum):
    task = "task"
    parallel = "parallel"
    spawn = "spawn"
    event = "event"


@dataclass(slots=True)
class TriggerSpec:
    """Definition of an event-trigger node.

    The executor blocks on :meth:`EventBus.wait_for` (sync) or
    :meth:`EventBus.async_wait_for` (async) until an event matching
    the topic arrives. Optional ``filter_fn`` can reject events that
    don't satisfy a custom predicate (e.g. only react to webhook
    payloads with ``branch == "main"``).
    """

    topic: str
    timeout_s: float = 60.0
    filter_fn: Callable[[Any], bool] | None = None
    payload_key: str = "event_payload"

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "timeout_s": float(self.timeout_s),
            "payload_key": self.payload_key,
        }


@dataclass(slots=True)
class ParallelGroup:
    """A group of nodes that should run concurrently.

    ``mode`` controls when the group is considered done:

    - ``"all"`` (default) — every child must finish.
    - ``"any"`` — first child to finish wins; others are cancelled.
    - ``"at_least"`` — wait until ``threshold`` children succeed.
    """

    children: list["AdvancedNode"] = field(default_factory=list)
    mode: Literal["all", "any", "at_least"] = "all"
    threshold: int = 1
    fail_fast: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "children": [c.to_dict() for c in self.children],
            "mode": self.mode,
            "threshold": int(self.threshold),
            "fail_fast": bool(self.fail_fast),
        }


@dataclass(slots=True)
class DynamicSpawn:
    """Marker that a node spawns its successors at runtime.

    ``runner`` (or :attr:`AdvancedNode.runner`) returns a list of
    :class:`AdvancedNode` instances *plus* an output dict. The executor
    inserts the new nodes after the current one and runs them as
    normal task nodes.
    """

    inherit_inputs: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"inherit_inputs": bool(self.inherit_inputs)}


@dataclass(slots=True)
class AdvancedNode:
    """A node in an :class:`AdvancedWorkflow`.

    The ``runner`` callable is the unit of work; we don't depend on
    :class:`CodeSkillRuntime` so callers can wire any sync function.
    Use :class:`vibe_coding.agent.workflow_advanced.executor.skill_runner_for`
    to produce a runner that delegates to a :class:`CodeSkillRuntime`.
    """

    id: str
    kind: NodeKind = NodeKind.task
    runner: NodeRunner | None = None
    skill_id: str = ""
    inputs: dict[str, str] = field(default_factory=dict)
    timeout_s: float | None = None
    retries: int = 0
    parallel: ParallelGroup | None = None
    trigger: TriggerSpec | None = None
    spawn: DynamicSpawn | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            self.kind = NodeKind(self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "skill_id": self.skill_id,
            "inputs": dict(self.inputs),
            "timeout_s": self.timeout_s,
            "retries": int(self.retries),
            "parallel": self.parallel.to_dict() if self.parallel else None,
            "trigger": self.trigger.to_dict() if self.trigger else None,
            "spawn": self.spawn.to_dict() if self.spawn else None,
            "config": dict(self.config),
        }


@dataclass(slots=True)
class AdvancedEdge:
    """Edge with an optional condition expression."""

    source: str
    target: str
    condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "condition": self.condition}


@dataclass(slots=True)
class AdvancedWorkflow:
    """Top-level container — nodes + edges + entry points."""

    workflow_id: str
    nodes: list[AdvancedNode] = field(default_factory=list)
    edges: list[AdvancedEdge] = field(default_factory=list)
    entry_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "entry_nodes": list(self.entry_nodes),
        }

    def get_node(self, node_id: str) -> AdvancedNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def successors(self, node_id: str) -> list[str]:
        return [e.target for e in self.edges if e.source == node_id]

    def predecessors(self, node_id: str) -> list[str]:
        return [e.source for e in self.edges if e.target == node_id]


__all__ = [
    "AdvancedEdge",
    "AdvancedNode",
    "AdvancedWorkflow",
    "DynamicSpawn",
    "NodeKind",
    "NodeRunner",
    "ParallelGroup",
    "TriggerSpec",
]


# Forward-reference used in NodeRunner above; pylint stays happy.
class WorkflowExecution:  # pragma: no cover - sentinel
    pass
