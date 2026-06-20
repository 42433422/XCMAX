"""关系深度计算器。"""
from __future__ import annotations

from app.domain.persona.value_objects import RapportScore


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """归一化到 [0, 1]。"""
    if max_val <= min_val:
        return 0.0
    normalized = (value - min_val) / (max_val - min_val)
    if normalized < 0.0:
        return 0.0
    if normalized > 1.0:
        return 1.0
    return normalized


class RapportCalculator:
    """关系深度计算器。

    公式：rapport = 0.7 * interaction + 0.1 * business_depth + 0.2 * emotion

    注：权重经测试校准，确保 500 轮互动 + 50 次情感信号达到忠诚阈值 (>=0.9)。
    """

    INTERACTION_WEIGHT = 0.7
    BUSINESS_DEPTH_WEIGHT = 0.1
    EMOTION_WEIGHT = 0.2

    MAX_INTERACTION_COUNT = 500  # 500 轮 → 1.0
    MAX_BUSINESS_DOMAINS = 5  # 5 个业务域 → 1.0
    MAX_EMOTION_SIGNALS = 50  # 50 次情感信号 → 1.0
    COLD_START_DEFAULT = 0.3

    def calculate(
        self,
        interaction_count: int,
        business_domain_counts: dict[str, int],
        emotion_signal_count: int,
    ) -> RapportScore:
        """计算关系深度。

        Args:
            interaction_count: 累计互动轮数
            business_domain_counts: 各业务域操作计数
            emotion_signal_count: 情感信号次数

        Returns:
            RapportScore: 关系深度值对象
        """
        interaction_normalized = _normalize(
            float(interaction_count), 0.0, float(self.MAX_INTERACTION_COUNT)
        )
        business_depth = _normalize(
            float(len(business_domain_counts)), 0.0, float(self.MAX_BUSINESS_DOMAINS)
        )
        emotion_normalized = _normalize(
            float(emotion_signal_count), 0.0, float(self.MAX_EMOTION_SIGNALS)
        )

        score = (
            self.INTERACTION_WEIGHT * interaction_normalized
            + self.BUSINESS_DEPTH_WEIGHT * business_depth
            + self.EMOTION_WEIGHT * emotion_normalized
        )

        # 冷启动保护：无任何数据时给友好默认值
        if interaction_count == 0 and not business_domain_counts and emotion_signal_count == 0:
            score = self.COLD_START_DEFAULT

        # clamp
        if score < 0.0:
            score = 0.0
        elif score > 1.0:
            score = 1.0

        return RapportScore(
            score=score,
            interaction_count=interaction_count,
            business_depth=business_depth,
            emotion_signal_count=emotion_signal_count,
        )
