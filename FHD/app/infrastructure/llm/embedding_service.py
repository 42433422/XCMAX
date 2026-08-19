"""真实 embedding 服务：支持本地 sentence-transformers 与远端 OpenAI 兼容 API。

设计要点：
- 默认 ``disabled``，向后兼容（``is_available`` 返回 False，``embed`` 返回空列表）。
- 单例 + lazy load：模型在首次 ``embed`` 调用时才加载，避免启动慢。
- 通过环境变量 ``FHD_EMBEDDING_MODE`` 切换 ``local`` / ``remote`` / ``disabled``。
- 同时实现 ``EmbedderPort`` 协议（``embed_texts`` / ``embed_query``），可作为 Excel/
  UserMemory 等向量服务的 embedder 直接注入。

环境变量：
  FHD_EMBEDDING_MODE             local | remote | disabled（默认 disabled）
  FHD_EMBEDDING_LOCAL_MODEL      本地模型名（默认 sentence-transformers/all-MiniLM-L6-v2，
                                  中文可用 BAAI/bge-small-zh-v1.5）
  FHD_EMBEDDING_REMOTE_URL       远端 /v1/embeddings 端点
  FHD_EMBEDDING_REMOTE_API_KEY   Bearer token（可选）
  FHD_EMBEDDING_REMOTE_MODEL     远端模型名
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Literal

from app.application.ports.embedder import EmbedderPort
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

EmbeddingMode = Literal["local", "remote", "hash", "disabled"]

_DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_HASH_EMBED_DIM = 64


def _resolve_mode() -> EmbeddingMode:
    """从环境变量解析 embedding 模式；未配置或非法值统一回退到 disabled。"""
    raw = (os.environ.get("FHD_EMBEDDING_MODE", "") or "").strip().lower()
    if raw in ("local", "sentence-transformers", "st"):
        return "local"
    if raw in ("remote", "api", "openai"):
        return "remote"
    if raw in ("hash", "local-hash", "deterministic"):
        return "hash"
    if raw in ("disabled", "off", "none"):
        return "disabled"
    # Unset: hash fallback for web omniscient; desktop stays disabled unless RAG on.
    rag = (os.environ.get("XCAGI_RAG_ENABLED", "") or "").strip().lower()
    if rag in {"0", "false", "no", "off"}:
        return "disabled"
    if rag in {"1", "true", "yes", "on", "auto"}:
        return "hash"
    try:
        from app.utils.deployment import is_desktop_mode

        if is_desktop_mode():
            return "disabled"
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - env bootstrap must not fail import
        pass
    return "hash"


class EmbeddingService(EmbedderPort):
    """双模式 embedding 服务（local: sentence-transformers / remote: OpenAI 兼容）。

    单例模式：通过 ``get_singleton()`` 获取，避免重复加载模型；测试用
    ``reset_singleton_for_tests()`` 清理。
    """

    _singleton_lock = threading.Lock()
    _singleton: EmbeddingService | None = None

    def __init__(self, mode: EmbeddingMode | None = None) -> None:
        # 不在 __init__ 加载模型；lazy load 在首次 embed 时触发。
        self._mode: EmbeddingMode = mode if mode is not None else _resolve_mode()
        self._model: Any | None = None  # SentenceTransformer 实例
        self._dim_cache: int | None = None
        self._load_lock = threading.Lock()
        self._load_attempted: bool = False  # 标记是否已尝试加载，避免重复尝试

    # ---------------- 单例 ----------------
    @classmethod
    def get_singleton(cls) -> EmbeddingService:
        """返回进程级单例（不区分 mode；mode 在 __init__ 时已固化）。"""
        with cls._singleton_lock:
            if cls._singleton is None:
                cls._singleton = cls()
            return cls._singleton

    @classmethod
    def reset_singleton_for_tests(cls) -> None:
        """测试专用：清理单例缓存，让下一个用例重新读取环境变量。"""
        with cls._singleton_lock:
            cls._singleton = None

    # ---------------- 公共 API ----------------
    def is_available(self) -> bool:
        """是否启用 embedding（含本地 hash 降级）。disabled 时返回 False。"""
        return self._mode != "disabled"

    @property
    def mode(self) -> EmbeddingMode:
        return self._mode

    def dim(self) -> int:
        """返回 embedding 维度。

        - disabled：返回 0
        - local/remote：通过一次探测性 embed 获取长度并缓存
        """
        if self._mode == "disabled":
            return 0
        if self._mode == "hash":
            self._dim_cache = _HASH_EMBED_DIM
            return _HASH_EMBED_DIM
        if self._dim_cache is not None:
            return self._dim_cache
        try:
            sample = self.embed_one("dimension_probe")
            if sample:
                self._dim_cache = len(sample)
                return self._dim_cache
        except RECOVERABLE_ERRORS as e:
            logger.warning("embedding dim 探测失败: %s", e)
        return 0

    def embed_one(self, text: str) -> list[float]:
        """单条文本嵌入；不可用时返回空列表（由调用方决定降级策略）。"""
        results = self.embed([text])
        if not results:
            return []
        return results[0]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入；不可用或空输入返回空列表。"""
        if self._mode == "disabled":
            return []
        if not texts:
            return []
        if self._mode == "local":
            return self._embed_local(texts)
        if self._mode == "remote":
            return self._embed_remote(texts)
        if self._mode == "hash":
            return [self._embed_hash(text) for text in texts]
        return []

    def _embed_hash(self, text: str) -> list[float]:
        """Deterministic bag-of-hashes embedder for local omniscient keyword+vector hybrid."""
        import hashlib
        import math
        import re

        vec = [0.0] * _HASH_EMBED_DIM
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", str(text or "").lower())
        if not tokens:
            tokens = ["_empty_"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in range(0, min(16, len(digest)), 2):
                idx = int.from_bytes(digest[offset : offset + 2], "big") % _HASH_EMBED_DIM
                sign = 1.0 if digest[(offset + 2) % len(digest)] % 2 == 0 else -1.0
                vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out = [v / norm for v in vec]
        if self._dim_cache is None:
            self._dim_cache = _HASH_EMBED_DIM
        return out

    # EmbedderPort 协议适配：供 ExcelVector/UserMemory 等使用 EmbedderPort 的服务注入
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_one(text)

    # ---------------- local 模式 ----------------
    def _embed_local(self, texts: list[str]) -> list[list[float]]:
        model = self._get_local_model()
        if model is None:
            return []
        try:
            vecs = model.encode(texts)  # numpy.ndarray 或 list
            result: list[list[float]] = []
            for row in vecs:
                result.append([float(x) for x in list(row)])
            if result and self._dim_cache is None:
                self._dim_cache = len(result[0])
            return result
        except RECOVERABLE_ERRORS as e:
            logger.warning("本地 embedding encode 失败: %s", e)
            return []

    def _get_local_model(self) -> Any | None:
        """lazy load SentenceTransformer；失败后不再重试。"""
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_attempted:
                return None
            self._load_attempted = True
            model_name = (
                os.environ.get("FHD_EMBEDDING_LOCAL_MODEL") or _DEFAULT_LOCAL_MODEL
            ).strip()
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
                logger.info("EmbeddingService local 模型加载完成: %s", model_name)
                return self._model
            except RECOVERABLE_ERRORS as e:
                logger.warning("sentence-transformers 不可用，embedding 降级为空: %s", e)
                return None

    # ---------------- remote 模式 ----------------
    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        url = (os.environ.get("FHD_EMBEDDING_REMOTE_URL") or "").strip()
        api_key = (os.environ.get("FHD_EMBEDDING_REMOTE_API_KEY") or "").strip()
        model = (os.environ.get("FHD_EMBEDDING_REMOTE_MODEL") or "").strip()
        if not url:
            logger.warning("FHD_EMBEDDING_REMOTE_URL 未配置，跳过远端 embedding")
            return []
        try:
            import requests

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            payload: dict[str, Any] = {"input": texts}
            if model:
                payload["model"] = model
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            # OpenAI 兼容格式：{"data": [{"embedding": [...], "index": 0}, ...]}
            items = data.get("data") or []
            items_sorted = sorted(items, key=lambda x: x.get("index", 0))
            result = [list(item["embedding"]) for item in items_sorted]
            if result and self._dim_cache is None:
                self._dim_cache = len(result[0])
            return result
        except RECOVERABLE_ERRORS as e:
            logger.warning("远端 embedding 调用失败: %s", e)
            return []


def get_default_embedding_service() -> EmbeddingService | None:
    """获取默认 EmbeddingService 单例；disabled 模式返回 None（保持向后兼容）。"""
    svc = EmbeddingService.get_singleton()
    return svc if svc.is_available() else None


__all__ = [
    "EmbeddingMode",
    "EmbeddingService",
    "get_default_embedding_service",
]
