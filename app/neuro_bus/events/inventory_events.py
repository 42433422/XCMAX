"""
Inventory 领域事件定义

包含库存管理中的所有领域事件。
"""

from __future__ import annotations

from typing import Any

from app.neuro_bus.events._typed_event import init_typed_event
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


class InventoryStockChangedEvent(NeuroEvent):
    """库存变动事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "inventory.stock_changed",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("product_id", "warehouse_id", "quantity_delta", "reason"),
            class_name="InventoryStockChangedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class InventoryLowStockAlertEvent(NeuroEvent):
    """库存不足预警事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "inventory.low_stock_alert",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("product_id", "current_stock", "threshold"),
            class_name="InventoryLowStockAlertEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class InventoryStockInEvent(NeuroEvent):
    """入库事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "inventory.stock_in",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("product_id", "warehouse_id", "quantity", "batch_no"),
            class_name="InventoryStockInEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class InventoryStockOutEvent(NeuroEvent):
    """出库事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "inventory.stock_out",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("product_id", "warehouse_id", "quantity", "reference_id"),
            class_name="InventoryStockOutEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class InventoryTransferEvent(NeuroEvent):
    """库存调拨事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "inventory.transfer",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("product_id", "from_warehouse", "to_warehouse", "quantity"),
            class_name="InventoryTransferEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class InventoryCheckCompletedEvent(NeuroEvent):
    """库存盘点完成事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "inventory.check_completed",
        priority: EventPriority = EventPriority.LOW,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("warehouse_id", "check_date", "differences"),
            class_name="InventoryCheckCompletedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )
