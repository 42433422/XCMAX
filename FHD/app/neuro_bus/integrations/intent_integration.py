"""
意图系统集成：ReflexArc + 主线 UnifiedIntentRecognizer + NeuroBus 事件。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from app.domain.neuro.processors.coordinator import ProcessorType
from app.domain.neuro.reflex_arc import IntentReflexArc, ReflexResult, ReflexType, get_reflex_arc
from app.neuro_bus.domains.intent_domain import get_intent_domain
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def is_neuro_stack_enabled() -> bool:
    """XCAGI_NEURO_INTENT 默认开启；设为 0/false/off/no 时关闭总线与意图桥接。"""
    raw = os.environ.get("XCAGI_NEURO_INTENT", "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def reflex_match_to_chat_intent_dict(rr: ReflexResult) -> dict[str, Any]:
    """将反射弧命中结果转成与 Hybrid / rule 路径一致的意图字典。"""
    rt = rr.reflex_type
    base: dict[str, Any] = {
        "primary_intent": None,
        "final_intent": None,
        "tool_key": None,
        "intent_hints": [],
        "is_negated": rt == ReflexType.DENIAL,
        "is_greeting": rt == ReflexType.GREETING,
        "is_goodbye": False,
        "is_help": rt == ReflexType.HELP,
        "is_confirmation": rt == ReflexType.CONFIRMATION,
        "is_negation_intent": rt == ReflexType.DENIAL,
        "is_likely_unclear": False,
        "slots": {"reflex_response": rr.response},
        "all_matched_tools": [],
        "intent_source": "neuro_reflex",
    }
    if rt == ReflexType.EMERGENCY_STOP and "emergency_stop" not in base["intent_hints"]:
        base["intent_hints"].append("emergency_stop")
    return base


def try_neuro_reflex_intent(message: str, user_id: str = "") -> dict[str, Any] | None:
    """
    非 pro 路径上的快速反射（问候/确认等）。总线未启动时仍返回意图字典，仅跳过 emit。
    """
    if not is_neuro_stack_enabled():
        return None
    t0 = time.perf_counter()
    reflex = get_reflex_arc()
    rr = reflex.process(message)
    if not (rr.triggered and rr.confidence >= 0.8):
        return None
    latency_ms = (time.perf_counter() - t0) * 1000
    try:
        dom = get_intent_domain()
        dom.emit_reflex_triggered(
            reflex_type=rr.reflex_type.value,
            latency_ms=latency_ms,
            user_id=user_id,
        )
    except RECOVERABLE_ERRORS:
        logger.debug("emit_reflex_triggered skipped (bus down?)", exc_info=True)
    return reflex_match_to_chat_intent_dict(rr)


@dataclass
class NeuroIntentResult:
    """神经意图识别结果（pro 路径：可携带完整 RecognizerResult）。"""

    intent: str
    confidence: float
    source: str
    processor_type: ProcessorType
    latency_ms: float
    entities: dict[str, Any]
    reflex_used: bool = False
    ai_enhanced: bool = False
    recognizer_result: Any | None = None


class NeuroIntentRecognizer:
    """
    1. ReflexArc 快速过滤
    2. app.services 统一意图识别（与 AI 对话 pro 模式一致）
    3. NeuroBus 上 intent 域事件
    """

    def __init__(
        self,
        reflex_arc: IntentReflexArc | None = None,
        base_recognizer: Any | None = None,
    ):
        from app.services.unified_intent_recognizer import get_unified_intent_recognizer

        self._reflex = reflex_arc or get_reflex_arc()
        self._base = base_recognizer or get_unified_intent_recognizer()

    def recognize(
        self,
        text: str,
        user_id: str = "",
        context: Any | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> NeuroIntentResult:
        """识别意图，用 MLP 元认知路由决定走 Reflex/Subconscious/Conscious。

        MLP 未启用或 shadow 模式时回退到规则路由（reflex confidence >= 0.8）。
        路由决策和结果写入 routing_decisions.jsonl，供 online_learner 学习。
        """
        from app.neuro_bus.routing.cognitive_router import get_cognitive_router

        start_time = time.perf_counter()
        reflex_result = self._reflex.process(text)

        # 元认知路由：MLP 决定走哪一级处理器
        cognitive_router = get_cognitive_router()
        cognitive_decision, trace_id = cognitive_router.route(
            text,
            extra={
                "intent_confidence": reflex_result.confidence if reflex_result.triggered else 0.0,
            },
        )

        result: NeuroIntentResult
        used_processor: ProcessorType

        if cognitive_decision is not None:
            # MLP 决策生效
            used_processor = cognitive_decision.processor_type
            if cognitive_decision.processor_type == ProcessorType.REFLEX:
                if reflex_result.triggered:
                    result = self._build_reflex_result(reflex_result, start_time, user_id)
                else:
                    # MLP 说 reflex 但没命中 → 降级到 conscious
                    result = self._build_conscious_result(
                        text,
                        user_id,
                        context,
                        context_data,
                        start_time,
                        ProcessorType.CONSCIOUS,
                    )
                    used_processor = ProcessorType.CONSCIOUS
            elif cognitive_decision.processor_type == ProcessorType.SUBCONSCIOUS:
                # Phase 1: subconscious 仍走 unified_recognizer（Phase 3 加 ML 推理）
                # 但标记 processor_type 为 SUBCONSCIOUS 供学习
                result = self._build_conscious_result(
                    text,
                    user_id,
                    context,
                    context_data,
                    start_time,
                    ProcessorType.SUBCONSCIOUS,
                )
            else:  # CONSCIOUS
                result = self._build_conscious_result(
                    text,
                    user_id,
                    context,
                    context_data,
                    start_time,
                    ProcessorType.CONSCIOUS,
                )
        else:
            # 回退到原逻辑（MLP 未启用或 shadow 模式）
            if reflex_result.triggered and reflex_result.confidence >= 0.8:
                used_processor = ProcessorType.REFLEX
                result = self._build_reflex_result(reflex_result, start_time, user_id)
            else:
                used_processor = ProcessorType.CONSCIOUS
                result = self._build_conscious_result(
                    text,
                    user_id,
                    context,
                    context_data,
                    start_time,
                    ProcessorType.CONSCIOUS,
                )

        # 记录路由结果（反馈闭环，供 online_learner 学习）
        latency_ms = (time.perf_counter() - start_time) * 1000
        sla_hit = cognitive_router.is_sla_hit(used_processor, latency_ms)
        success = result.intent != "unknown" and result.confidence > 0.5
        cognitive_router.record_outcome(
            trace_id=trace_id,
            processor_type=used_processor,
            features=None,
            latency_ms=latency_ms,
            sla_hit=sla_hit,
            success=success,
            confidence=result.confidence,
        )

        return result

    def _build_reflex_result(
        self,
        reflex_result: ReflexResult,
        start_time: float,
        user_id: str,
    ) -> NeuroIntentResult:
        """构建 Reflex 命中结果并 emit 事件。"""
        latency_ms = (time.perf_counter() - start_time) * 1000
        try:
            get_intent_domain().emit_reflex_triggered(
                reflex_type=reflex_result.reflex_type.value,
                latency_ms=latency_ms,
                user_id=user_id,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("emit_reflex_triggered skipped", exc_info=True)

        return NeuroIntentResult(
            intent=reflex_result.reflex_type.value,
            confidence=reflex_result.confidence,
            source="reflex",
            processor_type=ProcessorType.REFLEX,
            latency_ms=latency_ms,
            entities={"response": reflex_result.response},
            reflex_used=True,
            ai_enhanced=False,
            recognizer_result=None,
        )

    def _build_conscious_result(
        self,
        text: str,
        user_id: str,
        context: Any | None,
        context_data: dict[str, Any] | None,
        start_time: float,
        processor_type: ProcessorType = ProcessorType.CONSCIOUS,
    ) -> NeuroIntentResult:
        """走 unified_recognizer 构建 Conscious/Subconscious 结果并 emit 事件。"""
        from app.services.unified_intent_recognizer import RecognizerResult

        base_result = self._base.recognize(text, context=context, context_data=context_data)
        latency_ms = (time.perf_counter() - start_time) * 1000

        if isinstance(base_result, RecognizerResult):
            try:
                get_intent_domain().emit_intent_recognized(
                    intent_type=str(base_result.primary_intent or "unknown"),
                    confidence=float(base_result.confidence),
                    entities=dict(base_result.slots or {}),
                    raw_text=text,
                    processor_used=processor_type.value,
                    latency_ms=latency_ms,
                )
            except RECOVERABLE_ERRORS:
                logger.debug("emit_intent_recognized skipped", exc_info=True)

            return NeuroIntentResult(
                intent=str(base_result.primary_intent or "unknown"),
                confidence=float(base_result.confidence),
                source="unified",
                processor_type=processor_type,
                latency_ms=latency_ms,
                entities={},
                reflex_used=False,
                ai_enhanced=True,
                recognizer_result=base_result,
            )

        # 极少数回退：非 RecognizerResult
        br = base_result if isinstance(base_result, dict) else {}
        try:
            get_intent_domain().emit_intent_recognized(
                intent_type=str(br.get("intent", "unknown")),
                confidence=float(br.get("confidence", 0.0)),
                entities=dict(br.get("entities") or {}),
                raw_text=text,
                processor_used=processor_type.value,
                latency_ms=latency_ms,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("emit_intent_recognized skipped", exc_info=True)

        return NeuroIntentResult(
            intent=str(br.get("intent", "unknown")),
            confidence=float(br.get("confidence", 0.0)),
            source=str(br.get("source", "unified")),
            processor_type=processor_type,
            latency_ms=latency_ms,
            entities=dict(br.get("entities") or {}),
            reflex_used=False,
            ai_enhanced=True,
            recognizer_result=None,
        )

    async def recognize_async(self, text: str, user_id: str = "") -> NeuroIntentResult:
        return self.recognize(text, user_id)

    def should_use_reflex(self, text: str) -> bool:
        return self._reflex.should_handle(text)

    def get_stats(self) -> dict[str, Any]:
        return {"reflex": self._reflex.get_stats()}


def integrate_with_intent_system() -> NeuroIntentRecognizer:
    logger.info("Integrating Neuro stack with app.services unified intent recognizer...")
    try:
        get_reflex_arc()
        logger.info("ReflexArc ready")
    except RECOVERABLE_ERRORS as e:
        logger.warning("ReflexArc initialization error: %s", e)
    try:
        get_intent_domain()
        logger.info("IntentDomain ready")
    except RECOVERABLE_ERRORS as e:
        logger.warning("IntentDomain initialization error: %s", e)
    return NeuroIntentRecognizer()


_neuro_recognizer: NeuroIntentRecognizer | None = None


def get_neuro_intent_recognizer() -> NeuroIntentRecognizer:
    global _neuro_recognizer
    if _neuro_recognizer is None:
        _neuro_recognizer = integrate_with_intent_system()
    return _neuro_recognizer
