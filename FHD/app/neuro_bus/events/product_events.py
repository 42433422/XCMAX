"""
Product 领域事件定义

包含产品生命周期中的所有领域事件。
"""

from typing import Any

from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


class _ProductEvent(NeuroEvent):
    """Product event constructor compatible with the non-dataclass base class."""

    event_type = "product.unknown"
    priority = EventPriority.NORMAL

    def __init__(
        self,
        payload: dict[str, Any],
        event_type: str | None = None,
        priority: EventPriority | None = None,
        metadata: EventMetadata | None = None,
        *,
        source: str | None = None,
        correlation_id: str | None = None,
        preserve_queue_identity: bool = False,
        **kwargs: Any,
    ) -> None:
        event_metadata = metadata or EventMetadata()
        if source is not None:
            event_metadata.source = source
        if correlation_id is not None:
            event_metadata.correlation_id = correlation_id
        super().__init__(
            event_type=event_type or self.event_type,
            payload=payload,
            priority=priority or self.priority,
            metadata=event_metadata,
            preserve_queue_identity=preserve_queue_identity,
            **kwargs,
        )
        self._validate_payload()

    def _validate_payload(self) -> None:
        return


class ProductCreatedEvent(_ProductEvent):
    """产品创建事件"""

    event_type: str = "product.created"
    priority: EventPriority = EventPriority.NORMAL

    def _validate_payload(self) -> None:
        # 验证必要字段
        required_fields = ["product_id", "unit_name", "product_name"]
        for field in required_fields:
            if field not in self.payload:
                raise ValueError(f"ProductCreatedEvent 缺少必要字段: {field}")


class ProductUpdatedEvent(_ProductEvent):
    """产品更新事件"""

    event_type: str = "product.updated"
    priority: EventPriority = EventPriority.NORMAL

    def _validate_payload(self) -> None:
        if "product_id" not in self.payload:
            raise ValueError("ProductUpdatedEvent 缺少必要字段: product_id")


class ProductDeletedEvent(_ProductEvent):
    """产品删除事件（软删除）"""

    event_type: str = "product.deleted"
    priority: EventPriority = EventPriority.NORMAL

    def _validate_payload(self) -> None:
        if "product_id" not in self.payload:
            raise ValueError("ProductDeletedEvent 缺少必要字段: product_id")


class ProductImportedEvent(_ProductEvent):
    """批量产品导入事件"""

    event_type: str = "product.imported"
    priority: EventPriority = EventPriority.LOW  # 批量导入优先级较低

    def _validate_payload(self) -> None:
        if "unit_name" not in self.payload:
            raise ValueError("ProductImportedEvent 缺少必要字段: unit_name")


class ProductPriceChangedEvent(_ProductEvent):
    """产品价格变更事件"""

    event_type: str = "product.price_changed"
    priority: EventPriority = EventPriority.NORMAL

    def _validate_payload(self) -> None:
        required_fields = ["product_id", "old_price", "new_price"]
        for field in required_fields:
            if field not in self.payload:
                raise ValueError(f"ProductPriceChangedEvent 缺少必要字段: {field}")


class ProductCacheInvalidatedEvent(_ProductEvent):
    """产品缓存失效事件"""

    event_type: str = "product.cache_invalidated"
    priority: EventPriority = EventPriority.HIGH  # 缓存失效需要快速处理

    def _validate_payload(self) -> None:
        # 可以是单个产品或整个单位
        if "product_id" not in self.payload and "unit_name" not in self.payload:
            raise ValueError("ProductCacheInvalidatedEvent 需要 product_id 或 unit_name")


# 事件处理器注册表
PRODUCT_EVENT_HANDLERS: dict[str, list[Any]] = {
    "product.created": [],
    "product.updated": [],
    "product.deleted": [],
    "product.imported": [],
    "product.price_changed": [],
    "product.cache_invalidated": [],
}


def register_product_handler(event_type: str, handler):
    """注册产品事件处理器"""
    if event_type in PRODUCT_EVENT_HANDLERS:
        PRODUCT_EVENT_HANDLERS[event_type].append(handler)
    else:
        raise ValueError(f"未知的产品事件类型: {event_type}")
