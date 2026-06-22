"""
Order 领域处理器逻辑

从 order_domain.py 迁出的 @self.on 处理器闭包。
通过 register_order_domain_handlers(domain) 注册到 domain 实例。
"""

import logging

from app.neuro_bus.domains.base import DomainChannel
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_order_domain_handlers"]


def register_order_domain_handlers(domain):
    """注册 Order 领域事件处理器到 domain 实例。

    将原 order_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """

    @domain.on("order.created", priority=1, channel=DomainChannel.RELIABLE)
    async def on_order_created(event):
        order_id = event.payload.get("order_id")
        logger.info("Order created: %s", order_id)
        bump_domain_handler_metric("order.created")

    @domain.on("order.paid", priority=0, channel=DomainChannel.RELIABLE)
    async def on_order_paid(event):
        order_id = event.payload.get("order_id")
        amount = event.payload.get("amount")
        logger.info("Order paid: %s, amount=%s", order_id, amount)
        from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

        bump_domain_handler_metric("order.paid")

    @domain.on("order.shipped", priority=1, channel=DomainChannel.STANDARD)
    async def on_order_shipped(event):
        order_id = event.payload.get("order_id")
        shipment_id = event.payload.get("shipment_id")
        logger.info("Order shipped: %s, shipment=%s", order_id, shipment_id)
        bump_domain_handler_metric("order.shipped")
