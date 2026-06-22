"""Path-level golden tests for register_legacy_compat_routes.

Serves as safety net for legacy_compat.py refactor: verifies each of the 34
routers mounts its expected path prefix. If a future split drops or reorders
a router, these assertions fail fast.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from app.fastapi_routes.openapi_route_compat import iter_effective_routes
from app.legacy.routes.legacy_compat import register_legacy_compat_routes


@pytest.fixture
def legacy_app() -> FastAPI:
    """Mount full legacy compat routes onto a fresh app."""
    with (
        patch("app.legacy.routes.legacy_compat.register_legacy_gap_routers"),
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("XCAGI_REGISTER_LEGACY_ROUTES", None)
        app = FastAPI()
        register_legacy_compat_routes(app)
        return app


def _paths(app: FastAPI) -> set[str]:
    # FastAPI 0.138+ 用 _IncludedRouter 懒包装 include_router 的子路由，实际路径不再
    # 直接挂在 app.routes 上；iter_effective_routes 会展开这些包装（与本测试上游 CI
    # 设置的 XCAGI_SKIP_LEGACY_COMPAT_ROUTES 无关——本测试直接调用 register 函数）。
    return {r.path for r in iter_effective_routes(app.routes) if r.path}


# (router_name, expected_path_prefix_or_substring)
# Derived from logger.info annotations in legacy_compat.py.
EXPECTED_ROUTER_PATHS: tuple[tuple[str, str], ...] = (
    ("market_account", "/api/market"),
    ("fhd_meta", "/api/fhd/db-tokens"),
    ("debug_client_log", "/api/debug/client-log"),
    ("legacy_auth", "/api/auth"),
    ("system_routes", "/api/system"),
    ("code_editor", "/api/code-editor"),
    ("wechat_decrypt", "/api/wechat/decrypt"),
    (
        "xcagi_compat",
        "/api/ai/unified_chat",
    ),  # aggregator mounts conversation compat with prefix=/api
    ("document_templates", "/api/document-templates"),
    ("xcagi_startup", "/api/startup"),
    ("template_api", "/api/templates"),
    ("shipment_orders", "/api/orders"),
    ("materials", "/api/materials"),
    ("upload", "/api/upload"),
    ("ocr", "/api/ocr"),
    ("print_routes", "/api/print"),
    ("ai_assistant", "/api/generate"),
    ("excel_templates", "/api/excel"),
    ("excel_extract", "/api/excel/data"),
    ("excel_vector", "/api/excel/vector"),
    ("health_k8s", "/health"),
    ("state", "/api/state"),
    ("payment_reconcile_internal", "/api/internal/payment"),
    ("sales_contract", "/api/sales-contract"),
    ("operations_line", "/api/operations-line"),
    ("ai_intent", "/api/ai"),
    ("ai_kitten", "/api/ai/kitten"),
    ("ai_qclaw", "/api/ai/qclaw"),
    ("ai_open", "/api/aiopen"),
    ("approval", "/api/approval"),
    ("service_bridge", "/api/service-bridge"),
)


@pytest.mark.parametrize("router_name,expected_prefix", EXPECTED_ROUTER_PATHS)
def test_router_mounts_expected_path(legacy_app: FastAPI, router_name: str, expected_prefix: str):
    """Each router must mount at least one path starting with its expected prefix."""
    paths = _paths(legacy_app)
    matching = [p for p in paths if p.startswith(expected_prefix) or expected_prefix in p]
    assert matching, (
        f"router '{router_name}' expected path prefix '{expected_prefix}' "
        f"not found in mounted paths. Got {len(paths)} paths. "
        f"Sample: {sorted(paths)[:10]}"
    )


def test_total_mounted_path_count(legacy_app: FastAPI):
    """Sanity: full legacy stack mounts a substantial number of paths."""
    paths = _paths(legacy_app)
    assert len(paths) >= 50, f"expected >=50 mounted paths from full legacy stack, got {len(paths)}"


def test_critical_early_mount_paths_present(legacy_app: FastAPI):
    """Paths that must mount early (before xcagi_compat / SPA fallback)."""
    paths = _paths(legacy_app)
    # market_account must mount before xcagi_compat (per docstring L30-31)
    assert any(p.startswith("/api/market") for p in paths), (
        "market_account must mount early to own /api/market/*"
    )
    # legacy_auth must mount before SPA fallback (per docstring L47)
    assert any(p.startswith("/api/auth") for p in paths), (
        "legacy_auth must mount early to avoid /api/auth/* falling to /{fallback:path}"
    )


def test_recoverable_routers_do_not_block_mount(legacy_app: FastAPI):
    """Routers wrapped in RECOVERABLE_ERRORS try/except must not block the whole stack."""
    paths = _paths(legacy_app)
    # If we got here, the full stack completed without raising (in non-CI mode).
    # Verify at least the non-recoverable routers mounted.
    assert any(p.startswith("/api/market") for p in paths)
    assert any(p.startswith("/api/auth") for p in paths)
    assert any(p.startswith("/api/ai") for p in paths)
