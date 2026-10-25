"""Dispatch work items to registered agents via NeuroBus."""
from __future__ import annotations

from typing import Any

from app.neuro_bus.agent_registry import AgentRegistry, AgentSpec


class AgentDispatcher:
    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self.registry = registry or AgentRegistry()

    def register(self, spec: AgentSpec) -> None:
        self.registry.register(spec)

    def dispatch(self, capability: str, payload: dict[str, Any]) -> list[Any]:
        results: list[Any] = []
        for agent in self.registry.by_capability(capability):
            if agent.handler is None:
                continue
            results.append(agent.handler(payload))
        return results
