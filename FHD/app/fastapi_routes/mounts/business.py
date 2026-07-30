"""Route mount: business routers via RouteRegistry."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from app.fastapi_routes._route_helpers import is_ci_strict
from app.fastapi_routes.registry import RouteRegistry
from app.runtime_integrity import record_runtime_component
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DESKTOP_REQUIRED_ROUTES = {
    "purchase",
    "inventory",
    "finance",
    "reports",
    "mods",
    "system",
    "workspace_prefs",
    "business_bridge",
    "mod_store",
    "etl",
}


def _mod_taiyangniao_pro_exposes_attendance_api() -> bool:
    """仅当 taiyangniao-pro 的 /api/mod/* 已实际挂载时，跳过宿主 compat 层。"""
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        return "taiyangniao-pro" in get_mod_manager()._http_routes_registered
    except RECOVERABLE_ERRORS:
        return False


def _bundled_taiyangniao_pro_exposes_attendance_api() -> bool:
    """Detect the bundled taiyangniao-pro blueprint before Mod routes are mounted."""
    fhd_root = Path(__file__).resolve().parents[3]
    candidates = (
        fhd_root / "mods" / "taiyangniao-pro" / "backend" / "blueprints.py",
        fhd_root / "XCAGI" / "mods" / "taiyangniao-pro" / "backend" / "blueprints.py",
    )
    for file_path in candidates:
        try:
            if not file_path.is_file():
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if (
            "register_fastapi_routes" in text
            and "/attendance/rules" in text
            and "/attendance/convert-upload" in text
            and "/attendance/download" in text
        ):
            return True
    return False


def _load_taiyangniao_attendance_compat_router():
    if (
        _mod_taiyangniao_pro_exposes_attendance_api()
        or _bundled_taiyangniao_pro_exposes_attendance_api()
    ):
        from fastapi import APIRouter

        logger.info(
            "Skip taiyangniao_attendance_compat routes: taiyangniao-pro mod already exposes attendance API"
        )
        return APIRouter(tags=["sunbird-attendance-compat-skipped"])
    return __import__(
        "app.fastapi_routes.taiyangniao_attendance_compat", fromlist=["router"]
    ).router


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
        if registry.app is not None:
            record_runtime_component(
                registry.app,
                f"business_route:{name}",
                ok=True,
                required=name in _DESKTOP_REQUIRED_ROUTES,
            )
    except RECOVERABLE_ERRORS as exc:
        if is_ci_strict() and required_in_ci:
            raise RuntimeError(f"Required route mount failed in CI: {name}") from exc
        if registry.app is not None:
            record_runtime_component(
                registry.app,
                f"business_route:{name}",
                ok=False,
                required=name in _DESKTOP_REQUIRED_ROUTES,
                detail=str(exc),
            )
        logger.warning("%s not available: %s", name, exc)


def register_business_routes(app: FastAPI, registry: RouteRegistry) -> None:
    """Register business API routers (deduplicated via registry)."""
    if registry.app is None:
        registry.app = app

    _mount(
        registry,
        "xcmax_admin",
        lambda: __import__("app.fastapi_routes.xcmax_admin", fromlist=["router"]).router,
        priority=10,
    )
    _mount(
        registry,
        "founder_autonomy",
        lambda: __import__("app.fastapi_routes.founder_autonomy_api", fromlist=["router"]).router,
        priority=10,
        required_in_ci=True,
    )
    _mount(
        registry,
        "ops_autonomy",
        lambda: __import__("app.fastapi_routes.ops_autonomy", fromlist=["router"]).router,
        priority=10,
        required_in_ci=True,
    )
    _mount(
        registry,
        "admin_audit",
        lambda: (
            __import__("app.fastapi_routes.domains.admin_audit.routes", fromlist=["router"]).router
        ),
        priority=10,
    )
    _mount(
        registry,
        "genai_traces",
        lambda: (
            __import__("app.fastapi_routes.domains.genai_traces.routes", fromlist=["router"]).router
        ),
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
        "agent",
        lambda: __import__("app.fastapi_routes.domains.agent.routes", fromlist=["router"]).router,
        priority=12,
    )
    _mount(
        registry,
        "system",
        lambda: __import__("app.fastapi_routes.domains.system.routes", fromlist=["router"]).router,
        priority=12,
        required_in_ci=True,
    )
    _mount(
        registry,
        "knowledge_v1",
        lambda: __import__("app.fastapi_routes.knowledge_v1", fromlist=["router"]).router,
        priority=13,
    )
    _mount(
        registry,
        "etl",
        lambda: __import__("app.fastapi_routes.etl", fromlist=["router"]).router,
        priority=13,
        required_in_ci=True,
    )
    _mount(
        registry,
        "etl_targets",
        lambda: __import__("app.fastapi_routes.etl_targets", fromlist=["router"]).router,
        priority=13,
        required_in_ci=True,
    )
    _mount(
        registry,
        "taiyangniao_attendance_compat",
        _load_taiyangniao_attendance_compat_router,
        priority=14,
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
        "workspace_prefs",
        lambda: __import__("app.fastapi_routes.workspace_prefs_routes", fromlist=["router"]).router,
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
        "im_v0",
        lambda: __import__("app.fastapi_routes.im_routes", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "internal_im",
        lambda: __import__("app.fastapi_routes.internal_im", fromlist=["router"]).router,
    )
    _mount(
        registry,
        "production_line_event",
        lambda: (
            __import__(
                "app.fastapi_routes.production_line_event_api",
                fromlist=["admin_router"],
            ).admin_router
        ),
    )
    _mount(
        registry,
        "production_line_event_xcmax",
        lambda: (
            __import__(
                "app.fastapi_routes.production_line_event_api",
                fromlist=["xcmax_router"],
            ).xcmax_router
        ),
    )
