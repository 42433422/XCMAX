"""真实 embedding 服务：支持本地 sentence-transformers 与远端 OpenAI 兼容 API。

设计要点：
- 未配置时优先使用已缓存 FastEmbed 模型，失败时固定降级到 hash；显式 disabled 可关闭。
- 单例：auto 模式在首次创建时选择固定向量空间，显式模型模式保持 lazy load。
- 通过环境变量 ``FHD_EMBEDDING_MODE`` 切换 ``local`` / ``remote`` / ``disabled``。
- 同时实现 ``EmbedderPort`` 协议（``embed_texts`` / ``embed_query``），可作为 Excel/
  UserMemory 等向量服务的 embedder 直接注入。

环境变量：
  FHD_EMBEDDING_MODE             auto | fastembed | local | remote | hash | disabled（默认 auto）
  FHD_EMBEDDING_LOCAL_MODEL      本地模型名（默认 sentence-transformers/all-MiniLM-L6-v2，
                                  中文可用 BAAI/bge-small-zh-v1.5）
  FHD_EMBEDDING_REMOTE_URL       远端 /v1/embeddings 端点
  FHD_EMBEDDING_REMOTE_API_KEY   Bearer token（可选）
  FHD_EMBEDDING_REMOTE_MODEL     远端模型名
  FHD_EMBEDDING_MODEL_REVISION   模型版本标识；同名模型更新权重时改变此值以重建索引
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Literal

from app.domain.ports.embedder import EmbedderPort
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

EmbeddingMode = Literal["local", "remote", "fastembed", "hash", "disabled"]

_DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# fastembed（Apache-2.0，ONNX Runtime，不依赖 torch）：中文默认 bge-small-zh
_DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-zh-v1.5"
_HASH_EMBED_DIM = 192
_CACHED_MODEL_LOAD_ERRORS = RECOVERABLE_ERRORS + (RuntimeError,)


def _resolve_mode() -> EmbeddingMode | Literal["auto"]:
    """未配置时优先 auto，保留显式关闭和非法配置的兼容行为。"""
    raw = (os.environ.get("FHD_EMBEDDING_MODE", "") or "").strip().lower()
    if raw in ("local", "sentence-transformers", "st"):
        return "local"
    if raw in ("fastembed", "onnx"):
        return "fastembed"
    if raw in ("remote", "api", "openai"):
        return "remote"
    if raw in ("hash", "local-hash", "deterministic"):
        return "hash"
    if raw in ("disabled", "off", "none"):
        return "disabled"
    # Unset mode: honor explicit RAG off, otherwise prefer cached semantic vectors.
    rag = (os.environ.get("XCAGI_RAG_ENABLED", "") or "").strip().lower()
    if rag in {"0", "false", "no", "off"}:
        return "disabled"
    return "auto" if raw in {"", "auto"} else "hash"


def _fastembed_cache_dir() -> Path | None:
    explicit = (os.environ.get("FHD_EMBEDDING_FASTEMBED_CACHE_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    for relative in ("resources/models/fastembed", "assets/models/fastembed", "models/fastembed"):
        candidate = root / relative
        if candidate.is_dir():
            return candidate
    return None


def _fastembed_artifact_revision(model_name: str) -> str:
    cache = _fastembed_cache_dir()
    if cache is None:
        return ""
    try:
        manifest = json.loads((cache / "xcmax-model.json").read_text(encoding="utf-8"))
        digest = manifest.get("sha256")
        if manifest.get("model") == model_name and isinstance(digest, str) and len(digest) == 64:
            return digest
    except RECOVERABLE_ERRORS:
        pass
    return ""


def _load_cached_fastembed(model_name: str) -> tuple[Any | None, int]:
    """Select a locally provisioned semantic model before publishing its fingerprint.

    Never download weights in a request or fall back to a different vector space
    after the service has published its identity. Restart to re-probe availability.
    """
    try:
        from fastembed import TextEmbedding

        cache = _fastembed_cache_dir()
        model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache) if cache is not None else None,
            local_files_only=True,
        )
        vectors = list(model.embed(["dimension_probe"]))
        if len(vectors) == 1 and len(vectors[0]) > 0:
            return model, len(vectors[0])
    except _CACHED_MODEL_LOAD_ERRORS as exc:
        logger.info("Cached FastEmbed unavailable; using hash: %s", type(exc).__name__)
    return None, 0


class EmbeddingService(EmbedderPort):
    """双模式 embedding 服务（local: sentence-transformers / remote: OpenAI 兼容）。

    单例模式：通过 ``get_singleton()`` 获取，避免重复加载模型；测试用
    ``reset_singleton_for_tests()`` 清理。
    """

    _singleton_lock = threading.Lock()
    _singleton: EmbeddingService | None = None

    def __init__(self, mode: EmbeddingMode | None = None) -> None:
        configured = mode if mode is not None else _resolve_mode()
        cached_model: Any | None = None
        cached_dim = 0
        if configured == "auto":
            cached_model, cached_dim = _load_cached_fastembed(
                os.environ.get("FHD_EMBEDDING_FASTEMBED_MODEL") or _DEFAULT_FASTEMBED_MODEL
            )
            self._mode: EmbeddingMode = "fastembed" if cached_model is not None else "hash"
        else:
            self._mode = configured
        self._model_name = {
            "local": os.environ.get("FHD_EMBEDDING_LOCAL_MODEL") or _DEFAULT_LOCAL_MODEL,
            "fastembed": os.environ.get("FHD_EMBEDDING_FASTEMBED_MODEL")
            or _DEFAULT_FASTEMBED_MODEL,
            "remote": os.environ.get("FHD_EMBEDDING_REMOTE_MODEL") or "",
            "hash": f"sha256-bigram-v1-{_HASH_EMBED_DIM}",
        }.get(self._mode, "").strip()
        self._remote_url = (os.environ.get("FHD_EMBEDDING_REMOTE_URL") or "").strip()
        identity = {
            "schema": 1,
            "mode": self._mode,
            "model": self._model_name,
            "endpoint": self._remote_url if self._mode == "remote" else "",
            "revision": (os.environ.get("FHD_EMBEDDING_MODEL_REVISION") or "").strip(),
        }
        if self._mode == "fastembed":
            identity["artifact_revision"] = _fastembed_artifact_revision(self._model_name)
        self._embedding_fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self._model: Any | None = None  # SentenceTransformer 实例
        self._fastembed_model: Any | None = cached_model  # fastembed.TextEmbedding 实例
        self._dim_cache: int | None = cached_dim or None
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

    @property
    def embedding_fingerprint(self) -> str:
        """Stable identity of the configured vector space; excludes credentials.

        Model configuration is fixed with the service instance, matching the
        lazy-loaded model. Restart after changing model settings or revision.
        """
        return self._embedding_fingerprint

    def is_semantic(self) -> bool:
        """是否使用真实语义向量；hash 只是确定性降级，不算语义检索。"""
        return self._mode in ("local", "remote", "fastembed")

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
        if self._mode == "fastembed":
            return self._embed_fastembed(texts)
        if self._mode == "remote":
            return self._embed_remote(texts)
        if self._mode == "hash":
            return [self._embed_hash(text) for text in texts]
        return []

    def _embed_hash(self, text: str) -> list[float]:
        """Deterministic hashed bigram embedder（无语义模型时的降级方案）。

        中文按二元组、英文数字按词做带符号哈希；192 维在 69 条中文评测上
        比旧的整段 token / 64 维方案显著提升（recall@1 0.17 → 0.84）。
        """
        import math
        import re

        vec = [0.0] * _HASH_EMBED_DIM
        tokens: list[str] = []
        for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", str(text or "").lower()):
            if re.match(r"[\u4e00-\u9fff]", part):
                if len(part) == 1:
                    tokens.append(part)
                else:
                    tokens.extend(part[index : index + 2] for index in range(len(part) - 1))
            else:
                tokens.append(part)
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
            model_name = self._model_name
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(model_name)
                logger.info("EmbeddingService local 模型加载完成: %s", model_name)
                return self._model
            except RECOVERABLE_ERRORS as e:
                logger.warning("sentence-transformers 不可用，embedding 降级为空: %s", e)
                return None

    # ---------------- fastembed（ONNX，无 torch） ----------------
    def _embed_fastembed(self, texts: list[str]) -> list[list[float]]:
        model = self._get_fastembed_model()
        if model is None:
            return []
        try:
            vectors = list(model.embed(texts))
            result = [[float(x) for x in list(vector)] for vector in vectors]
            if result and self._dim_cache is None:
                self._dim_cache = len(result[0])
            return result
        except RECOVERABLE_ERRORS as e:
            logger.warning("fastembed encode 失败: %s", e)
            return []

    def _get_fastembed_model(self) -> Any | None:
        """lazy load fastembed.TextEmbedding；失败后不再重试。"""
        if self._fastembed_model is not None:
            return self._fastembed_model
        with self._load_lock:
            if self._fastembed_model is not None:
                return self._fastembed_model
            if self._load_attempted:
                return None
            self._load_attempted = True
            model_name = self._model_name
            try:
                from fastembed import TextEmbedding

                cache = _fastembed_cache_dir()
                self._fastembed_model = TextEmbedding(
                    model_name=model_name, cache_dir=str(cache) if cache is not None else None
                )
                logger.info("EmbeddingService fastembed 模型加载完成: %s", model_name)
                return self._fastembed_model
            except RECOVERABLE_ERRORS as e:
                logger.warning("fastembed 不可用，embedding 降级为空: %s", e)
                return None

    # ---------------- remote 模式 ----------------
    def _embed_remote(self, texts: list[str]) -> list[list[float]]:
        url = self._remote_url
        api_key = (os.environ.get("FHD_EMBEDDING_REMOTE_API_KEY") or "").strip()
        model = self._model_name
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
