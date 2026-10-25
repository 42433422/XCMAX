"""Lightweight saga coordinator for multi-agent workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.utils.operational_errors import BOUNDARY_ERRORS


@dataclass
class SagaStep:
    name: str
    action: Callable[[dict[str, Any]], Any]
    compensate: Callable[[dict[str, Any]], Any] | None = None


@dataclass
class SagaResult:
    ok: bool
    completed: list[str] = field(default_factory=list)
    error: str | None = None


class OrchestrationSaga:
    def __init__(self, steps: list[SagaStep]) -> None:
        self.steps = steps

    def run(self, context: dict[str, Any]) -> SagaResult:
        completed: list[str] = []
        for step in self.steps:
            try:
                step.action(context)
                completed.append(step.name)
            except BOUNDARY_ERRORS as exc:
                for name in reversed(completed):
                    comp = next((s.compensate for s in self.steps if s.name == name), None)
                    if comp:
                        try:
                            comp(context)
                        except BOUNDARY_ERRORS:
                            pass
                return SagaResult(ok=False, completed=completed, error=str(exc))
        return SagaResult(ok=True, completed=completed)
