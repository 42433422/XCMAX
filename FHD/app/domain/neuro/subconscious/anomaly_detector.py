"""异常检测器（AnomalyDetector）——基于 IsolationForest 的在线异常检测。

检测维度：
1. **路由异常**：MLP 路由决策与历史模式不一致（如突然大量走 CONSCIOUS）。
2. **延迟异常**：处理器延迟突然飙升（如 Reflex 从 0.5ms 飙到 50ms）。
3. **错误异常**：错误率突然上升。

实现策略：
- 使用 ``sklearn.ensemble.IsolationForest``（已在 server-api 依赖中）。
- 特征向量：``[processor_type_idx, latency_ms, sla_hit, success, hour_of_day]``。
- 在线增量学习：每收到 N 个样本触发一次 ``partial_fit``（IsolationForest 不支持真正的 partial_fit，
  用滑动窗口重新拟合替代）。
- 推理 < 1ms（IsolationForest.predict 单样本极快）。

Phase 3 用途：为 SubconsciousProcessor 提供异常检测能力，发现系统行为偏移。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_WINDOW_SIZE = 200  # 滑动窗口大小
_MIN_SAMPLES_TO_FIT = 20  # 最少样本数才能拟合
_REFIT_INTERVAL = 50  # 每 N 个新样本重新拟合一次

# 处理器类型到数值的映射
_PROCESSOR_MAP = {"reflex": 0, "subconscious": 1, "conscious": 2}


@dataclass
class AnomalyResult:
    """异常检测结果。"""

    is_anomaly: bool = False
    anomaly_score: float = 0.0  # -1.0 (异常) ~ 1.0 (正常)
    feature_vector: list[float] = field(default_factory=list)
    reason: str = ""


class AnomalyDetector:
    """基于 IsolationForest 的异常检测器。

    特征向量：``[processor_type_idx, latency_ms_normalized, sla_hit, success, hour_normalized]``

    用法：
        detector = AnomalyDetector()
        detector.add_sample(processor_type="reflex", latency_ms=0.5, sla_hit=True, success=True)
        result = detector.predict(processor_type="reflex", latency_ms=50.0, sla_hit=False, success=False)
        if result.is_anomaly:
            # 处理异常
    """

    def __init__(
        self,
        window_size: int = _WINDOW_SIZE,
        min_samples_to_fit: int = _MIN_SAMPLES_TO_FIT,
        refit_interval: int = _REFIT_INTERVAL,
        contamination: float = 0.1,
    ) -> None:
        self._window_size = window_size
        self._min_samples = min_samples_to_fit
        self._refit_interval = refit_interval
        self._contamination = contamination

        self._samples: deque[list[float]] = deque(maxlen=window_size)
        self._model: Any = None
        self._samples_since_fit = 0
        self._anomaly_count = 0
        self._total_count = 0

    def add_sample(
        self,
        processor_type: str,
        latency_ms: float,
        sla_hit: bool,
        success: bool,
    ) -> None:
        """添加训练样本到滑动窗口。"""
        features = self._extract_features(processor_type, latency_ms, sla_hit, success)
        self._samples.append(features)
        self._samples_since_fit += 1

        # 定期重新拟合
        if (
            len(self._samples) >= self._min_samples
            and self._samples_since_fit >= self._refit_interval
        ):
            self._fit()

    def predict(
        self,
        processor_type: str,
        latency_ms: float,
        sla_hit: bool,
        success: bool,
    ) -> AnomalyResult:
        """预测给定特征是否为异常。

        Returns:
            ``AnomalyResult``，``is_anomaly=True`` 表示异常。
        """
        self._total_count += 1

        if self._model is None:
            # 模型未就绪，无法检测
            return AnomalyResult(
                is_anomaly=False,
                anomaly_score=0.0,
                reason="model_not_ready",
            )

        features = self._extract_features(processor_type, latency_ms, sla_hit, success)

        try:
            import numpy as np

            X = np.array([features], dtype=np.float64)
            prediction = int(self._model.predict(X)[0])
            score = float(self._model.decision_function(X)[0])

            is_anomaly = prediction == -1
            if is_anomaly:
                self._anomaly_count += 1

            return AnomalyResult(
                is_anomaly=is_anomaly,
                anomaly_score=score,
                feature_vector=features,
                reason="isolation_forest" if is_anomaly else "normal",
            )

        except RECOVERABLE_ERRORS:
            logger.debug("AnomalyDetector.predict failed", exc_info=True)
            return AnomalyResult(
                is_anomaly=False,
                anomaly_score=0.0,
                feature_vector=features,
                reason="prediction_error",
            )

    def _extract_features(
        self,
        processor_type: str,
        latency_ms: float,
        sla_hit: bool,
        success: bool,
    ) -> list[float]:
        """提取特征向量。

        特征：
        1. processor_type_idx: 0=reflex, 1=subconscious, 2=conscious
        2. latency_ms_normalized: log(1 + latency_ms) / 10.0
        3. sla_hit: 0.0 or 1.0
        4. success: 0.0 or 1.0
        5. hour_normalized: current_hour / 23.0
        """
        import math

        pt_idx = float(_PROCESSOR_MAP.get(processor_type, 2))
        latency_norm = math.log1p(max(latency_ms, 0.0)) / 10.0
        sla = 1.0 if sla_hit else 0.0
        succ = 1.0 if success else 0.0
        hour = time.localtime().tm_hour / 23.0

        return [pt_idx, latency_norm, sla, succ, hour]

    def _fit(self) -> None:
        """用滑动窗口数据拟合 IsolationForest。"""
        if len(self._samples) < self._min_samples:
            return

        try:
            import numpy as np
            from sklearn.ensemble import IsolationForest

            X = np.array(list(self._samples), dtype=np.float64)

            self._model = IsolationForest(
                contamination=self._contamination,
                random_state=42,
                n_estimators=50,  # 小树数量，保持推理快
            )
            self._model.fit(X)
            self._samples_since_fit = 0
            logger.debug("AnomalyDetector fitted with %d samples", len(self._samples))

        except RECOVERABLE_ERRORS:
            logger.debug("AnomalyDetector._fit failed", exc_info=True)

    def get_stats(self) -> dict[str, Any]:
        """获取统计。"""
        return {
            "total_samples": len(self._samples),
            "total_predictions": self._total_count,
            "anomalies_detected": self._anomaly_count,
            "anomaly_rate": self._anomaly_count / max(self._total_count, 1),
            "model_ready": self._model is not None,
            "samples_since_fit": self._samples_since_fit,
        }


_detector: AnomalyDetector | None = None


def get_anomaly_detector() -> AnomalyDetector:
    """获取全局 ``AnomalyDetector`` 单例。"""
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
    return _detector


def reset_anomaly_detector() -> None:
    """重置单例（测试用）。"""
    global _detector
    _detector = None
