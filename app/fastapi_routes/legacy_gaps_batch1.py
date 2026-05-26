"""FastAPI 路由缺口补齐 batch1 — 聚合入口。

聚合自归档蓝图的端点契约；原 batch1 已按业务域拆分到独立模块，本文件仅做路由聚合。
最终按域彻底拆分待 ``docs/reports/LEGACY_CLEANUP_TRACKING.md`` Phase 2D 推进。
"""

from fastapi import APIRouter

from app.fastapi_routes.legacy_conversation import router as conversation_router
from app.fastapi_routes.legacy_excel import router as excel_router
from app.fastapi_routes.legacy_helpers import router as helpers_router
from app.fastapi_routes.legacy_inventory import router as inventory_router
from app.fastapi_routes.legacy_miniprogram import router as miniprogram_router
from app.fastapi_routes.legacy_miniprogram_extra import router as miniprogram_extra_router
from app.fastapi_routes.legacy_miniprogram_order import router as miniprogram_order_router
from app.fastapi_routes.legacy_miniprogram_user import router as miniprogram_user_router
from app.fastapi_routes.legacy_products import router as products_router
from app.fastapi_routes.legacy_static import router as static_router
from app.fastapi_routes.legacy_system import router as system_router
from app.fastapi_routes.legacy_wechat import router as wechat_router
from app.fastapi_routes.legacy_workflow import router as workflow_router

router = APIRouter(tags=["legacy-gaps-batch1"])

for _r in [
    conversation_router,
    excel_router,
    helpers_router,
    inventory_router,
    miniprogram_router,
    miniprogram_extra_router,
    miniprogram_order_router,
    miniprogram_user_router,
    products_router,
    static_router,
    system_router,
    wechat_router,
    workflow_router,
]:
    router.include_router(_r)
