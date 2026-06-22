"""潜意识 ML 处理器——SubconsciousProcessor 的 ML 驱动处理器。

整合 ``LocalEmbedder`` + ``AnomalyDetector`` + ``PatternPredictor``，
为 ``SubconsciousProcessor`` 提供 ML 驱动的后台分析能力。

处理流程：
1. 从事件 payload 提取处理器类型 / 延迟 / SLA / 成功状态
2. ``AnomalyDetector.add_sample()`` + ``predict()`` 检测异常
3. ``PatternPredictor.observe()`` + ``predict()`` 预测下一模式
4. ``LocalEmbedder.embed_query()`` 向量化文本（供后续分析）
5. 返回分析结果（异常标记 + 预测 + 嵌入向量）

SLA 感知：
- Subconscious 目标 < 10ms。
- IsolationForest.predict < 1ms，N-gram 查找 < 0.1ms，HashEmbedder < 0.1ms。
- 总延迟 < 2ms，满足 SLA。

注册方式：
    processor = get_subconscious_processor()
    processor.register_handler("routing.decision", SubconsciousMLHandler())
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.domain.neuro.subconscious.anomaly_detector import (
    AnomalyDetector,
    get_anomaly_detector,
)
from app.domain.neuro.subconscious.local_embedder import (
    LocalEmbedder,
    get_local_embedder,
)
from app.domain.neuro.subconscious.pattern_predictor import (
    PatternPredictor,
    get_pattern_predictor,
)
from app.neuro_bus.events.base import NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class SubconsciousMLHandler:
    """ML 驱动的潜意识处理器。

    可注册到 ``SubconsciousProcessor.register_handler()``。

    处理 ``routing.decision`` 类事件，执行：
    - 异常检测（IsolationForest）
    - 模式预测（N-gram + Markov）
    - 文本向量化（HashEmbedder）

    Args:
        embedder: 本地嵌入器（默认全局单例）。
        anomaly_detector: 异常检测器（默认全局单例）。
        pattern_predictor: 模式预测器（默认全局单例）。
    """

    def __init__(
        self,
        embedder: LocalEmbedder | None = None,
        anomaly_detector: AnomalyDetector | None = None,
        pattern_predictor: PatternPredictor | None = None,
    ) -> None:
        self._embedder = embedder or get_local_embedder()
        self._anomaly_detector = anomaly_detector or get_anomaly_detector()
        self._pattern_predictor = pattern_predictor or get_pattern_predictor()

    async def handle(self, event: NeuroEvent) -> dict[str, Any]:
        """处理 ``routing.decision`` 事件。

        事件 payload 期望字段：
        - ``processor_type``: 处理器类型（reflex/subconscious/conscious）
        - ``latency_ms``: 延迟（毫秒）
        - ``sla_hit``: 是否命中 SLA
        - ``success``: 是否成功
        - ``text``: 原始文本（可选，用于向量化）

        Returns:
            分析结果字典。
        """
        start = time.perf_counter()
        payload = event.payload or {}

        processor_type = str(payload.get("processor_type") or "conscious")
        latency_ms = float(payload.get("latency_ms") or 0.0)
        sla_hit = bool(payload.get("sla_hit", True))
        success = bool(payload.get("success", True))
        text = str(payload.get("text") or "")

        result: dict[str, Any] = {
            "processed": True,
            "anomaly": None,
            "prediction": None,
            "embedded": False,
        }

        # 1. 异常检测
        try:
            self._anomaly_detector.add_sample(
                processor_type=processor_type,
                latency_ms=latency_ms,
                sla_hit=sla_hit,
                success=success,
            )
            anomaly_result = self._anomaly_detector.predict(
                processor_type=processor_type,
                latency_ms=latency_ms,
                sla_hit=sla_hit,
                success=success,
            )
            result["anomaly"] = {
                "is_anomaly": anomaly_result.is_anomaly,
                "score": anomaly_result.anomaly_score,
                "reason": anomaly_result.reason,
            }
            if anomaly_result.is_anomaly:
                logger.warning(
                    "Anomaly detected: processor=%s latency=%.1fms sla=%s success=%s score=%.3f",
                    processor_type,
                    latency_ms,
                    sla_hit,
                    success,
                    anomaly_result.anomaly_score,
                )
        except RECOVERABLE_ERRORS:
            logger.debug("anomaly detection skipped", exc_info=True)

        # 2. 模式预测
        try:
            self._pattern_predictor.observe(processor_type)
            prediction = self._pattern_predictor.predict()
            result["prediction"] = {
                "next_processor": prediction.predicted,
                "confidence": prediction.confidence,
                "alternatives": prediction.alternatives,
                "reason": prediction.reason,
            }
        except RECOVERABLE_ERRORS:
            logger.debug("pattern prediction skipped", exc_info=True)

        # 3. 文本向量化（可选）
        if text:
            try:
                vec = self._embedder.embed_query(text)
                result["embedded"] = len(vec) > 0
                result["vector_dim"] = len(vec)
            except RECOVERABLE_ERRORS:
                logger.debug("embedding skipped", exc_info=True)

        elapsed_ms = (time.perf_counter() - start) * 1000
        result["latency_ms"] = elapsed_ms

        return result


_handler: SubconsciousMLHandler | None = None


def get_subconscious_ml_handler() -> SubconsciousMLHandler:
    """获取全局 ``SubconsciousMLHandler`` 单例。"""
    global _handler
    if _handler is None:
        _handler = SubconsciousMLHandler()
    return _handler


def reset_subconscious_ml_handler() -> None:
    """重置单例（测试用）。"""
    global _handler
    _handler = None
