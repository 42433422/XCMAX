"""Legacy compat route mount phase."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from app.fastapi_routes._route_helpers import is_ci_strict
from app.fastapi_routes.mounts.legacy_gap import register_legacy_gap_routers
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def register_legacy_compat_routes(app: FastAPI) -> None:
    """注册 XCAGI 前端依赖的历史兼容路由(原 backend.routers.*,2026-04-20 已全部迁至本包)。

    ``xcagi_compat`` 路由注册顺序说明:
    主站 Vue 依赖 xcagi_compat(Planner / run_agent_chat)的 JSON 契约与错误语义。
    """

    # 须早于 xcagi_compat：避免与其它 /api 聚合路由在个别 Starlette 版本下的匹配顺序边缘问题，
    # 并保证 /api/market/* 始终由 market_account 提供（compat 层不再重复注册 llm-catalog）。
    from app.fastapi_routes.market_account import router as market_account_router

    app.include_router(market_account_router)
    logger.info("Registered market_account (/api/market/*)")

    from app.fastapi_routes.fhd_meta import router as fhd_meta_router

    app.include_router(fhd_meta_router)
    logger.info("Registered fhd_meta_router (/api/fhd/db-tokens/status)")

    from app.fastapi_routes.debug_client_log import router as debug_client_log_router

    app.include_router(debug_client_log_router)
    logger.info("Registered debug_client_log_router (/api/debug/client-log)")

    # 须早于 xcagi_compat / SPA 兜底：避免 ``GET /api/auth/session/validate`` 等落入 ``/{fallback:path}`` 返回 404。
    from app.fastapi_routes.domains.auth.routes import router as legacy_auth_router

    app.include_router(legacy_auth_router)
    logger.info("Registered legacy_auth_router early (/api/auth/*)")

    try:
        from app.fastapi_routes.system_routes import router as system_router

        app.include_router(system_router)
        logger.info("Registered system_router early (/api/system/*)")
    except (ImportError, AttributeError) as e:
        logger.warning("System router not available: %s", e)

    from app.fastapi_routes.code_editor import router as code_editor_router

    app.include_router(code_editor_router)
    logger.info("Registered code_editor_router (/api/code-editor/*)")

    try:
        from app.fastapi_routes.private_db_read_assistant_compat import (
            register_private_db_read_assistant_routes,
        )

        register_private_db_read_assistant_routes(app)
    except RECOVERABLE_ERRORS as e:
        logger.warning("private_db_read_assistant compat routes skipped: %s", e)

    try:
        from app.fastapi_routes.user_cs_wechat_passive_compat import (
            register_user_cs_wechat_passive_routes,
        )

        register_user_cs_wechat_passive_routes(app)
    except RECOVERABLE_ERRORS as e:
        logger.warning("user_cs_wechat_passive compat routes skipped: %s", e)

    try:
        from app.fastapi_routes.wechat_decrypt_routes import router as wechat_decrypt_router

        app.include_router(wechat_decrypt_router)
        logger.info("Registered wechat_decrypt_router (/api/wechat/decrypt/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("wechat_decrypt routes skipped: %s", e)

    from app.fastapi_routes.xcagi_compat import router as xcagi_compat_router

    app.include_router(xcagi_compat_router, prefix="/api")
    logger.info("Registered xcagi_compat_router (prefix=/api)")

    from app.fastapi_routes.document_templates import public_router as doc_templates_public_router

    app.include_router(doc_templates_public_router)
    logger.info("Registered document_templates public_router (/api/document-templates)")

    from app.fastapi_routes.xcagi_startup import router as xcagi_startup_router

    app.include_router(xcagi_startup_router, prefix="/api")
    logger.info("Registered xcagi_startup_router (/api/startup/status)")

    from app.fastapi_routes.template_api import router as template_list_router

    app.include_router(template_list_router)
    logger.info("Registered template_api router (/api/templates*)")

    from app.fastapi_routes.shipment_orders import router as shipment_orders_router

    app.include_router(shipment_orders_router)
    logger.info("Registered shipment_orders (/api/orders*, /api/shipment/shipment-records/*)")

    from app.fastapi_routes.materials import router as materials_router

    app.include_router(materials_router)
    logger.info("Registered materials (/api/materials*)")

    from app.fastapi_routes.upload import router as upload_router

    app.include_router(upload_router)
    logger.info("Registered upload (/api/upload/*)")

    from app.fastapi_routes.ocr import router as ocr_router

    app.include_router(ocr_router)
    logger.info("Registered ocr (/api/ocr/*)")

    from app.fastapi_routes.print_routes import router as print_router

    app.include_router(print_router)
    logger.info("Registered print_routes (/api/print/*)")

    from app.fastapi_routes.ai_assistant import router as ai_assistant_router

    app.include_router(ai_assistant_router)
    logger.info("Registered ai_assistant (/health, /api/generate, /api/shipment-records/*, ...)")

    try:
        from app.fastapi_routes.tts_install import router as tts_install_router

        app.include_router(tts_install_router)
        logger.info("Registered tts_install (/api/tts/install-system-voice)")
    except RECOVERABLE_ERRORS as e:  # pragma: no cover — Windows-only 可选功能
        logger.warning("tts_install route skipped: %s", e)

    from app.fastapi_routes.excel_templates import router as excel_templates_router

    app.include_router(excel_templates_router)
    logger.info("Registered excel_templates (/api/excel/*)")

    from app.fastapi_routes.excel_extract import router as excel_extract_router

    app.include_router(excel_extract_router)
    logger.info("Registered excel_extract (/api/excel/data/*)")

    from app.fastapi_routes.excel_vector import router as excel_vector_router

    app.include_router(excel_vector_router)
    logger.info("Registered excel_vector (/api/excel/vector/*)")

    from app.fastapi_routes.health_k8s import router as health_k8s_router

    app.include_router(health_k8s_router)
    logger.info("Registered health_k8s (/health/liveness|readiness|details)")

    from app.fastapi_routes.state import router as state_router

    app.include_router(state_router)
    logger.info("Registered state (/api/state/*)")

    try:
        from app.fastapi_routes.model_payment import router as model_payment_router

        app.include_router(model_payment_router)
        logger.info("Registered model_payment (/api/model-payment/*)")
    except RECOVERABLE_ERRORS as e:
        logger.warning("model_payment routes skipped: %s", e)

    from app.fastapi_routes.payment_reconcile_internal_api import (
        router as payment_reconcile_internal_router,
    )

    app.include_router(payment_reconcile_internal_router)
    logger.info("Registered payment_reconcile_internal (/api/internal/payment/*)")

    from app.fastapi_routes.sales_contract_api import router as sales_contract_router

    app.include_router(sales_contract_router)
    logger.info("Registered sales_contract (/api/sales-contract/*)")

    try:
        from app.fastapi_routes.contract_lifecycle_api import router as contract_lifecycle_router

        app.include_router(contract_lifecycle_router)
        logger.info("Registered contract_lifecycle (/api/contract-lifecycle/*)")
    except ImportError as exc:
        logger.warning("contract_lifecycle routes skipped: %s", exc)

    from app.fastapi_routes.operations_line_api import router as operations_line_router

    app.include_router(operations_line_router)
    logger.info("Registered operations_line (/api/operations-line/*)")

    from app.fastapi_routes.ai_intent import router as ai_intent_router

    app.include_router(ai_intent_router)
    logger.info(
        "Registered ai_intent (/api/ai/test, /api/ai/chat-unified*, /api/ai/intent/test, /api/intent/*)"
    )

    from app.fastapi_routes.ai_kitten import router as ai_kitten_router

    app.include_router(ai_kitten_router)
    logger.info("Registered ai_kitten (/api/ai/kitten/*)")

    from app.fastapi_routes.ai_qclaw import router as ai_qclaw_router

    app.include_router(ai_qclaw_router)
    logger.info("Registered ai_qclaw (/api/ai/qclaw/*)")

    from app.fastapi_routes.ai_open import router as ai_open_router

    app.include_router(ai_open_router)
    logger.info("Registered ai_open (/api/aiopen/*)")

    # legacy_gap domain routers superseded by xcagi_compat (SSOT) — no double-mount.
    # Force-only via XCAGI_REGISTER_LEGACY_ROUTES=1 for migration debugging.
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

    from app.fastapi_routes.approval import router as approval_router

    app.include_router(approval_router)
    logger.info("Registered approval (/api/approval/requests*, /api/approval/flows*)")

    try:
        from app.fastapi_routes.service_bridge import router as service_bridge_router

        app.include_router(service_bridge_router)
        logger.info("Registered service_bridge (/api/service-bridge/*)")
    except RECOVERABLE_ERRORS as exc:
        if is_ci_strict():
            raise RuntimeError("service_bridge router required in CI") from exc
        logger.warning("service_bridge router not available: %s", exc)
