"""
Payment 领域事件处理器（V2）

对齐 ocr/wechat 的「类 + bus.subscribe」写法。原实现用 ``@domain.on``，
而 mod ``neuro_handler_catalog`` 经 ``register_all_domain_handlers`` 传入 *bus*
（无 ``.on``），导致启动时抛 ``AttributeError: 'NeuroBus' object has no attribute 'on'``。
改用 ``bus.subscribe``：从入参解析 bus（domain 取 ``.bus``，bus 直用），单例 + 守卫幂等。

交易计数由处理器实例自持（原写入 domain._transaction_count；domain.get_stats 未经任何
路由暴露，仅由 NeuroBus 内部统计，故迁入本类不影响外部读取）。
"""

import logging
from decimal import Decimal
from typing import Any

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_payment_domain_handlers", "get_payment_handlers", "PaymentDomainHandlers"]


class PaymentDomainHandlers:
    """Payment 领域事件处理器（自持交易计数）。"""

    def __init__(self, bus=None):
        self.bus = bus or get_neuro_bus()
        self._registered = False
        self._transaction_count = 0
        self._total_amount = Decimal("0")
        self._failed_count = 0

    def register(self) -> None:
        if self._registered:
            return
        self.bus.subscribe("payment.completed", self.on_completed, priority=0)
        self.bus.subscribe("payment.failed", self.on_failed, priority=0)
        self._registered = True
        logger.info("[PaymentDomain] 所有事件处理器已注册")

    async def on_completed(self, event: NeuroEvent) -> dict[str, Any]:
        self._transaction_count += 1
        amount = Decimal(str(event.payload.get("amount", "0")))
        self._total_amount += amount
        logger.info("Payment completed: amount=%s", amount)
        bump_domain_handler_metric("payment.completed")
        return {"success": True, "event_type": "payment.completed"}

    async def on_failed(self, event: NeuroEvent) -> dict[str, Any]:
        self._failed_count += 1
        error = event.payload.get("error")
        logger.error("Payment failed: %s", error)
        bump_domain_handler_metric("payment.failed")
        return {"success": True, "event_type": "payment.failed"}


_handlers: PaymentDomainHandlers | None = None


def get_payment_handlers(bus=None) -> PaymentDomainHandlers:
    global _handlers
    if _handlers is None:
        _handlers = PaymentDomainHandlers(bus)
    return _handlers


def _resolve_bus(target):
    if hasattr(target, "subscribe"):
        return target
    bus = getattr(target, "bus", None)
    if bus is not None:
        return bus
    return get_neuro_bus()


def register_payment_domain_handlers(target) -> None:
    """注册所有 Payment 领域事件处理器到 NeuroBus（接受 NeuroBus 或 NeuroDomain）。"""
    get_payment_handlers(_resolve_bus(target)).register()
