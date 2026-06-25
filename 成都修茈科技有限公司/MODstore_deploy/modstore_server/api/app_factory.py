"""FastAPI application factory.

Gateway note: payment proxy is wired in ``middleware_registry.register_all_middleware``
via ``_payment_backend_proxy_middleware`` wrapping ``payment_backend_proxy_middleware``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

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

logger = logging.getLogger(__name__)

_OPENAPI_TAGS = [
    {"name": "health", "description": "服务探活"},
    {
        "name": "config",
        "description": "库路径、XCAGI 根目录、后端 URL、导出 FHD 壳层 /api/mods JSON",
    },
    {"name": "mods", "description": "Mod 列表、详情、manifest、文件读写、导入导出"},
    {"name": "sync", "description": "与 XCAGI/mods 推送与拉回"},
    {"name": "debug", "description": "沙箱目录、primary 批量标记、XCAGI 状态代理"},
    {"name": "authoring", "description": "扩展面文档、蓝图路由静态扫描、宿主 OpenAPI 合并"},
    {"name": "payment", "description": "支付、订单与会员计划"},
    {
        "name": "workflow",
        "description": "工作流编排、执行、自然语言生成与沙箱（见 workflow_api / workflow_nl_graph）",
    },
    {"name": "workflow-hooks", "description": "工作流 Webhook 触发入口（/api/workflow-hooks）"},
    {"name": "webhooks", "description": "业务 Webhook 投递与重放"},
    {"name": "inbound-webhooks", "description": "入站 Webhook 接收"},
    {"name": "refunds", "description": "退款申请与审核"},
    {"name": "catalog", "description": "公开目录与市场检索"},
    {
        "name": "catalog-mod-sync",
        "description": "公网机器令牌：库与 XCAGI/mods 推送/拉回（/v1/mod-sync）",
    },
    {"name": "market", "description": "市场展示、目录与匿名公开接口（如落地页联系表单）"},
    {"name": "auth", "description": "注册、登录、JWT、个人资料；与 Java 支付侧用户叠加信息"},
    {
        "name": "admin",
        "description": "需管理员权限的账户与运维辅助入口（与 /api/admin/* 部分重叠）",
    },
    {
        "name": "employees",
        "description": "AI 员工执行、配置与打包（领域边界见 SERVICE_BOUNDARIES.md）",
    },
    {"name": "llm", "description": "大模型目录、BYOK、聊天/多模态代理与计费"},
    {
        "name": "openai-gateway",
        "description": "OpenAI 兼容聚合网关（/v1/chat/completions，账户默认路由 + 平台计费）",
    },
    {"name": "knowledge", "description": "知识库与向量检索（v1 API）"},
    {"name": "knowledge-v2", "description": "知识库 v2 扩展接口"},
    {"name": "workbench", "description": "工作台与制作向导相关 API"},
    {"name": "eskills", "description": "ESkill 定义与版本"},
    {"name": "script-workflow", "description": "脚本化工作流"},
    {"name": "realtime", "description": "WebSocket 实时通知通道（/api/realtime/ws）"},
    {"name": "notifications", "description": "站内通知 REST 与持久化"},
    {"name": "openapi-connectors", "description": "第三方 OpenAPI 连接器导入与调用"},
    {"name": "customer-service", "description": "客服编排与工具链"},
    {"name": "butler", "description": "数字管家（Butler）编排 API"},
    {"name": "butler-qq", "description": "Butler ↔ QQ 官方机器人 HTTP 桥"},
    {"name": "butler-qqbot", "description": "Butler QQ botpy 网关与 Webhook"},
    {"name": "developer", "description": "开发者门户与密钥"},
    {"name": "key-export", "description": "开发者密钥导出"},
    {"name": "sandbox", "description": "沙箱执行与校验"},
    {"name": "ops", "description": "运维状态、编排开关与员工健康"},
    {"name": "analytics", "description": "埋点与分析"},
    {"name": "templates", "description": "模板资源"},
    {"name": "csp", "description": "CSP 违规上报"},
    {"name": "runtime-allowlist", "description": "运行时允许名单（管理）"},
    {"name": "admin-events", "description": "管理端领域事件查询"},
    {"name": "admin-email", "description": "管理端邮件测试与配置"},
    {"name": "admin-employees", "description": "管理端员工执行指标与干预"},
    {"name": "admin-change-requests", "description": "员工变更请求审批"},
    {"name": "admin-ai-accounts", "description": "AI 员工账户与凭据（管理）"},
    {"name": "admin-yuangon-onboard", "description": "元工（Yuangon）入驻配置"},
    {"name": "admin-employee-autonomy", "description": "员工自主度策略"},
    {"name": "admin-ops", "description": "运维审计与操作记录"},
    {"name": "admin-duty-graph", "description": "值班员工关系图（管理）"},
    {"name": "admin-production-line", "description": "制作线全流程管理（10步端到端编排与审批）"},
    {
        "name": "admin-redline",
        "description": "红线审批门控（支付/安全/DB/发布/删除 AI执行+人工审批）",
    },
    {"name": "author-earnings", "description": "作者分成与结算相关"},
    {"name": "invoices", "description": "发票"},
    {"name": "reconciliation", "description": "对账"},
    {"name": "subscription", "description": "订阅续费与计划"},
    {
        "name": "xcmax-admin",
        "description": "XCmax 服务器后台与双向同步（/api/xcmax/admin、/api/xcmax/sync）",
    },
]


@dataclass(frozen=True)
class AppConfig:
    """Process-level app wiring flags."""

    profile: str = "full"  # full | llm-only


def load_default_config() -> AppConfig:
    raw = (os.environ.get("MODSTORE_APP_PROFILE") or "").strip().lower()
    if raw in ("llm-only", "llm_only"):
        return AppConfig(profile="llm-only")
    return AppConfig(profile="full")


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


_failed_bg_jobs: list[str] = []


def _init_background_jobs() -> None:
    global _failed_bg_jobs
    _failed_bg_jobs = []  # Reset for each app creation

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
        _failed_bg_jobs.append("outbox_worker")

    try:
        from modstore_server.subscription_renewer import start_subscription_scheduler

        start_subscription_scheduler()
        print("[bg-jobs] subscription scheduler started OK", flush=True)
    except Exception:
        logger.exception("subscription auto-renew scheduler failed to start")
        print("[bg-jobs] subscription scheduler FAILED", flush=True)
        _failed_bg_jobs.append("subscription_renewer")

    try:
        from modstore_server.backup_event_subscriber import register_backup_event_subscribers

        register_backup_event_subscribers()
        print("[bg-jobs] backup event subscribers registered OK", flush=True)
    except Exception:
        logger.exception("backup event subscribers registration failed")
        print("[bg-jobs] backup event subscribers FAILED", flush=True)
        _failed_bg_jobs.append("backup_subscribers")

    try:
        from modstore_server.workflow_scheduler import start_scheduler as start_workflow_scheduler

        start_workflow_scheduler()
        print("[bg-jobs] workflow scheduler started OK", flush=True)
    except Exception:
        logger.exception(
            "workflow scheduler failed to start (daily digest / inbox poll / workflow cron)"
        )
        print("[bg-jobs] workflow scheduler FAILED", flush=True)
        _failed_bg_jobs.append("workflow_scheduler")

    try:
        from modstore_server.craft_steps import register_all_craft_steps

        register_all_craft_steps()
        print("[bg-jobs] craft step registry loaded OK", flush=True)
    except Exception:
        logger.exception("craft step registry failed to load")
        print("[bg-jobs] craft step registry FAILED", flush=True)
        _failed_bg_jobs.append("craft_steps")

    # Fail fast if critical jobs failed and env var is set
    if _failed_bg_jobs and os.environ.get("MODSTORE_STARTUP_FAIL_ON_BG_JOBS") == "1":
        raise RuntimeError(
            f"Critical background jobs failed to start: {', '.join(_failed_bg_jobs)}"
        )


def _register_core_routes(app: FastAPI, cfg: AppConfig) -> None:
    from modstore_server.api import csp_report, ui_mount

    app.include_router(csp_report.router)

    if cfg.profile != "llm-only":
        from modstore_server.api.market_routes import router as market_router
        from modstore_server.api.payment_routes import router as payment_router

        app.include_router(market_router)
        app.include_router(payment_router)

        try:
            from modstore_server.market_auth_api import router as market_auth_router

            app.include_router(market_auth_router, prefix="/api")
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
            sync,
        )

        from modstore_server.api import scheduler_runtime_api

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
    "modstore_server.admin_duty_graph_api",
    "modstore_server.production_line_api",
    "modstore_server.release_train_api",
    "modstore_server.action_items_api",
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

    # Track failed background jobs in app state for runtime visibility
    app.state.failed_background_jobs = _failed_bg_jobs

    @app.on_event("startup")
    async def _warm_edge_tts_on_startup() -> None:
        try:
            from modstore_server.edge_tts_service import warm_defaults

            await warm_defaults()
            logger.info("startup: edge-tts warm OK")
        except Exception:
            logger.debug("startup: edge-tts warm skipped", exc_info=True)

    from modstore_server.middleware_registry import register_all_middleware

    register_all_middleware(app)

    _register_core_routes(app, cfg)
    _register_optional_routes(app, cfg)
    _register_diagnostics(app)

    @app.on_event("shutdown")
    async def _close_shared_http_clients() -> None:
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
            try:
                from modstore_server.eventing.db_outbox import _default_worker

                if _default_worker is not None:
                    _default_worker.stop(timeout=5.0)
            except Exception:
                logger.exception("outbox worker shutdown failed")

    return app


def _maybe_mount_vibe_subapp(app: FastAPI) -> None:
    if (os.environ.get("MODSTORE_ENABLE_VIBE_WEB") or "").strip() not in ("1", "true", "yes"):
        return
    try:
        from modstore_server.integrations.vibe_adapter import vibe_available
    except Exception:
        return
    if not vibe_available():
        logger.info("MODSTORE_ENABLE_VIBE_WEB=1 但 vibe-coding 未安装,跳过挂载")
        return
    try:
        from vibe_coding.agent.web import create_app as create_vibe_app
    except Exception:
        logger.exception("vibe_coding.agent.web 加载失败,跳过 /api/vibe 挂载")
        return
    try:
        sub = create_vibe_app()
        app.mount("/api/vibe", sub)
        logger.info("已挂载 vibe-coding sub-app 到 /api/vibe")
    except Exception:
        logger.exception("挂载 /api/vibe 失败")


def _register_neurobus_diagnostics(app: FastAPI) -> None:
    try:
        from modstore_server.eventing.global_bus import neuro_bus

        @app.get("/api/neurobus/stats", tags=["ops"])
        async def neurobus_stats():
            if hasattr(neuro_bus, "get_stats"):
                return neuro_bus.get_stats()
            return {"status": "basic", "type": type(neuro_bus).__name__}

        @app.get("/api/neurobus/health", tags=["ops"])
        async def neurobus_health():
            return {
                "status": "ok",
                "bus_type": type(neuro_bus).__name__,
                "has_stats": hasattr(neuro_bus, "get_stats"),
            }

        logger.info("Registered NeuroBus diagnostics (/api/neurobus/stats, /api/neurobus/health)")
    except Exception:
        logger.debug("NeuroBus diagnostics skipped", exc_info=True)


__all__ = ["AppConfig", "create_app", "load_default_config"]
