# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.api.app_factory")


def _register_optional_routes(app: _facade().FastAPI, cfg: _facade().AppConfig) -> None:
    if cfg.profile == "llm-only":
        from modstore_server.api import health as health_routes

        app.include_router(health_routes.router)
        modules = _facade()._LLM_ONLY_OPTIONAL_MODULES
    else:
        modules = _facade()._FULL_OPTIONAL_MODULES
    for _m in modules:
        _facade()._include_optional(app, _m)
    try:
        from modstore_server.butler_qq_botpy import start_botpy_background

        start_botpy_background(app)
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("butler_qq_botpy start_botpy_background failed, skipping")
    try:
        from modstore_server.workflow_api import workflow_hooks_router

        app.include_router(workflow_hooks_router)
        _facade().logger.info("已挂载 workflow_hooks_router (/api/workflow-hooks/*)")
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("workflow_hooks_router 挂载失败，跳过")


def _register_diagnostics(app: _facade().FastAPI) -> None:
    _facade()._maybe_mount_vibe_subapp(app)
    _facade()._register_neurobus_diagnostics(app)
    try:
        from modstore_server.security import ensure_secure_config

        ensure_secure_config()
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.debug("secure config check skipped", exc_info=True)
    from modstore_server.api import ui_mount

    ui_mount.maybe_mount_dev_docs(app)
    ui_mount.maybe_mount_ui(app)


def create_app(config: _facade().AppConfig | None = None) -> _facade().FastAPI:
    cfg = config or _facade().load_default_config()

    @_facade().asynccontextmanager
    async def lifespan(_app: _facade().FastAPI):
        try:
            from modstore_server.edge_tts_service import warm_defaults

            await warm_defaults()
            _facade().logger.info("startup: edge-tts warm OK")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("startup: edge-tts warm skipped", exc_info=True)
        try:
            yield
        finally:
            try:
                from modstore_server.infrastructure.http_clients import close_all

                await close_all()
            except _facade().RECOVERABLE_ERRORS:
                _facade().logger.exception("error closing shared http clients on shutdown")
            if _facade().os.environ.get("MODSTORE_RUN_BACKGROUND_JOBS", "0") == "1":
                try:
                    from modstore_server.workflow_scheduler import stop_scheduler

                    stop_scheduler()
                except _facade().RECOVERABLE_ERRORS:
                    _facade().logger.exception("workflow scheduler shutdown failed")

    app = _facade().FastAPI(
        title="XC AGI",
        version="0.2.0",
        description=f"XCAGI Mod 本地库与调试辅助 API。\n\n**交互式文档**：本页同源的 [`/docs`](./docs)（Swagger UI）、[`/redoc`](./redoc)。\n**机器可读**：[`/openapi.json`](./openapi.json)。\n\n默认假设 XCAGI HTTP 后端在 `{_facade().DEFAULT_XCAGI_BACKEND_URL}`（可在配置中覆盖）。\n开发时 API 默认监听 `127.0.0.1:{_facade().DEFAULT_API_PORT}`。",
        openapi_tags=_facade()._OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    from modstore_server.metrics import install_metrics

    install_metrics(app)
    _facade()._init_database()
    _facade()._init_event_subscribers()
    try:
        from modstore_server.craft_steps import register_all_craft_steps

        register_all_craft_steps()
        _facade().logger.info("startup: craft step registry loaded OK")
    except _facade().RECOVERABLE_ERRORS:
        _facade().logger.exception("startup: craft step registry failed to load")
    _facade()._init_background_jobs()
    from modstore_server.middleware_registry import register_all_middleware

    register_all_middleware(app)
    _facade()._register_core_routes(app, cfg)
    _facade()._register_optional_routes(app, cfg)
    _facade()._register_diagnostics(app)
    return app
