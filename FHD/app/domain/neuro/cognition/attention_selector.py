"""注意力选择器（AttentionSelector）——从工作记忆中选取与当前查询最相关的上下文。

灵感来源：认知科学的"注意力聚焦"——System 2 慎思时，工作记忆容量有限（Miller's 7±2），
需要从大量记忆条目中选取最相关的少数几条注入 LLM 上下文。

实现策略（保持 <5ms，不引入重 ML）：
1. **关键词重叠**：对查询分词后，计算与每条记忆的内容重叠度（Jaccard 系数）。
2. **位置衰减**：越近期的会话消息权重越高（指数衰减）。
3. **来源加权**：长期记忆（向量召回）已有相关性分数，直接复用。
4. **token 预算**：选取的条目总 token 数不超过预算（默认 1500，约 750 汉字）。

Phase 2 用途：为 ``ConsciousLLMHandler`` 构建精简的 LLM 上下文，避免 prompt 过长。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.domain.neuro.cognition.working_memory import MemoryItem, WorkingMemorySnapshot

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_BUDGET = 1500
_DEFAULT_MAX_ITEMS = 6
_RECENCY_DECAY = 0.85  # 每往前一条，权重 *0.85


@dataclass
class AttentionResult:
    """注意力选择结果。"""

    selected: list[MemoryItem] = field(default_factory=list)
    total_candidates: int = 0
    pruned: int = 0
    estimated_tokens: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.selected

    def as_messages(self) -> list[dict[str, str]]:
        """转为 OpenAI 消息格式。"""
        return [{"role": it.role, "content": it.content} for it in self.selected]


def _tokenize(text: str) -> set[str]:
    """简易分词：中文按字、英文按词。"""
    if not text:
        return set()
    # 英文单词
    tokens = {w.lower() for w in re.findall(r"[a-zA-Z]{2,}", text)}
    # 中文字符（单字）
    tokens.update(re.findall(r"[\u4e00-\u9fff]", text))
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1.3 token。"""
    if not text:
        return 0
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_words = len(re.findall(r"[a-zA-Z]+", text))
    return int(cn_chars * 1.5 + en_words * 1.3)


class AttentionSelector:
    """注意力选择器：从工作记忆快照中选取最相关条目。

    Args:
        token_budget: 选取条目的总 token 预算（默认 1500）。
        max_items: 最大选取条目数（默认 6）。
    """

    def __init__(
        self,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        max_items: int = _DEFAULT_MAX_ITEMS,
    ) -> None:
        self._token_budget = token_budget
        self._max_items = max_items

    def select(
        self,
        query: str,
        snapshot: WorkingMemorySnapshot,
    ) -> AttentionResult:
        """从 ``snapshot`` 中选取与 ``query`` 最相关的记忆条目。

        Args:
            query: 当前查询文本。
            snapshot: 工作记忆快照（``WorkingMemory.recall()`` 的结果）。

        Returns:
            ``AttentionResult``，包含选取的条目和统计信息。
        """
        candidates = snapshot.items
        total = len(candidates)

        if total == 0:
            return AttentionResult()

        query_tokens = _tokenize(query)
        n = len(candidates)

        scored: list[tuple[float, int, MemoryItem]] = []
        for idx, item in enumerate(candidates):
            # 相关性：关键词重叠
            relevance = _jaccard(query_tokens, _tokenize(item.content))

            # 长期记忆已有分数，加权
            if item.source == "long_term" and item.score > 0:
                relevance = 0.5 * relevance + 0.5 * item.score

            # 位置衰减：越近期（idx 越大）权重越高
            # 倒数第 1 条 decay=1.0，倒数第 2 条 decay=0.85，…
            recency = _RECENCY_DECAY ** (n - 1 - idx)

            # 综合分数
            score = relevance * 0.7 + recency * 0.3
            scored.append((score, idx, item))

        # 按分数降序
        scored.sort(key=lambda t: t[0], reverse=True)

        # 按预算选取
        selected: list[MemoryItem] = []
        used_tokens = 0
        for score, _idx, item in scored:
            if len(selected) >= self._max_items:
                break
            item_tokens = _estimate_tokens(item.content)
            if used_tokens + item_tokens > self._token_budget:
                continue
            # 填充分数
            item.score = score
            selected.append(item)
            used_tokens += item_tokens

        # 按原始顺序排列（保持对话时序）
        selected.sort(key=lambda it: candidates.index(it))

        return AttentionResult(
            selected=selected,
            total_candidates=total,
            pruned=total - len(selected),
            estimated_tokens=used_tokens,
        )


_selector: AttentionSelector | None = None


def get_attention_selector() -> AttentionSelector:
    """获取全局 ``AttentionSelector`` 单例。"""
    global _selector
    if _selector is None:
        _selector = AttentionSelector()
    return _selector


def reset_attention_selector() -> None:
    """重置单例（测试用）。"""
    global _selector
    _selector = None
