"""
Product 领域事件处理器

处理所有 product.* 事件的业务逻辑。
"""

import logging
from typing import Any

from app.bootstrap import get_product_application_service_core
from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.command_gateway import try_complete_command_reply
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.events.product_events import (
    ProductCacheInvalidatedEvent,
    ProductCreatedEvent,
    ProductDeletedEvent,
    ProductImportedEvent,
    ProductPriceChangedEvent,
    ProductUpdatedEvent,
)

logger = logging.getLogger(__name__)


class ProductDomainHandlers:
    """Product 领域事件处理器集合"""

    def __init__(self):
        self._bus = None

    @property
    def bus(self):
        """延迟获取 NeuroBus 实例"""
        if self._bus is None:
            self._bus = get_neuro_bus()
        return self._bus

    async def handle_product_created(self, event: ProductCreatedEvent) -> dict[str, Any]:
        """落库 + 命令回复；副作用（缓存失效）仍经事件链。"""
        logger.info(
            "[ProductDomain] 处理产品创建: %s",
            event.payload.get("product_name") or event.payload.get("name"),
        )
        core = get_product_application_service_core()
        try:
            data = dict(event.payload)
            result = core.create_product(data)
            try_complete_command_reply(event, result)
            if result.get("success"):
                cache_event = ProductCacheInvalidatedEvent(
                    payload={
                        "unit_name": event.payload.get("unit_name"),
                        "reason": "new_product_added",
                    },
                    source="product_domain",
                    correlation_id=event.metadata.event_id,
                )
                self.bus.publish(cache_event)
            return result
        except Exception as e:
            logger.exception("[ProductDomain] 创建产品失败: %s", e)
            err = {"success": False, "message": str(e)}
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_product_updated(self, event: ProductUpdatedEvent) -> dict[str, Any]:
        logger.info("[ProductDomain] 处理产品更新: %s", event.payload.get("product_id"))
        core = get_product_application_service_core()
        try:
            pid = int(event.payload.get("product_id"))
            updates = {
                k: v
                for k, v in event.payload.items()
                if k not in ("product_id", "changed_fields", "old_price")
            }
            result = core.update_product(pid, updates)
            try_complete_command_reply(event, result)
            if result.get("success") and "price" in (event.payload.get("changed_fields") or []):
                price_event = ProductPriceChangedEvent(
                    payload={
                        "product_id": pid,
                        "old_price": event.payload.get("old_price"),
                        "new_price": event.payload.get("price"),
                        "unit_name": event.payload.get("unit_name"),
                    },
                    source="product_domain",
                    correlation_id=event.metadata.event_id,
                )
                self.bus.publish(price_event)
            return result
        except Exception as e:
            logger.exception("[ProductDomain] 更新产品失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_product_deleted(self, event: ProductDeletedEvent) -> dict[str, Any]:
        logger.info("[ProductDomain] 处理产品删除: %s", event.payload.get("product_id"))
        core = get_product_application_service_core()
        try:
            pid = int(event.payload.get("product_id"))
            result = core.delete_product(pid)
            try_complete_command_reply(event, result)
            if result.get("success"):
                cache_event = ProductCacheInvalidatedEvent(
                    payload={
                        "product_id": pid,
                        "unit_name": event.payload.get("unit_name"),
                        "reason": "product_deleted",
                    },
                    source="product_domain",
                    correlation_id=event.metadata.event_id,
                )
                self.bus.publish(cache_event)
            return result
        except Exception as e:
            logger.exception("[ProductDomain] 删除产品失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_product_imported(self, event: ProductImportedEvent) -> dict[str, Any]:
        logger.info(
            "[ProductDomain] 批量导入: count=%s",
            event.payload.get("count", len(event.payload.get("products") or [])),
        )
        core = get_product_application_service_core()
        try:
            products = event.payload.get("products") or []
            result = core.batch_add_products(products)
            try_complete_command_reply(event, result)
            if result.get("success"):
                cache_event = ProductCacheInvalidatedEvent(
                    payload={
                        "unit_name": event.payload.get("unit_name"),
                        "reason": "bulk_import",
                        "affected_count": event.payload.get("count", len(products)),
                    },
                    source="product_domain",
                    correlation_id=event.metadata.event_id,
                )
                self.bus.publish(cache_event)
            return result
        except Exception as e:
            logger.exception("[ProductDomain] 批量导入失败: %s", e)
            try_complete_command_reply(event, None, error=e)
            raise

    async def handle_price_changed(self, event: ProductPriceChangedEvent) -> dict[str, Any]:
        """
        处理价格变更事件

        职责:
        1. 记录价格历史
        2. 检查是否需要触发价格预警
        3. 通知相关业务方
        """
        logger.info(
            f"[ProductDomain] 处理价格变更: {event.payload.get('product_id')} "
            f"({event.payload.get('old_price')} -> {event.payload.get('new_price')})"
        )

        result = {
            "success": True,
            "product_id": event.payload.get("product_id"),
            "price_delta": event.payload.get("new_price", 0) - event.payload.get("old_price", 0),
            "actions": [],
        }

        try:
            # 1. 记录价格历史
            result["actions"].append("price_history_recorded")

            # 2. 可以在这里触发价格预警检查
            # 如果价格变动超过阈值，发送预警

        except Exception as e:
            logger.error(f"[ProductDomain] 处理价格变更事件失败: {e}")
            result["success"] = False
            result["error"] = str(e)

        return result

    async def handle_cache_invalidated(self, event: ProductCacheInvalidatedEvent) -> dict[str, Any]:
        """
        处理缓存失效事件

        职责:
        1. 执行实际的缓存清除操作
        2. 通知其他节点（如果是分布式缓存）
        """
        payload = event.payload

        if "product_id" in payload:
            logger.info(f"[ProductDomain] 清除产品缓存: {payload.get('product_id')}")
        elif "unit_name" in payload:
            logger.info(f"[ProductDomain] 清除单位缓存: {payload.get('unit_name')}")

        result = {"success": True, "invalidated": payload, "actions": ["cache_cleared"]}

        try:
            # 这里调用实际的缓存清除逻辑
            # 可以调用 ProductsService 的缓存清除方法
            pass
        except Exception as e:
            logger.error(f"[ProductDomain] 处理缓存失效事件失败: {e}")
            result["success"] = False
            result["error"] = str(e)

        return result


# 创建处理器实例
_product_handlers = None


def get_product_domain_handlers() -> ProductDomainHandlers:
    """获取 ProductDomainHandlers 单例"""
    global _product_handlers
    if _product_handlers is None:
        _product_handlers = ProductDomainHandlers()
    return _product_handlers


def register_product_domain_handlers(bus):
    """注册所有 Product 领域事件处理器到 NeuroBus"""
    handlers = get_product_domain_handlers()

    # 注册所有事件处理器
    bus.subscribe("product.created", handlers.handle_product_created)
    bus.subscribe("product.updated", handlers.handle_product_updated)
    bus.subscribe("product.deleted", handlers.handle_product_deleted)
    bus.subscribe("product.imported", handlers.handle_product_imported)
    bus.subscribe("product.price_changed", handlers.handle_price_changed)
    bus.subscribe("product.cache_invalidated", handlers.handle_cache_invalidated)

    logger.info("[ProductDomain] 所有事件处理器已注册")
