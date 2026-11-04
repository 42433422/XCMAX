"""Small callable interfaces between the HTTP adapter and its services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.workflow.workflow_types import PlanGraph

AccessResolver = Callable[[Request], DatasetAccessContext | None]


class DatasetAction(Protocol):
    def __call__(
        self, *, request: Request, action: str, params: dict[str, Any], route_path: str
    ) -> JSONResponse: ...


class MemoryResponse(Protocol):
    def __call__(
        self, payload: dict[str, Any], *, request: Request, action: str
    ) -> JSONResponse: ...


class RecallMerger(Protocol):
    def __call__(
        self, payload: dict[str, Any], *, request: Request, params: dict[str, Any]
    ) -> dict[str, Any]: ...


class AgentRuntime(Protocol):
    def start_run_from_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun: ...
    def continue_run(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None: ...
