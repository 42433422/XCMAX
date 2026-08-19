# ruff: noqa: E402
"""FastAPI application factory.

Gateway note: payment proxy is wired in ``middleware_registry.register_all_middleware``
via ``_payment_backend_proxy_middleware`` wrapping ``payment_backend_proxy_middleware``.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from modstore_server.env_loader import load_modstore_env

_deploy_root = Path(__file__).resolve().parents[2]
_preserved_db_path = (os.environ.get("MODSTORE_DB_PATH") or "").strip()
load_modstore_env(
    _deploy_root,
    preserve_existing=(
        "MODSTORE_JWT_SECRET",
        "ALIPAY_APP_ID",
        "ALIPAY_APP_PRIVATE_KEY",
        "ALIPAY_APP_PRIVATE_KEY_PATH",
        "ALIPAY_ALIPAY_PUBLIC_KEY",
        "ALIPAY_ALIPAY_PUBLIC_KEY_PATH",
        "ALIPAY_NOTIFY_URL",
        "ALIPAY_DEBUG",
        "PAYMENT_SECRET_KEY",
        "PAYMENT_BACKEND",
    ),
)
if _preserved_db_path:
    os.environ["MODSTORE_DB_PATH"] = _preserved_db_path
if os.environ.get("MODSTORE_PYTEST_USE_SQLITE") == "1":
    os.environ.pop("DATABASE_URL", None)

from modstore_server.constants import DEFAULT_API_PORT, DEFAULT_XCAGI_BACKEND_URL
from modstore_server.api.app_config import AppConfig, load_default_config
from modstore_server.api.app_diagnostics import (
    maybe_mount_vibe_subapp as _maybe_mount_vibe_subapp,
    register_neurobus_diagnostics as _register_neurobus_diagnostics,
)
from modstore_server.api.app_metadata import OPENAPI_TAGS as _OPENAPI_TAGS

logger = logging.getLogger(__name__)


def _include_optional(app: FastAPI, module_path: str) -> None:
    try:
        mod = __import__(module_path, fromlist=["router"])
    except ImportError as exc:
        logger.info("skip optional router %s: %s", module_path, exc)
        return
    except Exception:
        logger.exception("FATAL: router %s failed to load", module_path)
        raise
    router = getattr(mod, "router", None)
    if router is None:
        return
    app.include_router(router)
    extra_router = getattr(mod, "open_router", None)
    if extra_router is not None:
        app.include_router(extra_router)


def _iter_route_method_signatures(routes, *, prefix: str = ""):
    """Yield flattened ``(path, method)`` pairs across lazy FastAPI routers."""

    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            include_context = getattr(route, "include_context", None)
            nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '') or ''}"
            yield from _iter_route_method_signatures(
                getattr(original_router, "routes", ()),
                prefix=nested_prefix,
            )
            continue
        path = f"{prefix}{getattr(route, 'path', '')}"
        for method in getattr(route, "methods", None) or set():
            yield path, str(method).upper()


def _include_router_without_method_conflicts(
    app: FastAPI,
    router: APIRouter,
    *,
    prefix: str = "",
) -> None:
    """Mount only routes not already owned by the application.

    ``market_auth_api`` still contains legacy implementations while its unique
    profile/avatar endpoints are migrated. Public auth contracts must have one
    runtime owner, so earlier core routes win deterministically.
    """

    existing = set(_iter_route_method_signatures(app.routes))
    filtered = APIRouter()
    for route in router.routes:
        full_path = f"{prefix}{getattr(route, 'path', '')}"
        methods = {str(method).upper() for method in (getattr(route, "methods", None) or set())}
        conflicts = sorted(method for method in methods if (full_path, method) in existing)
        if conflicts:
            logger.info(
                "skip duplicate legacy route %s methods=%s endpoint=%s",
                full_path,
                conflicts,
                getattr(route, "name", ""),
            )
            continue
        filtered.routes.append(route)
    app.include_router(filtered, prefix=prefix)


def _init_database() -> None:
    try:
        from modstore_server.models import init_db

        try:
            import modstore_server.models_project_context  # noqa: F401
        except Exception:
            logger.debug("models_project_context not registered", exc_info=True)
        init_db()
    except Exception:
        logger.exception("startup: init_db failed")

    try:
        from modstore_server.sync_employee_triggers import sync_all_employee_triggers

        n = sync_all_employee_triggers()
        logger.info("startup: synced %d employee trigger bindings (manifest)", n)
    except Exception:
        logger.exception("startup: sync_employee_triggers failed")

    try:
        from modstore_server.incident_bus import sync_employee_trigger_bindings_from_yuangon

        _deploy_root = Path(__file__).resolve().parents[2]
        _repo_root = Path(os.environ.get("MODSTORE_REPO_ROOT") or _deploy_root.parent).resolve()
        _yuangon = _repo_root / "yuangon"
        if _yuangon.is_dir():
            n_y = sync_employee_trigger_bindings_from_yuangon(_yuangon)
            logger.info("startup: synced %d employee trigger bindings (yuangon)", n_y)
    except Exception:
        logger.exception("startup: sync_employee_trigger_bindings_from_yuangon failed")

    try:
        from modstore_server.six_line_event_router import install_orchestrator_hooks

        install_orchestrator_hooks()
    except Exception:
        logger.exception("startup: six_line_event_router hooks failed")


def _init_event_subscribers() -> None:
    try:
        from modstore_server.eventing.subscribers import install_default_subscribers

        install_default_subscribers()
    except Exception:
        logger.exception("domain event subscribers failed to install")


def _init_background_jobs() -> None:
    if os.environ.get("MODSTORE_RUN_BACKGROUND_JOBS", "0") != "1":
        logger.info(
            "Background jobs (outbox/scheduler) SKIPPED "
            "(MODSTORE_RUN_BACKGROUND_JOBS != 1). "
            "Ensure modstore-scheduler.service is running separately."
        )
        print("[bg-jobs] SKIPPED: MODSTORE_RUN_BACKGROUND_JOBS != 1", flush=True)
        return

    print("[bg-jobs] MODSTORE_RUN_BACKGROUND_JOBS=1, starting background jobs...", flush=True)
    try:
        from modstore_server.eventing.db_outbox import start_default_worker

        start_default_worker()
        print("[bg-jobs] outbox worker started OK", flush=True)
    except Exception:
        logger.exception("outbox dispatcher worker failed to start")
        print("[bg-jobs] outbox worker FAILED", flush=True)

    try:
        from modstore_server.subscription_renewer import start_subscription_scheduler

        start_subscription_scheduler()
        print("[bg-jobs] subscription scheduler started OK", flush=True)
    except Exception:
        logger.exception("subscription auto-renew scheduler failed to start")
        print("[bg-jobs] subscription scheduler FAILED", flush=True)

    try:
        from modstore_server.backup_event_subscriber import register_backup_event_subscribers

        register_backup_event_subscribers()
        print("[bg-jobs] backup event subscribers registered OK", flush=True)
    except Exception:
        logger.exception("backup event subscribers registration failed")
        print("[bg-jobs] backup event subscribers FAILED", flush=True)

    try:
        from modstore_server.workflow_scheduler import start_scheduler as start_workflow_scheduler

        start_workflow_scheduler()
        print("[bg-jobs] workflow scheduler started OK", flush=True)
    except Exception:
        logger.exception(
            "workflow scheduler failed to start (daily digest / inbox poll / workflow cron)"
        )
        print("[bg-jobs] workflow scheduler FAILED", flush=True)

    try:
        from modstore_server.craft_steps import register_all_craft_steps

        register_all_craft_steps()
        print("[bg-jobs] craft step registry loaded OK", flush=True)
    except Exception:
        logger.exception("craft step registry failed to load")
        print("[bg-jobs] craft step registry FAILED", flush=True)


def _register_core_routes(app: FastAPI, cfg: AppConfig) -> None:
    from modstore_server.api import csp_report

    app.include_router(csp_report.router)

    if cfg.profile != "llm-only":
        from modstore_server.api.market_routes import router as market_router
        from modstore_server.api.payment_routes import router as payment_router

        app.include_router(market_router)
        app.include_router(payment_router)

        try:
            from modstore_server.market_auth_api import router as market_auth_router

            _include_router_without_method_conflicts(
                app,
                market_auth_router,
                prefix="/api",
            )
        except Exception:
            logger.exception("market_auth_api 加载失败，跳过")

        try:
            from modstore_server.app_config_api import router as app_config_router

            app.include_router(app_config_router, prefix="/api")
        except Exception:
            logger.exception("app_config_api 加载失败，跳过")

        try:
            from modstore_server.digest_identity_peer_api import router as digest_peer_router

            app.include_router(digest_peer_router, prefix="/api")
        except Exception:
            logger.exception("digest_identity_peer_api 加载失败，跳过")

        try:
            from modstore_server.market_catalog_api import router as market_catalog_router

            app.include_router(market_catalog_router, prefix="/api")
        except Exception:
            logger.exception("market_catalog_api 加载失败，跳过")

        from modstore_server.api import (
            admin_events,
            authoring,
            catalog,
        )
        from modstore_server.api import config as config_routes
        from modstore_server.api import (
            debug,
            health,
            scheduler_runtime_api,
            sync,
        )

        app.include_router(health.router)
        app.include_router(scheduler_runtime_api.router)
        app.include_router(admin_events.router)
        app.include_router(config_routes.router)
        app.include_router(catalog.router)
        app.include_router(authoring.router)
        app.include_router(sync.router)
        app.include_router(debug.router)

        from modstore_server.api.catalog_public_routes import router as catalog_public_router
        from modstore_server.mod_sync_catalog_api import router as mod_sync_catalog_router

        app.include_router(catalog_public_router)
        app.include_router(mod_sync_catalog_router)


_FULL_OPTIONAL_MODULES = (
    "modstore_server.public_visualization_api",
    "modstore_server.llm_api",
    "modstore_server.openai_llm_gateway_api",
    "modstore_server.agent_butler_api",
    "modstore_server.account_api",
    "modstore_server.butler_qq_bridge",
    "modstore_server.butler_qq_botpy",
    "modstore_server.notification_api",
    "modstore_server.knowledge_vector_api",
    "modstore_server.knowledge_v2_api",
    "modstore_server.realtime_ws",
    "modstore_server.workflow_api",
    "modstore_server.eskill_api",
    "modstore_server.script_workflow_api",
    "modstore_server.runtime_allowlist_api",
    "modstore_server.email_admin_api",
    "modstore_server.workbench_api",
    "modstore_server.asr_proxy_ws",
    "modstore_server.voice_s2s_ws",
    "modstore_server.voice_unified_ws",
    "modstore_server.workbench_studio_assets_api",
    "modstore_server.employee_api",
    "modstore_server.analytics_api",
    "modstore_server.refund_api",
    "modstore_server.ops_api",
    "modstore_server.admin_ops_audit_api",
    "modstore_server.admin_employee_execution_api",
    "modstore_server.admin_employee_autonomy_api",
    "modstore_server.autonomy_decision_evidence_api",
    "modstore_server.customer_value_evidence_api",
    "modstore_server.admin_duty_graph_api",
    "modstore_server.production_line_api",
    "modstore_server.release_train_api",
    "modstore_server.action_items_api",
    "modstore_server.public_action_board_api",
    "modstore_server.public_company_hall_api",
    "modstore_server.redline_approval_api",
    "modstore_server.ai_employee_account_api",
    "modstore_server.employee_change_request_api",
    "modstore_server.yuangon_onboard_admin_api",
    "modstore_server.webhook_api",
    "modstore_server.health_api",
    "modstore_server.health_check_api",
    "modstore_server.payment_health_api",
    "modstore_server.openapi_connector_api",
    "modstore_server.customer_service_api",
    "modstore_server.developer_api",
    "modstore_server.developer_key_export_api",
    "modstore_server.webhook_subscription_api",
    "modstore_server.templates_api",
    "modstore_server.sandbox_api",
    "modstore_server.employee_status_api",
    "modstore_server.self_maintenance_loop_api",
    "modstore_server.on_demand_orchestrate_api",
    "modstore_server.inbound_webhook_api",
    "modstore_server.author_earnings",
    "modstore_server.store_lifecycle_api",
    "modstore_server.invoice_api",
    "modstore_server.reconciliation",
    "modstore_server.telemetry_internal_api",
    "modstore_server.subscription_renewer",
    "modstore_server.xcmax_admin_api",
    "modstore_server.strategic_layer_api",
    "modstore_server.api.host_config_routes",
)

_LLM_ONLY_OPTIONAL_MODULES = (
    "modstore_server.llm_api",
    "modstore_server.openai_llm_gateway_api",
    "modstore_server.health_api",
)


def _register_optional_routes(app: FastAPI, cfg: AppConfig) -> None:
    if cfg.profile == "llm-only":
        from modstore_server.api import health as health_routes

        app.include_router(health_routes.router)
        modules = _LLM_ONLY_OPTIONAL_MODULES
    else:
        modules = _FULL_OPTIONAL_MODULES

    for _m in modules:
        _include_optional(app, _m)

    try:
        from modstore_server.butler_qq_botpy import start_botpy_background

        start_botpy_background(app)
    except Exception:
        logger.exception("butler_qq_botpy start_botpy_background failed, skipping")

    try:
        from modstore_server.workflow_api import workflow_hooks_router

        app.include_router(workflow_hooks_router)
        logger.info("已挂载 workflow_hooks_router (/api/workflow-hooks/*)")
    except Exception:
        logger.exception("workflow_hooks_router 挂载失败，跳过")


def _register_diagnostics(app: FastAPI) -> None:
    _maybe_mount_vibe_subapp(app)
    _register_neurobus_diagnostics(app)

    try:
        from modstore_server.security import ensure_secure_config

        ensure_secure_config()
    except Exception:
        logger.debug("secure config check skipped", exc_info=True)

    from modstore_server.api import ui_mount

    ui_mount.maybe_mount_dev_docs(app)
    ui_mount.maybe_mount_ui(app)


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or load_default_config()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            from modstore_server.edge_tts_service import warm_defaults

            await warm_defaults()
            logger.info("startup: edge-tts warm OK")
        except Exception:
            logger.debug("startup: edge-tts warm skipped", exc_info=True)
        try:
            yield
        finally:
            try:
                from modstore_server.infrastructure.http_clients import close_all

                await close_all()
            except Exception:
                logger.exception("error closing shared http clients on shutdown")
            if os.environ.get("MODSTORE_RUN_BACKGROUND_JOBS", "0") == "1":
                try:
                    from modstore_server.workflow_scheduler import stop_scheduler

                    stop_scheduler()
                except Exception:
                    logger.exception("workflow scheduler shutdown failed")

    app = FastAPI(
        title="XC AGI",
        version="0.2.0",
        description=(
            "XCAGI Mod 本地库与调试辅助 API。"
            f"\n\n**交互式文档**：本页同源的 [`/docs`](./docs)（Swagger UI）、[`/redoc`](./redoc)。"
            f"\n**机器可读**：[`/openapi.json`](./openapi.json)。"
            f"\n\n默认假设 XCAGI HTTP 后端在 `{DEFAULT_XCAGI_BACKEND_URL}`（可在配置中覆盖）。"
            f"\n开发时 API 默认监听 `127.0.0.1:{DEFAULT_API_PORT}`。"
        ),
        openapi_tags=_OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    from modstore_server.metrics import install_metrics

    install_metrics(app)

    _init_database()
    _init_event_subscribers()

    try:
        from modstore_server.craft_steps import register_all_craft_steps

        register_all_craft_steps()
        logger.info("startup: craft step registry loaded OK")
    except Exception:
        logger.exception("startup: craft step registry failed to load")

    _init_background_jobs()

    from modstore_server.middleware_registry import register_all_middleware

    register_all_middleware(app)

    _register_core_routes(app, cfg)
    _register_optional_routes(app, cfg)
    _register_diagnostics(app)

    return app


__all__ = ["AppConfig", "create_app", "load_default_config"]
