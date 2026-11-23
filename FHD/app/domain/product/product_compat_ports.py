"""Typed, lazy dependencies used by the legacy product request flows."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

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


class ProductAgentCall(Protocol):
    def __call__(
        self,
        *,
        request: Request,
        action: str,
        params: Payload,
        route_path: str,
    ) -> tuple[Payload, int]: ...


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


def load_business_visibility() -> BusinessVisibility:
    from app.shell import mod_business_scope

    return mod_business_scope
