"""认知路由器（CognitiveRouter）

元认知层：用 MLP 策略网络决定意图/事件走哪一级处理器。
- Reflex (<1ms): 正则反射弧
- Subconscious (<10ms): 后台 ML 推理（Phase 3 升级）
- Conscious (<200ms-5s): LLM 慎思（Phase 2 升级）

支持 shadow/canary/full 灰度模式（复用 policy_router 逻辑）。
路由决策写入 routing_decisions.jsonl，供 online_learner 在线学习。

Phase 1：接通 MLP v2 到生产意图识别路径，让学到的策略真实生效。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from app.domain.neuro.processors.coordinator import ProcessorType, RoutingDecision
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.routing.policy_router import decide_processor_with_policy
from app.neuro_bus.routing.routing_log import append_routing_decision
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 各级处理器的 SLA 阈值（毫秒），用于判断 sla_hit
_SLA_THRESHOLDS_MS: dict[ProcessorType, float] = {
    ProcessorType.REFLEX: 1.0,
    ProcessorType.SUBCONSCIOUS: 10.0,
    ProcessorType.CONSCIOUS: 200.0,
}


class CognitiveRouter:
    """元认知路由器：MLP 策略 → 处理器分级。

    在 NeuroIntentRecognizer.recognize() 中调用，用学到的 MLP 策略
    决定意图走 Reflex / Subconscious / Conscious 哪一级。
    MLP 未启用或 shadow 模式时返回 None，调用方回退到规则路由。
    """

    def route(
        self,
        text: str,
        event: NeuroEvent | None = None,
        *,
        trace_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[RoutingDecision | None, str]:
        """返回 (路由决策, trace_id)。

        - 决策为 None: MLP 未启用 / shadow 模式 / canary 未命中 → 回退规则路由
        - 决策非 None: MLP 决策了处理器分级

        trace_id 用于后续记录决策结果（反馈闭环）。
        """
        tid = trace_id or uuid.uuid4().hex[:16]
        try:
            decision = decide_processor_with_policy(text, event, trace_id=tid, extra=extra)
        except RECOVERABLE_ERRORS:
            logger.debug(
                "CognitiveRouter.route failed, fallback to rule-based",
                exc_info=True,
            )
            decision = None
        return decision, tid

    def record_outcome(
        self,
        trace_id: str,
        processor_type: ProcessorType,
        features: list[float] | None,
        latency_ms: float,
        sla_hit: bool,
        success: bool,
        confidence: float = 0.0,
    ) -> None:
        """记录路由决策的结果（反馈闭环）。

        online_learner 通过 routing_decisions.jsonl 消费这些样本：
        reward = sla_hit * 0.6 + success * 0.4
        """
        try:
            append_routing_decision(
                trace_id=trace_id,
                features=features or [],
                action=processor_type.value,
                latency_ms=latency_ms,
                outcome="policy_completed",
                reward=sla_hit * 0.6 + success * 0.4,
                sla_hit=sla_hit,
                success=success,
                extra={
                    "source": "cognitive_router_outcome",
                    "confidence": confidence,
                },
            )
        except RECOVERABLE_ERRORS:
            logger.debug("record_outcome failed", exc_info=True)

    @staticmethod
    def is_sla_hit(processor_type: ProcessorType, latency_ms: float) -> bool:
        """判断延迟是否命中该处理器的 SLA 阈值。"""
        threshold = _SLA_THRESHOLDS_MS.get(processor_type, 200.0)
        return latency_ms <= threshold

    @staticmethod
    def is_enabled() -> bool:
        """MLP 路由是否启用（任何模式：shadow/canary/full）。"""
        raw = (os.environ.get("XCAGI_ROUTING_POLICY_ENABLED") or "").strip().lower()
        return raw in {"1", "true", "yes", "on", "shadow", "canary", "full"}


_router: CognitiveRouter | None = None


def get_cognitive_router() -> CognitiveRouter:
    """获取 CognitiveRouter 单例。"""
    global _router
    if _router is None:
        _router = CognitiveRouter()
    return _router


def reset_cognitive_router() -> None:
    """重置单例（测试用）。"""
    global _router
    _router = None
