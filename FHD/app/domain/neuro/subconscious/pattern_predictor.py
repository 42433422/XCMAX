"""模式预测器（PatternPredictor）——基于 N-gram + Markov 链的序列预测。

预测目标：
1. **下一处理器类型**：给定当前处理器序列，预测下一个最可能走哪级处理器。
2. **下一事件类型**：给定当前事件序列，预测下一个最可能的事件类型。

实现策略：
- **N-gram 模型**：跟踪长度为 N 的事件/处理器序列，统计下一项的频率分布。
- **Markov 链**：一阶马尔可夫转移概率矩阵 ``P(next | current)``。
- 推理 < 0.1ms（纯字典查找 + 简单算术）。
- 在线增量学习：每观测到一个新序列就更新统计。

Phase 3 用途：为 SubconsciousProcessor 提供预测能力，支持预调度和资源预热。
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_N = 3  # N-gram 阶数
_DEFAULT_HISTORY = 50  # 历史窗口大小


@dataclass
class PredictionResult:
    """预测结果。"""

    predicted: str = ""
    confidence: float = 0.0
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""


class PatternPredictor:
    """N-gram + Markov 模式预测器。

    Args:
        n: N-gram 阶数（默认 3）。
        history_size: 历史窗口大小（默认 50）。
    """

    def __init__(
        self,
        n: int = _DEFAULT_N,
        history_size: int = _DEFAULT_HISTORY,
    ) -> None:
        self._n = max(n, 2)
        self._history_size = max(history_size, self._n)

        # N-gram 统计：{ (s1, s2, ..., s_{n-1}): {next: count} }
        self._ngrams: dict[tuple[str, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Markov 一阶转移：{ current: {next: count} }
        self._markov: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # 历史序列
        self._history: deque[str] = deque(maxlen=history_size)

        # 统计
        self._total_observations = 0

    def observe(self, item: str) -> None:
        """观测到一个新项，更新 N-gram 和 Markov 统计。

        Args:
            item: 观测到的项（处理器类型 / 事件类型 / 任意字符串）。
        """
        if not item:
            return

        self._total_observations += 1

        # 更新 Markov（一阶）
        if len(self._history) >= 1:
            prev = self._history[-1]
            self._markov[prev][item] += 1

        # 更新 N-gram（n-1 阶上下文 → 当前项）
        if len(self._history) >= self._n - 1:
            context = tuple(list(self._history)[-(self._n - 1) :])
            self._ngrams[context][item] += 1

        # 追加到历史
        self._history.append(item)

    def predict(self, context: list[str] | None = None) -> PredictionResult:
        """预测下一项。

        Args:
            context: 可选的上下文序列。``None`` 时使用内部历史。

        Returns:
            ``PredictionResult``，包含预测项、置信度和备选项。
        """
        if self._total_observations == 0:
            return PredictionResult(reason="no_observations")

        # 使用提供的上下文或内部历史
        if context is not None:
            ctx_list = list(context)
        else:
            ctx_list = list(self._history)

        if not ctx_list:
            return PredictionResult(reason="empty_context")

        # 1. 尝试 N-gram 预测（高阶优先）
        ngram_result = self._predict_ngram(ctx_list)
        if ngram_result.predicted:
            return ngram_result

        # 2. 回退到 Markov 一阶预测
        markov_result = self._predict_markov(ctx_list[-1])
        if markov_result.predicted:
            return markov_result

        return PredictionResult(reason="no_pattern_matched")

    def _predict_ngram(self, ctx_list: list[str]) -> PredictionResult:
        """N-gram 预测。"""
        # 从高阶到低阶尝试
        for order in range(min(self._n - 1, len(ctx_list)), 0, -1):
            context = tuple(ctx_list[-order:])
            counts = self._ngrams.get(context)

            if counts and sum(counts.values()) > 0:
                total = sum(counts.values())
                # 按频率排序
                sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
                predicted, count = sorted_items[0]
                confidence = count / total

                alternatives = [(item, c / total) for item, c in sorted_items[:3]]

                return PredictionResult(
                    predicted=predicted,
                    confidence=confidence,
                    alternatives=alternatives,
                    reason=f"ngram_order_{order}",
                )

        return PredictionResult(reason="ngram_no_match")

    def _predict_markov(self, current: str) -> PredictionResult:
        """Markov 一阶预测。"""
        counts = self._markov.get(current)
        if not counts or sum(counts.values()) == 0:
            return PredictionResult(reason="markov_no_match")

        total = sum(counts.values())
        sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        predicted, count = sorted_items[0]
        confidence = count / total

        alternatives = [(item, c / total) for item, c in sorted_items[:3]]

        return PredictionResult(
            predicted=predicted,
            confidence=confidence,
            alternatives=alternatives,
            reason="markov_order_1",
        )

    def get_transition_matrix(self) -> dict[str, dict[str, float]]:
        """获取 Markov 转移概率矩阵（用于调试/可视化）。"""
        matrix: dict[str, dict[str, float]] = {}
        for current, counts in self._markov.items():
            total = sum(counts.values())
            if total > 0:
                matrix[current] = {nxt: cnt / total for nxt, cnt in counts.items()}
        return matrix

    def get_stats(self) -> dict[str, Any]:
        """获取统计。"""
        return {
            "total_observations": self._total_observations,
            "ngram_order": self._n,
            "ngram_patterns": len(self._ngrams),
            "markov_states": len(self._markov),
            "history_size": len(self._history),
        }


_predictor: PatternPredictor | None = None


def get_pattern_predictor() -> PatternPredictor:
    """获取全局 ``PatternPredictor`` 单例。"""
    global _predictor
    if _predictor is None:
        _predictor = PatternPredictor()
    return _predictor


def reset_pattern_predictor() -> None:
    """重置单例（测试用）。"""
    global _predictor
    _predictor = None
