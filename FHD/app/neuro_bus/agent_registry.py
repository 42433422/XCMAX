"""Multi-agent registry for NeuroBus orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class AgentSpec:
    agent_id: str
    capabilities: frozenset[str]
    handler: Callable[..., object] | None = None


@dataclass
class AgentRegistry:
    _agents: dict[str, AgentSpec] = field(default_factory=dict)

    def register(self, spec: AgentSpec) -> None:
        self._agents[spec.agent_id] = spec

    def get(self, agent_id: str) -> AgentSpec | None:
        return self._agents.get(agent_id)

    def by_capability(self, capability: str) -> list[AgentSpec]:
        return [a for a in self._agents.values() if capability in a.capabilities]

    def list_ids(self) -> list[str]:
        return sorted(self._agents)
