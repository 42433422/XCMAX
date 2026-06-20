"""
Wechat 领域处理器逻辑

从 wechat_domain.py 迁出的 @self.on 处理器闭包。
通过 register_wechat_domain_handlers(domain) 注册到 domain 实例。
"""

import logging

from app.neuro_bus.domains.base import DomainChannel
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_wechat_domain_handlers"]


def register_wechat_domain_handlers(domain):
    """注册 Wechat 领域事件处理器到 domain 实例。

    将原 wechat_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """

    @domain.on("wechat.message.received", priority=1)
    async def on_message(event):
        msg_type = event.payload.get("msg_type")
        from_user = event.payload.get("from_user")
        logger.info("WeChat message: type=%s sender=%s", msg_type, from_user)
        from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

        bump_domain_handler_metric("wechat.message.received")

    @domain.on("wechat.payment.callback", priority=0, channel=DomainChannel.RELIABLE)
    async def on_payment(event):
        order_id = event.payload.get("order_id")
        status = event.payload.get("status")
        logger.info("WeChat payment: order=%s, status=%s", order_id, status)
        bump_domain_handler_metric("wechat.payment.callback")
