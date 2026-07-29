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

from app.domain.neuro.cognition.plan_constraints import (
    is_sla_hit_soft,
    load_soft_constraints,
    select_processor_by_cost,
)
from app.domain.neuro.processors.coordinator import ProcessorType, RoutingDecision
from app.neuro_bus.events.base import NeuroEvent
from app.neuro_bus.routing.policy_router import decide_processor_with_policy
from app.neuro_bus.routing.routing_log import append_routing_decision
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 硬阈值仅作兜底先验；生产判断走 soft_constraints（可被 Evolution 白名单晋升）
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

        额外：将软约束路径建议写入 extra（供日志/编排器），不硬杀请求。
        """
        tid = trace_id or uuid.uuid4().hex[:16]
        enriched_extra = dict(extra or {})
        try:
            prefer = None
            conf = float(enriched_extra.get("intent_confidence") or 0.0)
            if conf >= 0.85:
                prefer = "reflex"
            elif conf > 0 and conf < 0.45:
                prefer = "conscious"
            soft = select_processor_by_cost(prefer=prefer)
            enriched_extra["soft_constraint_path"] = soft
        except RECOVERABLE_ERRORS:
            logger.debug("soft constraint suggestion skipped", exc_info=True)
        try:
            decision = decide_processor_with_policy(
                text, event, trace_id=tid, extra=enriched_extra
            )
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
        """判断延迟是否命中软 SLA（允许 slack；阈值来自 soft_constraints）。"""
        try:
            constraints = load_soft_constraints()
            key = processor_type.value if hasattr(processor_type, "value") else str(processor_type)
            return is_sla_hit_soft(key, latency_ms, constraints=constraints)
        except RECOVERABLE_ERRORS:
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
