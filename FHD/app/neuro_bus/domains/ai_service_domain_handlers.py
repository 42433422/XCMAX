"""
AI Service 领域处理器逻辑

从 ai_service_domain.py 迁出的 @self.on 处理器闭包。
通过 register_ai_service_domain_handlers(domain) 注册到 domain 实例。
"""

import logging

from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

logger = logging.getLogger(__name__)

__all__ = ["register_ai_service_domain_handlers"]


def register_ai_service_domain_handlers(domain):
    """注册 AI Service 领域事件处理器到 domain 实例。

    将原 ai_service_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """
    @domain.on("ai.completed", priority=1)
    async def on_completed(event):
        domain._request_count += 1
        model = event.payload.get("model")
        latency_ms = event.payload.get("latency_ms")
        logger.debug("AI completed: model=%s, latency=%sms", model, latency_ms)
        from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

        bump_domain_handler_metric("ai.completed")

    @domain.on("ai.failed", priority=0)
    async def on_failed(event):
        domain._error_count += 1
        model = event.payload.get("model")
        error = event.payload.get("error")
        logger.error("AI failed: model=%s, error=%s", model, error)
        bump_domain_handler_metric("ai.failed")
