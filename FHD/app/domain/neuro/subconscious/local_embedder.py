"""本地嵌入器（LocalEmbedder）——基于 HashEmbedder + LRU 缓存的轻量嵌入。

设计约束：
- 无外部依赖（不使用 sentence-transformers / torch）。
- SLA < 1ms（HashEmbedder 本身 < 0.1ms，加缓存后更快）。
- 向量维度 256（与 HashEmbedder 默认一致，够用于余弦相似度）。
- LRU 缓存避免重复嵌入相同文本。

Phase 3 用途：为 AnomalyDetector 和 PatternPredictor 提供文本向量化能力。
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from app.application.ports.embedder import EmbedderPort
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_DIM = 256
_DEFAULT_CACHE_SIZE = 512


class LocalEmbedder(EmbedderPort):
    """本地嵌入器：HashEmbedder + LRU 缓存。

    Args:
        dim: 嵌入维度（默认 256）。
        cache_size: LRU 缓存大小（默认 512）。
    """

    def __init__(
        self,
        dim: int = _DEFAULT_DIM,
        cache_size: int = _DEFAULT_CACHE_SIZE,
    ) -> None:
        self._dim = max(dim, 64)
        self._cache_size = max(cache_size, 1)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._inner: Any = None
        self._init_inner()

    def _init_inner(self) -> None:
        """延迟初始化 HashEmbedder（避免循环导入）。"""
        try:
            from app.application.excel_vector_app_service import HashEmbedder

            self._inner = HashEmbedder(dimensions=self._dim)
        except RECOVERABLE_ERRORS:
            logger.debug("HashEmbedder init failed, using fallback", exc_info=True)
            self._inner = None

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量（带 LRU 缓存）。"""
        results: list[list[float]] = []
        for text in texts:
            results.append(self.embed_query(text))
        return results

    def embed_query(self, text: str) -> list[float]:
        """生成查询向量（带 LRU 缓存）。"""
        if text is None:
            text = ""
        cache_key = text[:500]  # 截断避免超长 key

        # 缓存命中
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # 缓存未命中
        vec = self._compute(text)

        # 写入缓存
        self._cache[cache_key] = vec
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)  # 移除最旧的

        return vec

    def _compute(self, text: str) -> list[float]:
        """实际计算嵌入向量。"""
        if self._inner is not None:
            try:
                return list(self._inner.embed_query(text or ""))
            except RECOVERABLE_ERRORS:
                logger.debug("HashEmbedder.embed_query failed", exc_info=True)

        # Fallback: 零向量
        return [0.0] * self._dim

    @property
    def dim(self) -> int:
        """嵌入维度。"""
        return self._dim

    @property
    def cache_size(self) -> int:
        """当前缓存条目数。"""
        return len(self._cache)

    def clear_cache(self) -> None:
        """清空缓存。"""
        self._cache.clear()


_embedder: LocalEmbedder | None = None


def get_local_embedder(
    dim: int = _DEFAULT_DIM,
    cache_size: int = _DEFAULT_CACHE_SIZE,
) -> LocalEmbedder:
    """获取全局 ``LocalEmbedder`` 单例。"""
    global _embedder
    if _embedder is None:
        _embedder = LocalEmbedder(dim=dim, cache_size=cache_size)
    return _embedder


def reset_local_embedder() -> None:
    """重置单例（测试用）。"""
    global _embedder
    _embedder = None
