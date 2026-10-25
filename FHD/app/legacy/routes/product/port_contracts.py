"""Typed, lazy dependencies used by the legacy product request flows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.workflow.types import PlanGraph

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


def load_product_dispatcher() -> ProductListDispatcher:
    from app.mod_sdk.erp_domain_dispatch import try_invoke_erp_domain_handler

    return try_invoke_erp_domain_handler


def load_product_service_facade() -> ProductServiceFacade:
    from app.mod_sdk import erp_products_facade

    return erp_products_facade


def load_product_lookup() -> ProductLookup:
    from app.bootstrap import get_products_service

    return get_products_service()


def create_product_agent() -> ProductAgentRuntime:
    from app.application.agent_orchestrator import AgentOrchestrator

    return AgentOrchestrator()


def load_product_registry() -> Payload:
    from app.application.workflow_registry_app import get_workflow_tool_registry

    return get_workflow_tool_registry()


def load_business_visibility() -> BusinessVisibility:
    from app.shell import mod_business_scope

    return mod_business_scope


def load_price_preview() -> Callable[[str | None], Payload]:
    from app.infrastructure.documents.price_list_export import (
        build_price_list_template_preview_json,
    )

    return build_price_list_template_preview_json
