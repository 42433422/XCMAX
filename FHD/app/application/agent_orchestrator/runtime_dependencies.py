"""Explicit runtime ports shared by planning, tool execution and bounded repair."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult


@dataclass(frozen=True)
class RuntimeDependencies:
    action_spec: Callable[[str, str], ToolActionSpecV2 | None]
    validate: Callable[[str, str, dict[str, Any]], ToolValidationResult]
    refresh_budget: Callable[[AgentRun], None]
    repair_enabled: Callable[[AgentRun, dict[str, Any]], bool]
    repair_limit: Callable[[AgentRun, AgentStep, dict[str, Any]], int]
    request_repair: Callable[[AgentRun, AgentStep, dict[str, Any]], dict[str, Any]]


class ArtifactSink(Protocol):
    def __call__(
        self,
        run: AgentRun,
        payload: Any,
        *,
        source: str,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None: ...


class ObservationSink(Protocol):
    def __call__(
        self, run: AgentRun, step: AgentStep, *, tool_call: ToolCall, success: bool
    ) -> dict[str, Any]: ...
