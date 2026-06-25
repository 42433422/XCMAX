"""
Customer 领域事件处理器（V2）

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

__all__ = ["register_customer_domain_handlers", "get_customer_handlers", "CustomerDomainHandlers"]


class CustomerDomainHandlers:
    """Customer 领域事件处理器。"""

    def __init__(self, bus=None):
        self.bus = bus or get_neuro_bus()
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        self.bus.subscribe("customer.registered", self.on_registered, priority=1)
        self.bus.subscribe("customer.login", self.on_login, priority=2)
        self._registered = True
        logger.info("[CustomerDomain] 所有事件处理器已注册")

    async def on_registered(self, event: NeuroEvent) -> dict[str, Any]:
        customer_id = event.payload.get("customer_id")
        logger.info("Customer registered: %s", customer_id)
        bump_domain_handler_metric("customer.registered")
        return {"success": True, "event_type": "customer.registered"}

    async def on_login(self, event: NeuroEvent) -> dict[str, Any]:
        customer_id = event.payload.get("customer_id")
        logger.info("Customer login: %s", customer_id)
        bump_domain_handler_metric("customer.login")
        return {"success": True, "event_type": "customer.login"}


_handlers: CustomerDomainHandlers | None = None


def get_customer_handlers(bus=None) -> CustomerDomainHandlers:
    global _handlers
    if _handlers is None:
        _handlers = CustomerDomainHandlers(bus)
    return _handlers


def _resolve_bus(target):
    if hasattr(target, "subscribe"):
        return target
    bus = getattr(target, "bus", None)
    if bus is not None:
        return bus
    return get_neuro_bus()


def register_customer_domain_handlers(target) -> None:
    """注册所有 Customer 领域事件处理器到 NeuroBus（接受 NeuroBus 或 NeuroDomain）。"""
    get_customer_handlers(_resolve_bus(target)).register()
