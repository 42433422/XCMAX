"""
Order 领域事件处理器（V2）

对齐 ocr/wechat 的「类 + bus.subscribe」写法。原实现用 ``@domain.on``，
而 mod ``neuro_handler_catalog`` 经 ``register_all_domain_handlers`` 传入 *bus*
（无 ``.on``），导致启动时抛 ``AttributeError: 'NeuroBus' object has no attribute 'on'``。
改用 ``bus.subscribe``：从入参解析 bus（domain 取 ``.bus``，bus 直用），单例 + 守卫幂等。
"""

import logging
from typing import Any

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_order_domain_handlers", "get_order_handlers", "OrderDomainHandlers"]


class OrderDomainHandlers:
    """Order 领域事件处理器。"""

    def __init__(self, bus=None):
        self.bus = bus or get_neuro_bus()
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        self.bus.subscribe("order.created", self.on_order_created, priority=1)
        self.bus.subscribe("order.paid", self.on_order_paid, priority=0)
        self.bus.subscribe("order.shipped", self.on_order_shipped, priority=1)
        self._registered = True
        logger.info("[OrderDomain] 所有事件处理器已注册")

    async def on_order_created(self, event: NeuroEvent) -> dict[str, Any]:
        order_id = event.payload.get("order_id")
        logger.info("Order created: %s", order_id)
        bump_domain_handler_metric("order.created")
        return {"success": True, "event_type": "order.created"}

    async def on_order_paid(self, event: NeuroEvent) -> dict[str, Any]:
        order_id = event.payload.get("order_id")
        amount = event.payload.get("amount")
        logger.info("Order paid: %s, amount=%s", order_id, amount)
        bump_domain_handler_metric("order.paid")
        return {"success": True, "event_type": "order.paid"}

    async def on_order_shipped(self, event: NeuroEvent) -> dict[str, Any]:
        order_id = event.payload.get("order_id")
        shipment_id = event.payload.get("shipment_id")
        logger.info("Order shipped: %s, shipment=%s", order_id, shipment_id)
        bump_domain_handler_metric("order.shipped")
        return {"success": True, "event_type": "order.shipped"}


_handlers: OrderDomainHandlers | None = None


def get_order_handlers(bus=None) -> OrderDomainHandlers:
    global _handlers
    if _handlers is None:
        _handlers = OrderDomainHandlers(bus)
    return _handlers


def _resolve_bus(target):
    if hasattr(target, "subscribe"):
        return target
    bus = getattr(target, "bus", None)
    if bus is not None:
        return bus
    return get_neuro_bus()


def register_order_domain_handlers(target) -> None:
    """注册所有 Order 领域事件处理器到 NeuroBus（接受 NeuroBus 或 NeuroDomain）。"""
    get_order_handlers(_resolve_bus(target)).register()
