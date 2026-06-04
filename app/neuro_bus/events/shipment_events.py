"""
Shipment 领域事件定义

包含发货单生命周期中的所有领域事件。
"""

from __future__ import annotations

from typing import Any

from app.neuro_bus.events._typed_event import init_typed_event
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


class ShipmentCreatedEvent(NeuroEvent):
    """发货单创建事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.created",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("shipment_id", "unit_name"),
            class_name="ShipmentCreatedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class ShipmentItemAddedEvent(NeuroEvent):
    """发货单添加产品事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.item_added",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("shipment_id", "product_id", "quantity"),
            class_name="ShipmentItemAddedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class ShipmentPrintedEvent(NeuroEvent):
    """发货单打印事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.printed",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("shipment_id",),
            class_name="ShipmentPrintedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class ShipmentCancelledEvent(NeuroEvent):
    """发货单取消事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.cancelled",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("shipment_id",),
            class_name="ShipmentCancelledEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class ShipmentDeletedEvent(NeuroEvent):
    """发货单删除事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.deleted",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("shipment_id",),
            class_name="ShipmentDeletedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class ShipmentExportedEvent(NeuroEvent):
    """发货单导出事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.exported",
        priority: EventPriority = EventPriority.LOW,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("file_path",),
            class_name="ShipmentExportedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class ShipmentInventoryDeductedEvent(NeuroEvent):
    """发货单库存扣减事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "shipment.inventory_deducted",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("shipment_id", "items"),
            class_name="ShipmentInventoryDeductedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )
