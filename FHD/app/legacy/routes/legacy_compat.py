"""Legacy compat route mount phase.

Refactored from single 241-line god function into domain-focused sub-registration
functions. Mount order is preserved exactly (critical for market_account and
legacy_auth to mount before xcagi_compat / SPA fallback).
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Literal

from fastapi import FastAPI

from app.legacy.routes.legacy_gap import register_legacy_gap_routers
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# Error strategy for _mount_router:
#   "bare"    — let all errors propagate (original inline mount, no try/except)
#   "broad"   — catch RECOVERABLE_ERRORS, log warning (original try/except RECOVERABLE_ERRORS)
#   "narrow"  — catch (ImportError, AttributeError), log warning (original try/except ImportError)
MountStrategy = Literal["bare", "broad", "narrow"]

_NARROW_ERRORS: tuple[type[BaseException], ...] = (ImportError, AttributeError)


def is_ci_strict() -> bool:
    """Lazy compatibility seam that avoids importing the route package during mount bootstrap."""
    from app.fastapi_routes._route_helpers import is_ci_strict as _is_ci_strict

    return _is_ci_strict()


def _import_and_mount(app: FastAPI, module_path: str, router_attr: str, prefix: str) -> None:
    """Import module and mount router (no error handling — caller decides strategy)."""
    module = importlib.import_module(module_path)
    router = getattr(module, router_attr)
    if prefix:
        app.include_router(router, prefix=prefix)
    else:
        app.include_router(router)


def _mount_router(
    app: FastAPI,
    module_path: str,
    *,
    router_attr: str = "router",
    log_name: str | None = None,
    prefix: str = "",
    strategy: MountStrategy = "bare",
) -> None:
    """Import and mount a router onto app with the specified error strategy.

    Preserves the deferred-import behavior of the original inline ``from ... import``
    statements: the import happens at call time, not at module load time.

    Args:
        app: FastAPI app to mount onto.
        module_path: Dotted module path, e.g. ``app.fastapi_routes.market_account``.
        router_attr: Attribute name holding the router (default ``router``).
        log_name: Human-readable name for logging (defaults to module's last segment).
        prefix: Optional prefix for ``include_router``.
        strategy: Error handling strategy — see ``MountStrategy``.
    """
    name = log_name or module_path.rsplit(".", 1)[-1]
    if strategy == "bare":
        _import_and_mount(app, module_path, router_attr, prefix)
        logger.info("Registered %s", name)
    elif strategy == "broad":
        try:
            _import_and_mount(app, module_path, router_attr, prefix)
            logger.info("Registered %s", name)
        except RECOVERABLE_ERRORS as e:
            logger.warning("%s routes skipped: %s", name, e)
    else:  # narrow
        try:
            _import_and_mount(app, module_path, router_attr, prefix)
            logger.info("Registered %s", name)
        except _NARROW_ERRORS as e:
            logger.warning("%s routes skipped: %s", name, e)


def _register_compat_func(
    app: FastAPI,
    module_path: str,
    *,
    register_func_name: str,
    log_name: str | None = None,
) -> None:
    """Import and call a ``register_*_routes(app)`` function, swallowing recoverable errors.

    Used for compat modules that expose a registration function rather than a router
    attribute (private_db_read_assistant, xcmax_personnel, user_cs_wechat_passive).
    """
    name = log_name or module_path.rsplit(".", 1)[-1]
    try:
        module = importlib.import_module(module_path)
        register_func = getattr(module, register_func_name)
        register_func(app)
    except RECOVERABLE_ERRORS as e:
        logger.warning("%s compat routes skipped: %s", name, e)


# ---------------------------------------------------------------------------
# Domain-specific sub-registration functions.
# Mount order within each function is preserved from the original god function.
# ---------------------------------------------------------------------------


def _register_early_critical_routes(app: FastAPI) -> None:
    """Mount routers that must register before xcagi_compat / SPA fallback.

    Ordering constraints (from original docstrings):
    - market_account must mount before xcagi_compat (avoids /api/market/* mismatch).
    - legacy_auth must mount before SPA fallback (avoids /api/auth/session/validate 404).
    """
    # market_account — bare mount, must be first
    _mount_router(
        app,
        "app.fastapi_routes.market_account",
        log_name="market_account (/api/market/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.fhd_meta",
        log_name="fhd_meta_router (/api/fhd/db-tokens/status)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.debug_client_log",
        log_name="debug_client_log_router (/api/debug/client-log)",
    )

    # legacy_auth — bare mount, must mount before xcagi_compat / SPA fallback
    _mount_router(
        app,
        "app.fastapi_routes.domains.auth.routes",
        router_attr="router",
        log_name="legacy_auth_router early (/api/auth/*)",
    )

    # system_routes — narrow catch (ImportError, AttributeError)
    _mount_router(
        app,
        "app.fastapi_routes.system_routes",
        log_name="system_router early (/api/system/*)",
        strategy="narrow",
    )

    _mount_router(
        app,
        "app.fastapi_routes.code_editor",
        log_name="code_editor_router (/api/code-editor/*)",
    )


def _register_wechat_compat_routes(app: FastAPI) -> None:
    """Mount wechat / personnel compat routes (register_*_routes pattern + wechat_decrypt)."""
    _register_compat_func(
        app,
        "app.fastapi_routes.private_db_read_assistant_compat",
        register_func_name="register_private_db_read_assistant_routes",
    )

    _register_compat_func(
        app,
        "app.fastapi_routes.xcmax_personnel_compat",
        register_func_name="register_xcmax_personnel_routes",
    )

    _register_compat_func(
        app,
        "app.fastapi_routes.user_cs_wechat_passive_compat",
        register_func_name="register_user_cs_wechat_passive_routes",
    )

    _mount_router(
        app,
        "app.fastapi_routes.wechat_decrypt_routes",
        log_name="wechat_decrypt_router (/api/wechat/decrypt/*)",
        strategy="broad",
    )


def _register_xcagi_compat_routes(app: FastAPI) -> None:
    """Mount xcagi_compat aggregator (prefix=/api). Must come after early critical routes."""
    _mount_router(
        app,
        "app.fastapi_routes.xcagi_compat",
        log_name="xcagi_compat_router (prefix=/api)",
        prefix="/api",
    )


def _register_document_routes(app: FastAPI) -> None:
    """Mount document/template routes."""
    _mount_router(
        app,
        "app.fastapi_routes.document_templates",
        router_attr="public_router",
        log_name="document_templates public_router (/api/document-templates)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.xcagi_startup",
        log_name="xcagi_startup_router (/api/startup/status)",
        prefix="/api",
    )

    _mount_router(
        app,
        "app.fastapi_routes.template_api",
        log_name="template_api router (/api/templates*)",
    )


def _register_shipment_routes(app: FastAPI) -> None:
    """Mount shipment/materials/upload/ocr/print routes."""
    _mount_router(
        app,
        "app.fastapi_routes.shipment_orders",
        log_name="shipment_orders (/api/orders*, /api/shipment/shipment-records/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.materials",
        log_name="materials (/api/materials*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.upload",
        log_name="upload (/api/upload/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.ocr",
        log_name="ocr (/api/ocr/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.print_routes",
        log_name="print_routes (/api/print/*)",
    )


def _register_ai_routes(app: FastAPI) -> None:
    """Mount AI assistant/intent/kitten/qclaw/open routes."""
    _mount_router(
        app,
        "app.fastapi_routes.ai_assistant",
        log_name="ai_assistant (/health, /api/generate, /api/shipment-records/*, ...)",
    )

    # tts_install — Windows-only optional, broad catch
    _mount_router(
        app,
        "app.fastapi_routes.tts_install",
        log_name="tts_install (/api/tts/install-system-voice)",
        strategy="broad",
    )

    _mount_router(
        app,
        "app.fastapi_routes.ai_intent",
        log_name="ai_intent (/api/ai/test, /api/ai/chat-unified*, /api/ai/intent/test, /api/intent/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.ai_kitten",
        log_name="ai_kitten (/api/ai/kitten/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.ai_qclaw",
        log_name="ai_qclaw (/api/ai/qclaw/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.ai_open",
        log_name="ai_open (/api/aiopen/*)",
    )


def _register_excel_routes(app: FastAPI) -> None:
    """Mount excel templates/extract/vector routes."""
    _mount_router(
        app,
        "app.fastapi_routes.excel_templates",
        log_name="excel_templates (/api/excel/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.excel_extract",
        log_name="excel_extract (/api/excel/data/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.excel_vector",
        log_name="excel_vector (/api/excel/vector/*)",
    )


def _register_infra_routes(app: FastAPI) -> None:
    """Mount health/state infrastructure routes."""
    _mount_router(
        app,
        "app.fastapi_routes.health_k8s",
        log_name="health_k8s (/health/liveness|readiness|details)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.state",
        log_name="state (/api/state/*)",
    )


def _register_payment_routes(app: FastAPI) -> None:
    """Mount payment/contract/operations routes."""
    # model_payment — broad catch
    _mount_router(
        app,
        "app.fastapi_routes.model_payment",
        log_name="model_payment (/api/model-payment/*)",
        strategy="broad",
    )

    _mount_router(
        app,
        "app.fastapi_routes.payment_reconcile_internal_api",
        log_name="payment_reconcile_internal (/api/internal/payment/*)",
    )

    _mount_router(
        app,
        "app.fastapi_routes.sales_contract_api",
        log_name="sales_contract (/api/sales-contract/*)",
    )

    # contract_lifecycle — narrow catch (ImportError)
    _mount_router(
        app,
        "app.fastapi_routes.contract_lifecycle_api",
        log_name="contract_lifecycle (/api/contract-lifecycle/*)",
        strategy="narrow",
    )

    _mount_router(
        app,
        "app.fastapi_routes.operations_line_api",
        log_name="operations_line (/api/operations-line/*)",
    )


def _register_legacy_gap_if_enabled(app: FastAPI) -> None:
    """Mount legacy_gap domain routers if XCAGI_REGISTER_LEGACY_ROUTES env is set.

    legacy_gap routers are superseded by xcagi_compat (SSOT) — no double-mount.
    Force-only via XCAGI_REGISTER_LEGACY_ROUTES=1 for migration debugging.
    """
    if os.environ.get("XCAGI_REGISTER_LEGACY_ROUTES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        register_legacy_gap_routers(app)
        logger.warning(
            "legacy gap routers mounted (XCAGI_REGISTER_LEGACY_ROUTES=1); "
            "may duplicate xcagi_compat routes"
        )


def _register_approval_routes(app: FastAPI) -> None:
    """Mount approval and service_bridge routes.

    service_bridge has special CI-strict behavior: in CI, failure raises RuntimeError;
    outside CI, failure logs a warning.
    """
    _mount_router(
        app,
        "app.fastapi_routes.approval",
        log_name="approval (/api/approval/requests*, /api/approval/flows*)",
    )

    # service_bridge — broad catch + CI strict check
    try:
        from app.fastapi_routes.service_bridge import router as service_bridge_router

        app.include_router(service_bridge_router)
        logger.info("Registered service_bridge (/api/service-bridge/*)")
    except RECOVERABLE_ERRORS as exc:
        if is_ci_strict():
            raise RuntimeError("service_bridge router required in CI") from exc
        logger.warning("service_bridge router not available: %s", exc)


# ---------------------------------------------------------------------------
# Main entry point — thin orchestrator preserving exact mount order.
# ---------------------------------------------------------------------------


def register_legacy_compat_routes(app: FastAPI) -> None:
    """注册 XCAGI 前端依赖的历史兼容路由(原 backend.routers.*,2026-04-20 已全部迁至本包)。

    ``xcagi_compat`` 路由注册顺序说明:
    主站 Vue 依赖 xcagi_compat(Planner / run_agent_chat)的 JSON 契约与错误语义。

    Mount order is critical:
    1. early_critical — market_account + legacy_auth must precede xcagi_compat
    2. wechat_compat — compat register functions
    3. xcagi_compat — aggregator (prefix=/api)
    4. document / shipment / ai / excel / infra / payment — business domains
    5. legacy_gap — conditional (debug only)
    6. approval + service_bridge — must mount last (service_bridge CI-strict)
    """
    _register_early_critical_routes(app)
    _register_wechat_compat_routes(app)
    _register_xcagi_compat_routes(app)
    _register_document_routes(app)
    _register_shipment_routes(app)
    _register_ai_routes(app)
    _register_excel_routes(app)
    _register_infra_routes(app)
    _register_payment_routes(app)
    _register_legacy_gap_if_enabled(app)
    _register_approval_routes(app)
