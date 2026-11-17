"""Cross-encoder reranker（成熟组件复用：fastembed / sentence-transformers）。

优先 fastembed（Apache-2.0，ONNX Runtime，无 torch），未安装时退回
sentence-transformers。默认关闭，避免首次查询静默下载大模型；显式设置
``FHD_RERANK_ENABLED=1`` 或 ``FHD_RERANK_MODEL`` 后启用。当 embedding 降级为
hash（无语义向量）时，可显式设置 ``FHD_RERANK_AUTO=1`` 让检索自动精排；模型不可用
时由调用方回退到词法重排，不影响检索主链路。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 多语言精排，int8 量化约 0.57GB；在 50 条中文评测上 recall@1 优于 base。
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3-int8"
RerankerFn = Callable[[str, list[str]], list[float]]

_lock = threading.Lock()
_singleton: CrossEncoderReranker | None = None
_load_attempted = False


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def rerank_enabled() -> bool:
    """显式开关，或直接给了模型名时启用。"""
    return _env_truthy("FHD_RERANK_ENABLED") or bool(
        (os.environ.get("FHD_RERANK_MODEL") or "").strip()
    )


def auto_rerank_allowed() -> bool:
    """hash 降级时是否自动精排；需显式 ``FHD_RERANK_AUTO=1``，避免静默下载模型。"""
    return _env_truthy("FHD_RERANK_AUTO")


class CrossEncoderReranker:
    """懒加载 cross-encoder（fastembed 优先、sentence-transformers 回退）。"""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any | None = None
        self._backend = ""

    def _model_or_none(self) -> Any | None:
        if self._model is not None:
            return self._model
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name=self._model_name)
            self._backend = "fastembed"
            return self._model
        except RECOVERABLE_ERRORS:
            logger.debug("fastembed rerank 不可用，尝试 sentence-transformers")
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name)
            self._backend = "sentence-transformers"
        except RECOVERABLE_ERRORS:
            logger.warning("rerank 模型不可用：%s", self._model_name, exc_info=True)
            return None
        return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        model = self._model_or_none()
        if model is None or not passages:
            return []
        try:
            if self._backend == "fastembed":
                return [float(value) for value in list(model.rerank(query, passages))]
            raw = model.predict([(query, text) for text in passages])
            return [float(value) for value in list(raw)]
        except RECOVERABLE_ERRORS:
            logger.warning("rerank 打分失败，回退词法重排", exc_info=True)
            return []


def get_default_reranker(*, auto: bool = False) -> CrossEncoderReranker | None:
    """返回启用的 reranker 单例；未启用或依赖缺失时返回 None。

    ``auto=True`` 用于 hash 降级时的自动精排：跳过显式开关，但仍要求依赖存在。
    """
    global _singleton, _load_attempted
    if not auto and not rerank_enabled():
        return None
    with _lock:
        if _singleton is not None:
            return _singleton
        if _load_attempted:
            return None
        _load_attempted = True
        model_name = (os.environ.get("FHD_RERANK_MODEL") or "").strip() or DEFAULT_RERANK_MODEL
        try:
            import fastembed  # noqa: F401
        except RECOVERABLE_ERRORS:
            try:
                import sentence_transformers  # noqa: F401
            except RECOVERABLE_ERRORS:
                logger.warning("无可用 rerank 依赖，回退词法重排")
                return None
        _singleton = CrossEncoderReranker(model_name)
        return _singleton


def reset_reranker_for_tests() -> None:
    global _singleton, _load_attempted
    with _lock:
        _singleton = None
        _load_attempted = False
