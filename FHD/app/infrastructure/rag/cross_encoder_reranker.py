"""Cross-encoder reranker：基于 sentence-transformers 的 ``CrossEncoder`` 做神经重排。

设计要点：
- 默认 ``disabled``，向后兼容（``is_available`` 返回 False，``rerank`` 回退到原顺序截断）。
- 单例 + lazy load：模型在首次 ``rerank`` 调用时才加载。
- 通过环境变量 ``FHD_RERANKER_MODE`` 切换 ``local`` / ``disabled``。

环境变量：
  FHD_RERANKER_MODE         local | disabled（默认 disabled）
  FHD_RERANKER_LOCAL_MODEL  CrossEncoder 模型名（默认 cross-encoder/ms-marco-MiniLM-L-6-v2，
                             中文可用 BAAI/bge-reranker-base）
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Literal

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .hybrid_retriever import RetrievedChunk

logger = logging.getLogger(__name__)

RerankerMode = Literal["local", "disabled"]

_DEFAULT_LOCAL_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _resolve_mode() -> RerankerMode:
    """从环境变量解析 reranker 模式；未配置或非法值统一回退到 disabled。"""
    raw = (os.environ.get("FHD_RERANKER_MODE", "") or "").strip().lower()
    if raw in ("local", "cross-encoder", "st"):
        return "local"
    return "disabled"


class CrossEncoderReranker:
    """Cross-encoder 神经重排器（基于 sentence-transformers ``CrossEncoder``）。

    单例模式：通过 ``get_singleton()`` 获取；测试用 ``reset_singleton_for_tests()`` 清理。
    """

    _singleton_lock = threading.Lock()
    _singleton: CrossEncoderReranker | None = None

    def __init__(self, mode: RerankerMode | None = None) -> None:
        self._mode: RerankerMode = mode if mode is not None else _resolve_mode()
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._load_attempted: bool = False

    # ---------------- 单例 ----------------
    @classmethod
    def get_singleton(cls) -> CrossEncoderReranker:
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = cls()
            return cls._singleton

    @classmethod
    def reset_singleton_for_tests(cls) -> None:
        with cls._singleton_lock:
            cls._singleton = None

    # ---------------- 公共 API ----------------
    def is_available(self) -> bool:
        """是否启用真实 reranker。disabled 时返回 False。"""
        return self._mode != "disabled"

    @property
    def mode(self) -> RerankerMode:
        return self._mode

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """对 ``chunks`` 用 cross-encoder 重新打分排序，返回前 ``top_k`` 条。

        降级策略：
        - ``disabled`` 或模型不可用：保持原顺序，截断到 ``top_k``（不调 lexical overlap；
          调用方负责在 disabled 时回退到自己的启发式）。
        - 模型加载或推理失败：同样回退到原顺序截断。
        """
        if not chunks:
            return []
        if self._mode == "disabled":
            return chunks[:top_k]
        model = self._get_model()
        if model is None:
            return chunks[:top_k]
        try:
            pairs = [[query, c.text] for c in chunks]
            scores = model.predict(pairs)
            scored = list(zip(chunks, scores))
            scored.sort(key=lambda kv: float(kv[1]), reverse=True)
            top = scored[:top_k]
            return [
                RetrievedChunk(
                    text=c.text,
                    score=float(s),
                    source=(f"{c.source}+rerank" if "rerank" not in c.source else c.source),
                    chunk_index=c.chunk_index,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    metadata=c.metadata,
                    source_url=c.source_url,
                    page=c.page,
                )
                for c, s in top
            ]
        except RECOVERABLE_ERRORS as e:
            logger.warning("cross-encoder rerank 失败，降级为原顺序: %s", e)
            return chunks[:top_k]

    # ---------------- local 模式 ----------------
    def _get_model(self) -> Any | None:
        """lazy load CrossEncoder；失败后不再重试。"""
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_attempted:
                return None
            self._load_attempted = True
            model_name = (
                os.environ.get("FHD_RERANKER_LOCAL_MODEL") or _DEFAULT_LOCAL_MODEL
            ).strip()
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(model_name)
                logger.info("CrossEncoderReranker 模型加载完成: %s", model_name)
                return self._model
            except RECOVERABLE_ERRORS as e:
                logger.warning("CrossEncoder 不可用，reranker 降级为原顺序: %s", e)
                return None


def get_default_reranker() -> CrossEncoderReranker | None:
    """获取默认 reranker 单例；disabled 模式返回 None（保持向后兼容）。"""
    svc = CrossEncoderReranker.get_singleton()
    return svc if svc.is_available() else None


__all__ = [
    "CrossEncoderReranker",
    "RerankerMode",
    "get_default_reranker",
]
