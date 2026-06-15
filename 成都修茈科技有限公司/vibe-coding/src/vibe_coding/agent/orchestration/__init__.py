"""Multi-agent orchestration: Planner / Coder / Reviewer / Researcher.

Single :class:`ProjectVibeCoder` is enough for "edit one file" tasks.
For larger jobs (rewrite a module, migrate an API surface, build a
mini-project from scratch) it pays to split the work between
specialised LLM-backed roles that share state via an event bus.

The package ships two models:

1. **Sequential pipeline** (``MultiAgentOrchestrator``) — run roles in
   a fixed order with feedback loops:

       brief → Planner → Researcher? → Coder → Reviewer → ✓ / loop

   The orchestrator handles message routing, retry budgets, deadlocks
   and (optionally) memory writes for the underlying skills.

2. **Parallel best-of-N** (``BestOfNOrchestrator``) — fan out to
   several Coders, ask the Reviewer to pick the strongest patch, and
   commit only that one. Useful when the brief has multiple plausible
   approaches.

All roles share the :class:`AgentRole` Protocol so callers can drop in
custom agents (e.g. a Documentation agent that fills in docstrings
after the Coder is done).
"""

from __future__ import annotations

from .messages import AgentMessage, AgentTask, MessageBus
from .roles import (
    AgentRole,
    CoderAgent,
    PlannerAgent,
    ResearcherAgent,
    ReviewerAgent,
    TesterAgent,
)
from .coordinator import (
    BestOfNOrchestrator,
    MultiAgentOrchestrator,
    OrchestrationResult,
)

__all__ = [
    "AgentMessage",
    "AgentRole",
    "AgentTask",
    "BestOfNOrchestrator",
    "CoderAgent",
    "MessageBus",
    "MultiAgentOrchestrator",
    "OrchestrationResult",
    "PlannerAgent",
    "ResearcherAgent",
    "ReviewerAgent",
    "TesterAgent",
]
