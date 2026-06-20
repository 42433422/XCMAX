"""
Safety 领域处理器逻辑

从 safety_domain.py 迁出的 @self.on 处理器闭包。
通过 register_safety_domain_handlers(domain) 注册到 domain 实例。
"""

import logging

from app.neuro_bus.domains.base import DomainChannel
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_safety_domain_handlers"]


def register_safety_domain_handlers(domain):
    """注册 Safety 领域事件处理器到 domain 实例。

    将原 safety_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """

    @domain.on("security.threat.detected", priority=0, channel=DomainChannel.CRITICAL)
    async def on_threat(event):
        domain._threat_count += 1
        threat_type = event.payload.get("threat_type")
        severity = event.payload.get("severity")
        logger.critical("SECURITY THREAT: type=%s, severity=%s", threat_type, severity)
        bump_domain_handler_metric("security.threat.detected")

    @domain.on("security.audit.log", priority=2, channel=DomainChannel.CRITICAL)
    async def on_audit(event):
        domain._audit_count += 1
        action = event.payload.get("action")
        user_id = event.payload.get("user_id")
        logger.info("Audit: user=%s, action=%s", user_id, action)
        bump_domain_handler_metric("security.audit.log")
