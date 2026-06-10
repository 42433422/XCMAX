"""Advanced workflow orchestration: parallel + dynamic + event-triggered.

The base :class:`vibe_coding.workflow_engine.VibeWorkflowEngine` is a
clean DAG executor — perfect for "weather → dressing recommendation"
chains but limited when you need:

- **Parallel groups** — fan out to N independent skills, gather all
  their outputs, continue when *any*/*all*/*at-least-K* finish.
- **Dynamic subgraphs** — a planner node returns a list of follow-up
  tasks; the executor spawns them on the fly without needing a static
  graph.
- **Event-triggered nodes** — wait for an external signal (webhook,
  cron, user approval, file watcher, …) before continuing.
- **Async execution** — one event loop drives everything, IO-bound
  nodes don't block CPU-bound ones.

These features live here as **opt-in** alongside the existing
synchronous engine. Choose the executor that matches your job; the
node API is intentionally compatible with :class:`VibeWorkflowNode`
so callers can mix DAG and advanced workflows freely.
"""

from __future__ import annotations

from .events import EventBus, WorkflowEvent
from .executor import (
    AdvancedWorkflowExecutor,
    AsyncWorkflowExecutor,
    NodeExecution,
    WorkflowExecution,
)
from .graph import (
    AdvancedNode,
    AdvancedWorkflow,
    DynamicSpawn,
    NodeKind,
    ParallelGroup,
    TriggerSpec,
)

__all__ = [
    "AdvancedNode",
    "AdvancedWorkflow",
    "AdvancedWorkflowExecutor",
    "AsyncWorkflowExecutor",
    "DynamicSpawn",
    "EventBus",
    "NodeExecution",
    "NodeKind",
    "ParallelGroup",
    "TriggerSpec",
    "WorkflowEvent",
    "WorkflowExecution",
]
