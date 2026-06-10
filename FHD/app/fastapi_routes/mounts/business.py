"""Route mount: business routers via RouteRegistry."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.fastapi_routes._route_helpers import is_ci_strict
from app.fastapi_routes.registry import RouteRegistry
from app.utils.operational_errors import OPERATIONAL_ERRORS

logger = logging.getLogger(__name__)


def _mount(
    registry: RouteRegistry,
    name: str,
    loader,
    *,
    priority: int = 50,
    prefix: str | None = None,
    tags: list[str] | None = None,
    required_in_ci: bool = False,
    **kwargs,
) -> None:
    try:
        router = loader()
        registry.register_router(
            name,
            router,
            priority=priority,
            prefix=prefix,
            tags=tags,
            **kwargs,
        )
    except OPERATIONAL_ERRORS as exc:
        if is_ci_strict() and required_in_ci:
            raise RuntimeError(f"Required route mount failed in CI: {name}") from exc
        logger.warning("%s not available: %s", name, exc)


def register_business_routes(app: FastAPI, registry: RouteRegistry) -> None:
    """Register business API routers (deduplicated via registry)."""
    del app  # business phase uses registry.apply in __init__

    _mount(
        registry,
        "xcmax_admin",
        lambda: __import__("app.fastapi_routes.xcmax_admin", fromlist=["router"]).router,
        priority=10,
    )
    _mount(
        registry,
        "aibiz_terminal",
        lambda: __import__("app.fastapi_routes.aibiz_terminal_api", fromlist=["router"]).router,
        priority=11,
    )
    _mount(
        registry,
        "purchase",
        lambda: __import__("app.fastapi_routes.purchase", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "inventory",
        lambda: __import__("app.fastapi_routes.inventory", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "finance_unified_ledger",
        lambda: __import__("app.fastapi_routes.finance_unified_ledger", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "finance_invoices",
        lambda: __import__("app.fastapi_routes.finance_invoices_api", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "finance",
        lambda: __import__("app.fastapi_routes.finance", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "reports",
        lambda: __import__("app.fastapi_routes.reports", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "rbac",
        lambda: __import__("app.fastapi_routes.rbac", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "mods",
        lambda: __import__(
            "app.fastapi_routes.mods_routes", fromlist=["get_mods_router"]
        ).get_mods_router(),
    )
    _mount(
        registry,
        "platform_shell",
        lambda: __import__("app.fastapi_routes.platform_shell_routes", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "business_bridge",
        lambda: __import__("app.fastapi_routes.business_api", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "mod_store",
        lambda: __import__("app.fastapi_routes.mod_store_routes", fromlist=["router"]).router,
        prefix="/api/mod-store",
    )
    _mount(
        registry,
        "control",
        lambda: __import__("app.control.routes", fromlist=["router"]).router,
        prefix="/api/control",
        tags=["control"],
    )
    _mount(
        registry,
        "voice",
        lambda: __import__("app.fastapi_routes.voice_routes", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "mobile_api",
        lambda: __import__("app.fastapi_routes.mobile_api", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "production_line_event",
        lambda: __import__(
            "app.fastapi_routes.production_line_event_api",
            fromlist=["admin_router"],
        ).admin_router,
    )
    _mount(
        registry,
        "production_line_event_xcmax",
        lambda: __import__(
            "app.fastapi_routes.production_line_event_api",
            fromlist=["xcmax_router"],
        ).xcmax_router,
    )
