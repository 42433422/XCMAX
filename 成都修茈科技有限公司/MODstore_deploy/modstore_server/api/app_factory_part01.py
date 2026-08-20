# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.api.app_factory")


def _include_optional(app: _facade().FastAPI, module_path: str) -> None:
    try:
        mod = __import__(module_path, fromlist=["router"])
    except ImportError as exc:
        _facade().logger.info("skip optional router %s: %s", module_path, exc)
        return
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("FATAL: router %s failed to load", module_path)
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
                getattr(original_router, "routes", ()), prefix=nested_prefix
            )
            continue
        path = f"{prefix}{getattr(route, 'path', '')}"
        for method in getattr(route, "methods", None) or set():
            yield (path, str(method).upper())


def _include_router_without_method_conflicts(
    app: _facade().FastAPI, router: _facade().APIRouter, *, prefix: str = ""
) -> None:
    """Mount only routes not already owned by the application.

    ``market_auth_api`` still contains legacy implementations while its unique
    profile/avatar endpoints are migrated. Public auth contracts must have one
    runtime owner, so earlier core routes win deterministically.
    """
    existing = set(_facade()._iter_route_method_signatures(app.routes))
    filtered = _facade().APIRouter()
    for route in router.routes:
        full_path = f"{prefix}{getattr(route, 'path', '')}"
        methods = {str(method).upper() for method in getattr(route, "methods", None) or set()}
        conflicts = sorted((method for method in methods if (full_path, method) in existing))
        if conflicts:
            _facade().logger.info(
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
            import modstore_server.models_project_context
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("models_project_context not registered", exc_info=True)
        init_db()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("startup: init_db failed")
    try:
        from modstore_server.sync_employee_triggers import sync_all_employee_triggers

        n = sync_all_employee_triggers()
        _facade().logger.info("startup: synced %d employee trigger bindings (manifest)", n)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("startup: sync_employee_triggers failed")
    try:
        from modstore_server.incident_bus import sync_employee_trigger_bindings_from_yuangon

        _deploy_root = _facade().Path(__file__).resolve().parents[2]
        _repo_root = (
            _facade()
            .Path(_facade().os.environ.get("MODSTORE_REPO_ROOT") or _deploy_root.parent)
            .resolve()
        )
        _yuangon = _repo_root / "yuangon"
        if _yuangon.is_dir():
            n_y = sync_employee_trigger_bindings_from_yuangon(_yuangon)
            _facade().logger.info("startup: synced %d employee trigger bindings (yuangon)", n_y)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("startup: sync_employee_trigger_bindings_from_yuangon failed")
    try:
        from modstore_server.six_line_event_router import install_orchestrator_hooks

        install_orchestrator_hooks()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("startup: six_line_event_router hooks failed")


def _init_event_subscribers() -> None:
    try:
        from modstore_server.eventing.subscribers import install_default_subscribers

        install_default_subscribers()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("domain event subscribers failed to install")


def _init_background_jobs() -> None:
    if _facade().os.environ.get("MODSTORE_RUN_BACKGROUND_JOBS", "0") != "1":
        _facade().logger.info(
            "Background jobs (outbox/scheduler) SKIPPED (MODSTORE_RUN_BACKGROUND_JOBS != 1). Ensure modstore-scheduler.service is running separately."
        )
        print("[bg-jobs] SKIPPED: MODSTORE_RUN_BACKGROUND_JOBS != 1", flush=True)
        return
    print("[bg-jobs] MODSTORE_RUN_BACKGROUND_JOBS=1, starting background jobs...", flush=True)
    try:
        from modstore_server.eventing.db_outbox import start_default_worker

        start_default_worker()
        print("[bg-jobs] outbox worker started OK", flush=True)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("outbox dispatcher worker failed to start")
        print("[bg-jobs] outbox worker FAILED", flush=True)
    try:
        from modstore_server.subscription_renewer import start_subscription_scheduler

        start_subscription_scheduler()
        print("[bg-jobs] subscription scheduler started OK", flush=True)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("subscription auto-renew scheduler failed to start")
        print("[bg-jobs] subscription scheduler FAILED", flush=True)
    try:
        from modstore_server.backup_event_subscriber import register_backup_event_subscribers

        register_backup_event_subscribers()
        print("[bg-jobs] backup event subscribers registered OK", flush=True)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("backup event subscribers registration failed")
        print("[bg-jobs] backup event subscribers FAILED", flush=True)
    try:
        from modstore_server.workflow_scheduler import start_scheduler as start_workflow_scheduler

        start_workflow_scheduler()
        print("[bg-jobs] workflow scheduler started OK", flush=True)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception(
            "workflow scheduler failed to start (daily digest / inbox poll / workflow cron)"
        )
        print("[bg-jobs] workflow scheduler FAILED", flush=True)
    try:
        from modstore_server.craft_steps import register_all_craft_steps

        register_all_craft_steps()
        print("[bg-jobs] craft step registry loaded OK", flush=True)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("craft step registry failed to load")
        print("[bg-jobs] craft step registry FAILED", flush=True)


def _register_core_routes(app: _facade().FastAPI, cfg: _facade().AppConfig) -> None:
    from modstore_server.api import csp_report

    app.include_router(csp_report.router)
    if cfg.profile != "llm-only":
        from modstore_server.api.market_routes import router as market_router
        from modstore_server.api.payment_routes import router as payment_router

        app.include_router(market_router)
        app.include_router(payment_router)
        try:
            from modstore_server.market_auth_api import router as market_auth_router

            _facade()._include_router_without_method_conflicts(
                app, market_auth_router, prefix="/api"
            )
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("market_auth_api 加载失败，跳过")
        try:
            from modstore_server.app_config_api import router as app_config_router

            app.include_router(app_config_router, prefix="/api")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("app_config_api 加载失败，跳过")
        try:
            from modstore_server.digest_identity_peer_api import router as digest_peer_router

            app.include_router(digest_peer_router, prefix="/api")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("digest_identity_peer_api 加载失败，跳过")
        try:
            from modstore_server.market_catalog_api import router as market_catalog_router

            app.include_router(market_catalog_router, prefix="/api")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("market_catalog_api 加载失败，跳过")
        from modstore_server.api import admin_events, authoring, catalog
        from modstore_server.api import config as config_routes
        from modstore_server.api import debug, health, scheduler_runtime_api, sync

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
