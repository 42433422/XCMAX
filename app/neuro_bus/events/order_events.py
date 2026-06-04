"""
Order 领域事件定义

包含订单生命周期中的所有领域事件。
"""

from __future__ import annotations

from typing import Any

from app.neuro_bus.events._typed_event import init_typed_event
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent


class OrderSubmittedEvent(NeuroEvent):
    """订单提交事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.submitted",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id", "customer_id", "items"),
            class_name="OrderSubmittedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderPaidEvent(NeuroEvent):
    """订单支付事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.paid",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id", "payment_id", "amount"),
            class_name="OrderPaidEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderPaymentFailedEvent(NeuroEvent):
    """订单支付失败事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.payment_failed",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id",),
            class_name="OrderPaymentFailedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderFulfilledEvent(NeuroEvent):
    """订单履行完成事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.fulfilled",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id",),
            class_name="OrderFulfilledEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderShippedEvent(NeuroEvent):
    """订单发货事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.shipped",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id", "shipment_id", "tracking_number"),
            class_name="OrderShippedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderCancelledEvent(NeuroEvent):
    """订单取消事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.cancelled",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id",),
            class_name="OrderCancelledEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderRefundedEvent(NeuroEvent):
    """订单退款事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.refunded",
        priority: EventPriority = EventPriority.HIGH,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id", "refund_id", "refund_amount"),
            class_name="OrderRefundedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderItemUpdatedEvent(NeuroEvent):
    """订单项更新事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.item_updated",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id", "item_id", "changes"),
            class_name="OrderItemUpdatedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )


class OrderStatusChangedEvent(NeuroEvent):
    """订单状态变更事件"""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        event_type: str = "order.status_changed",
        priority: EventPriority = EventPriority.NORMAL,
        metadata: EventMetadata | None = None,
        preserve_queue_identity: bool = False,
    ) -> None:
        init_typed_event(
            self,
            payload,
            event_type=event_type,
            priority=priority,
            required=("order_id", "old_status", "new_status"),
            class_name="OrderStatusChangedEvent",
            metadata=metadata,
            preserve_queue_identity=preserve_queue_identity,
        )
