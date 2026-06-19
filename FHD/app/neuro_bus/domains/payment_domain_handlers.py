"""
Payment 领域处理器逻辑

从 payment_domain.py 迁出的 @self.on 处理器闭包。
通过 register_payment_domain_handlers(domain) 注册到 domain 实例。
"""

import logging
from decimal import Decimal

from app.neuro_bus.domains.base import DomainChannel
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_payment_domain_handlers"]


def register_payment_domain_handlers(domain):
    """注册 Payment 领域事件处理器到 domain 实例。

    将原 payment_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """
    @domain.on("payment.completed", priority=0, channel=DomainChannel.CRITICAL)
    async def on_completed(event):
        domain._transaction_count += 1
        amount = Decimal(event.payload.get("amount", "0"))
        domain._total_amount += amount
        logger.info("Payment completed: amount=%s", amount)
        bump_domain_handler_metric("payment.completed")

    @domain.on("payment.failed", priority=0, channel=DomainChannel.CRITICAL)
    async def on_failed(event):
        domain._failed_count += 1
        error = event.payload.get("error")
        logger.error("Payment failed: %s", error)
        bump_domain_handler_metric("payment.failed")
