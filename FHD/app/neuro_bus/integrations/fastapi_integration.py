"""
FastAPI 集成

NeuroBus 与 FastAPI 的健康检查/统计端点集成。

注：应用生命周期由 ``app/fastapi_app/lifespan.py`` 统一管理，
    此处不再提供重复的 lifespan 工厂（历史 ``setup_neurobus_lifespan``
    与 ``create_fastapi_app_with_neurobus`` 已移除，避免与生产 lifespan 冲突）。
"""

import logging
from typing import Any

from fastapi import FastAPI

from app.domain.neuro.processors.coordinator import get_processor_coordinator
from app.mod_sdk.neuro_bus_runtime import get_neuro_bus_health_runtime
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.bus_setup import get_neuro_bus_manager
from app.neuro_bus.domains.base import get_domain_registry
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def get_neurobus_health() -> dict[str, Any]:
    """
    获取 NeuroBus 健康状态

    用于健康检查端点
    """
    try:
        health = get_neuro_bus_health_runtime()
        manager = get_neuro_bus_manager()
        bus = get_neuro_bus()

        base = manager.get_health() if manager else {}
        if isinstance(health, dict) and isinstance(base, dict):
            health = {**base, **health}

        # 添加各组件状态
        health["components"] = {
            "bus_running": bool(bus and bus.is_running),
            "queue_size": bus.get_stats().get("queue_size", 0) if bus else 0,
            "domains": get_domain_registry().list_domains(),
        }
        if bus:
            health["reliability"] = bus.get_reliability_status()

        # 添加处理器统计
        try:
            processor = get_processor_coordinator()
            health["processors"] = processor.get_all_processor_stats()
        except RECOVERABLE_ERRORS:
            pass

        # 添加认知层 / 潜意识层 / 进化层统计（Phase 2-4 接线）
        try:
            from app.domain.neuro.register_cognition_handlers import get_cognition_stats

            health["cognition"] = get_cognition_stats()
        except RECOVERABLE_ERRORS:
            pass

        return health

    except RECOVERABLE_ERRORS as e:
        return {
            "status": "error",
            "error": str(e),
        }


def add_neurobus_routes(app: FastAPI):
    """
    添加 NeuroBus 相关路由

    添加以下端点：
    - GET /api/neurobus/health - 健康检查
    - GET /api/neurobus/stats - 统计数据
    """

    @app.get("/api/neurobus/health")
    async def neurobus_health():
        return get_neurobus_health()

    @app.get("/api/neurobus/stats")
    async def neurobus_stats():
        try:
            processor = get_processor_coordinator()
            return processor.get_all_processor_stats()
        except RECOVERABLE_ERRORS as e:
            return {"error": str(e)}

    logger.info("NeuroBus routes added")
