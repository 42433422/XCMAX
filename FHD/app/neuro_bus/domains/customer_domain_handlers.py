"""
Customer 领域处理器逻辑

从 customer_domain.py 迁出的 @self.on 处理器闭包。
通过 register_customer_domain_handlers(domain) 注册到 domain 实例。
"""

import logging

from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_customer_domain_handlers"]


def register_customer_domain_handlers(domain):
    """注册 Customer 领域事件处理器到 domain 实例。

    将原 customer_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """
    @domain.on("customer.registered", priority=1)
    async def on_registered(event):
        customer_id = event.payload.get("customer_id")
        logger.info("Customer registered: %s", customer_id)
        bump_domain_handler_metric("customer.registered")

    @domain.on("customer.login", priority=2)
    async def on_login(event):
        customer_id = event.payload.get("customer_id")
        logger.info("Customer login: %s", customer_id)
        bump_domain_handler_metric("customer.login")
