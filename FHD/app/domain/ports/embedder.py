"""文本嵌入端口（EmbedderPort）与无依赖哈希实现（HashEmbedder）。

端口归 domain 层所有（DDD：抽象属于使用它们的领域）；
``app.application.ports.embedder`` 保留向后兼容 re-export。
HashEmbedder 不依赖任何外部服务，可同时供 domain（LocalEmbedder）
与 application（Excel/UserMemory 向量化）使用。
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod


class EmbedderPort(ABC):
    """文本嵌入模型端口。"""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量。"""
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """生成查询向量。"""
        raise NotImplementedError


class HashEmbedder(EmbedderPort):
    """无需外部依赖的轻量哈希嵌入。"""

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = max(64, dimensions)

    def _tokenize(self, text: str) -> list[str]:
        raw = str(text or "").strip().lower()
        if not raw:
            return []

        tokens: list[str] = []
        ascii_tokens = re.findall(r"[a-z0-9]+", raw)
        tokens.extend(ascii_tokens)

        cjk_chars = re.findall(r"[一-鿿]", raw)
        tokens.extend(cjk_chars)
        if len(cjk_chars) >= 2:
            tokens.extend("".join(cjk_chars[i : i + 2]) for i in range(0, len(cjk_chars) - 1))
        return tokens

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dimensions
        tokens = self._tokenize(text)
        if not tokens:
            return vec

        for token in tokens:
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % self._dimensions
            sign = 1.0 if int(digest[-1], 16) % 2 == 0 else -1.0
            vec[idx] += sign

        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


__all__ = [
    "EmbedderPort",
    "HashEmbedder",
]
