"""
意图域（IntentNeuroDomain）

意图识别事件通道，优先级最高
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.neuro_bus.domains.base import DomainChannel, NeuroDomain, get_domain_registry
from app.neuro_bus.domains.intent_domain_handlers import register_intent_domain_handlers
from app.neuro_bus.events.base import EventPriority
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """意图识别结果"""

    intent_type: str
    confidence: float
    entities: dict[str, Any]
    raw_text: str
    processor_used: str  # "reflex", "subconscious", "conscious"
    latency_ms: float


class IntentNeuroDomain(NeuroDomain):
    """
    意图神经域

    处理：
    - 意图识别请求
    - 意图识别完成
    - 意图处理状态更新
    - Reflex 级快速响应
    """

    domain_name = "intent"
    default_channel = DomainChannel.FAST

    def __init__(self, bus=None):
        super().__init__(bus)

        # 统计
        self._recognized_count = 0
        self._reflex_count = 0
        self._failed_count = 0

        # 注册默认处理器（子类可覆盖）
        self._setup_handlers()

    def _setup_handlers(self):
        """设置默认事件处理器"""
        register_intent_domain_handlers(self)

    async def initialize(self):
        """初始化意图域"""
        logger.info("IntentNeuroDomain initialized")

    async def shutdown(self):
        """关闭意图域"""
        logger.info("IntentNeuroDomain shutdown")

    def emit_intent_recognized(
        self,
        intent_type: str,
        confidence: float,
        entities: dict[str, Any],
        raw_text: str,
        processor_used: str = "conscious",
        latency_ms: float = 0.0,
    ) -> bool:
        """
        发送意图识别完成事件
        """
        return self.emit(
            event_type="intent.recognized",
            priority=EventPriority.HIGH,
            payload={
                "intent_type": intent_type,
                "confidence": confidence,
                "entities": entities,
                "raw_text": raw_text,
                "processor_used": processor_used,
                "latency_ms": latency_ms,
            },
        )

    def emit_intent_processing(
        self,
        intent_type: str,
        user_id: str,
        stage: str = "started",
    ) -> bool:
        """
        发送意图处理中事件
        """
        return self.emit(
            event_type="intent.processing",
            priority=EventPriority.HIGH,
            payload={
                "intent_type": intent_type,
                "user_id": user_id,
                "stage": stage,
            },
        )

    def emit_intent_failed(
        self,
        intent_type: str,
        user_id: str,
        error: str,
        raw_text: str = "",
    ) -> bool:
        """
        发送意图处理失败事件
        """
        return self.emit(
            event_type="intent.failed",
            priority=EventPriority.NORMAL,
            payload={
                "intent_type": intent_type,
                "user_id": user_id,
                "error": error,
                "raw_text": raw_text,
            },
        )

    def emit_reflex_triggered(
        self,
        reflex_type: str,
        latency_ms: float,
        user_id: str,
    ) -> bool:
        """
        发送反射弧触发事件
        """
        return self.emit(
            event_type="intent.reflex_triggered",
            priority=EventPriority.CRITICAL,
            payload={
                "reflex_type": reflex_type,
                "latency_ms": latency_ms,
                "user_id": user_id,
            },
        )

    def get_stats(self) -> dict[str, Any]:
        """获取统计"""
        base_stats = super().get_stats()
        out = {
            **base_stats,
            "recognized": self._recognized_count,
            "reflex_triggers": self._reflex_count,
            "failed": self._failed_count,
            "reflex_rate": self._reflex_count / max(self._recognized_count, 1),
        }
        try:
            from app.neuro_bus.neuro_trace_config import (
                get_domain_handler_metrics,
                is_neuro_domain_metrics_enabled,
            )

            if is_neuro_domain_metrics_enabled():
                allm = get_domain_handler_metrics()
                intent_only = {k: v for k, v in allm.items() if k.startswith("intent.")}
                if intent_only:
                    out["handler_metrics"] = intent_only
        except RECOVERABLE_ERRORS:
            pass
        return out


# 单例
_intent_domain: IntentNeuroDomain | None = None


def get_intent_domain() -> IntentNeuroDomain:
    """获取意图域单例"""
    global _intent_domain
    if _intent_domain is None:
        _intent_domain = IntentNeuroDomain()
        get_domain_registry().register(_intent_domain)
    return _intent_domain
