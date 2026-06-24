"""
Wechat 领域事件处理器（V2）

对齐 ocr_domain_handlers / print_domain_handlers 的「类 + bus.subscribe」写法。

历史背景：原实现用 ``@domain.on(...)`` 装饰器，依赖 ``NeuroDomain.on``。
``register_wechat_domain_handlers`` 同时被两条路径调用——

1. ``wechat_domain.WechatNeuroDomain._setup_handlers`` 传入 *domain* 实例；
2. mod ``neuro_handler_catalog`` 经 ``register_all_domain_handlers`` 传入 *bus* 实例。

``NeuroBus`` 没有 ``.on``，故 catalog 路径会抛
``AttributeError: 'NeuroBus' object has no attribute 'on'``。

本实现统一改用 ``bus.subscribe``：从入参解析出 bus（domain 取 ``.bus``，bus 直用），
并以单例 + ``_registered`` 守卫保证两条路径只订阅一次，避免重复注册。
"""

import logging
from typing import Any

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_wechat_domain_handlers", "get_wechat_handlers", "WechatDomainHandlers"]


class WechatDomainHandlers:
    """Wechat 领域事件处理器。"""

    def __init__(self, bus=None):
        self.bus = bus or get_neuro_bus()
        self._registered = False

    def register(self) -> None:
        """订阅 Wechat 领域事件；幂等，重复调用不会重复订阅。"""
        if self._registered:
            return
        self.bus.subscribe("wechat.message.received", self.on_message, priority=1)
        self.bus.subscribe("wechat.payment.callback", self.on_payment, priority=0)
        self._registered = True
        logger.info("[WechatDomain] 所有事件处理器已注册")

    async def on_message(self, event: NeuroEvent) -> dict[str, Any]:
        msg_type = event.payload.get("msg_type")
        from_user = event.payload.get("from_user")
        logger.info("WeChat message: type=%s sender=%s", msg_type, from_user)
        bump_domain_handler_metric("wechat.message.received")
        return {"success": True, "event_type": "wechat.message.received"}

    async def on_payment(self, event: NeuroEvent) -> dict[str, Any]:
        order_id = event.payload.get("order_id")
        status = event.payload.get("status")
        logger.info("WeChat payment: order=%s, status=%s", order_id, status)
        bump_domain_handler_metric("wechat.payment.callback")
        return {"success": True, "event_type": "wechat.payment.callback"}


# 全局处理器单例（与 ocr_domain_handlers 一致）
_handlers: WechatDomainHandlers | None = None


def get_wechat_handlers(bus=None) -> WechatDomainHandlers:
    """获取领域处理器单例。"""
    global _handlers
    if _handlers is None:
        _handlers = WechatDomainHandlers(bus)
    return _handlers


def _resolve_bus(target):
    """从入参解析 NeuroBus：bus 直用，domain 取 ``.bus``，兜底 get_neuro_bus()。"""
    if hasattr(target, "subscribe"):
        return target
    bus = getattr(target, "bus", None)
    if bus is not None:
        return bus
    return get_neuro_bus()


def register_wechat_domain_handlers(target) -> None:
    """注册所有 Wechat 领域事件处理器到 NeuroBus。

    ``target`` 可为 NeuroBus（mod catalog 路径）或 NeuroDomain（旧域路径）。
    """
    bus = _resolve_bus(target)
    handlers = get_wechat_handlers(bus)
    handlers.register()
    logger.info("[WechatDomain] register_wechat_domain_handlers 完成")
