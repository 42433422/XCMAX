"""Typed, lazy dependencies used by the legacy product request flows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from app.domain.workflow.plan_graph import PlanGraph

Payload = dict[str, Any]


class ProductListDispatcher(Protocol):
    def __call__(
        self,
        domain: str,
        action: str,
        *,
        request: Request,
        page: int,
        per_page: int,
        keyword: str | None,
        unit: str | None,
    ) -> Payload | None: ...


class ProductServiceFacade(Protocol):
    def is_erp_products_via_service_enabled(self) -> bool: ...

    def products_list(
        self,
        request: Request,
        *,
        page: int,
        per_page: int,
        keyword: str | None,
        unit: str | None,
    ) -> Payload: ...

    def products_get(self, request: Request, product_id: int) -> Payload | JSONResponse: ...


class ProductLookup(Protocol):
    def get_product(self, product_id: int) -> Payload: ...


class AgentStepView(Protocol):
    @property
    def node_id(self) -> str: ...

    @property
    def output(self) -> Mapping[str, Any]: ...


class AgentRunView(Protocol):
    @property
    def final_output(self) -> Mapping[str, Any]: ...

    @property
    def steps(self) -> Sequence[AgentStepView]: ...

    @property
    def error(self) -> str: ...

    @property
    def run_id(self) -> str: ...

    @property
    def status(self) -> str: ...


class ProductAgentRuntime(Protocol):
    def start_run_from_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: PlanGraph,
        runtime_context: Payload | None = None,
    ) -> AgentRunView: ...

    def continue_run(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        runtime_context: Payload | None = None,
    ) -> AgentRunView | None: ...


class ProductAgentCall(Protocol):
    def __call__(
        self,
        *,
        request: Request,
        action: str,
        params: Payload,
        route_path: str,
    ) -> Payload: ...


class BusinessVisibility(Protocol):
    def business_data_exposed(self) -> bool: ...

    def business_data_hidden_reason(self) -> str | None: ...

