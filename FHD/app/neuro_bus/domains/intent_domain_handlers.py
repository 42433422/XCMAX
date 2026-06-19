"""
Intent 领域处理器逻辑

从 intent_domain.py 迁出的 @self.on 处理器闭包。
通过 register_intent_domain_handlers(domain) 注册到 domain 实例。
"""

import logging

from app.neuro_bus.domains.base import DomainChannel
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

__all__ = ["register_intent_domain_handlers"]


def register_intent_domain_handlers(domain):
    """注册 Intent 领域事件处理器到 domain 实例。

    将原 intent_domain.py 中 _setup_handlers 的闭包迁出至此，
    业务逻辑保持不变（仅将 self 改为 domain 参数）。
    """

    @domain.on("intent.recognized", priority=0, channel=DomainChannel.FAST)
    async def on_intent_recognized(event: NeuroEvent):
        """意图识别完成"""
        domain._recognized_count += 1
        intent_type = event.payload.get("intent_type")
        confidence = event.payload.get("confidence", 0.0)
        processor = event.payload.get("processor_used", "unknown")

        if processor == "reflex":
            domain._reflex_count += 1

        logger.debug(
            f"Intent recognized: {intent_type} (confidence={confidence:.2f}, processor={processor})"  # noqa: G004
        )
        try:
            from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

            bump_domain_handler_metric("intent.recognized")
        except RECOVERABLE_ERRORS:
            pass

    @domain.on("intent.processing", priority=1, channel=DomainChannel.FAST)
    async def on_intent_processing(event: NeuroEvent):
        """意图处理中"""
        intent_type = event.payload.get("intent_type")
        logger.debug("Intent processing: %s", intent_type)
        try:
            from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

            bump_domain_handler_metric("intent.processing")
        except RECOVERABLE_ERRORS:
            pass

    @domain.on("intent.failed", priority=0, channel=DomainChannel.STANDARD)
    async def on_intent_failed(event: NeuroEvent):
        """意图处理失败"""
        domain._failed_count += 1
        intent_type = event.payload.get("intent_type")
        error = event.payload.get("error", "Unknown")
        logger.error("Intent failed: %s, error: %s", intent_type, error)
        try:
            from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

            bump_domain_handler_metric("intent.failed")
        except RECOVERABLE_ERRORS:
            pass

    @domain.on("intent.reflex_triggered", priority=0, channel=DomainChannel.FAST)
    async def on_reflex_triggered(event: NeuroEvent):
        """反射弧触发"""
        domain._reflex_count += 1
        reflex_type = event.payload.get("reflex_type")
        latency_ms = event.payload.get("latency_ms", 0)
        logger.debug(f"Reflex triggered: {reflex_type} ({latency_ms:.2f}ms)")  # noqa: G004
        try:
            from app.neuro_bus.neuro_trace_config import bump_domain_handler_metric

            bump_domain_handler_metric("intent.reflex_triggered")
        except RECOVERABLE_ERRORS:
            pass
