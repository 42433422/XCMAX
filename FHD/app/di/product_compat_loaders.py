"""Composition-root loaders for the legacy product compatibility routes.

The protocols stay in ``app.domain.product.product_compat_ports``; resolving the
concrete implementations is a composition concern and must not live in domain.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain.product.product_compat_ports import (
    BusinessVisibility,
    Payload,
    ProductAgentRuntime,
    ProductListDispatcher,
    ProductLookup,
    ProductServiceFacade,
)


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
