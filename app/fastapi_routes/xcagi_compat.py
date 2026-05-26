"""
XCAGI 前端兼容 API（FastAPI APIRouter）— 聚合入口。

原始单文件（4300+ 行）已按业务域拆分为子模块：
  - xcagi_compat_wechat       微信联系人
  - xcagi_compat_customer     客户管理
  - xcagi_compat_product      产品 / 库存 / 报价表
  - xcagi_compat_chat         AI 对话（流式 / 批量）
  - xcagi_compat_conversation 会话持久化
  - xcagi_compat_template     模板 / Excel 网格提取
  - xcagi_compat_misc         系统 / 认证 / 偏好 / 工具目录
  - xcagi_compat_db_base      共享 SQL 工具与常量
  - xcagi_compat_db_queries   共享 DB 查询辅助
  - xcagi_compat_db_writes    共享 DB 写入辅助

本文件仅做路由聚合，所有 API 路径保持不变。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.fastapi_routes.xcagi_compat_chat import router as chat_router
from app.fastapi_routes.xcagi_compat_conversation import router as conversation_router
from app.fastapi_routes.xcagi_compat_customer import router as customer_router
from app.fastapi_routes.xcagi_compat_misc import router as misc_router
from app.fastapi_routes.xcagi_compat_product import router as product_router
from app.fastapi_routes.xcagi_compat_template import router as template_router
from app.fastapi_routes.xcagi_compat_wechat import router as wechat_router

logger = logging.getLogger(__name__)

router = APIRouter(tags=["xcagi-compat"])

router.include_router(wechat_router)
router.include_router(customer_router)
router.include_router(product_router)
router.include_router(chat_router)
router.include_router(conversation_router)
router.include_router(template_router)
router.include_router(misc_router)


def _register_router_events():
    try:
        from app.neuro_bus.bus import get_neuro_bus

        bus = get_neuro_bus()
        logger.info(f"[XCAGICompat] 路由已注册到 NeuroBus，当前订阅者: {len(bus.subscribers)}")
    except Exception as e:
        logger.debug(f"[XCAGICompat] NeuroBus 注册跳过: {e}")


_register_router_events()
