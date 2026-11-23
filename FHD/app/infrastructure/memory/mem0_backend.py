"""mem0 OSS 长期记忆后端。

设计原则：
- 可选依赖：未安装 mem0ai / qdrant-client 时静默停用，调用方继续走原有记忆链路。
- 离线可用：嵌入复用本地 ``EmbeddingService``（默认 hash，可切本地模型），不联网、无 torch。
- Mem0 抽取只产生待确认候选；已确认 MemoryV2 记录按来源 ID / revision 投影。
- 记忆带有效区间：``valid_from`` / ``valid_to`` / ``superseded_by``，召回时过滤失效项。
- 数据边界：所有查询强制带 ``user_id`` 过滤，租户/Mod/渠道在应用层再过滤。
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from filelock import FileLock

from app.infrastructure.memory.memory_units import (
    expiration_iso,
    iso_at,
    rank_hits,
)
from app.infrastructure.observability.metrics import observe_memory_recall
from app.utils.deployment import env_float as _env_float
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# mem0 默认开启 PostHog 遥测；离线产品必须先关闭再导入 mem0。
os.environ.setdefault("MEM0_TELEMETRY", "False")

_ENV_BACKEND = "XCAGI_LONG_TERM_MEMORY_BACKEND"
_ENV_MIN_SCORE = "XCAGI_LONG_TERM_MEMORY_MIN_SCORE"
_ENV_MAX_CHARS = "XCAGI_LONG_TERM_MEMORY_PROMPT_CHARS"
_ENV_CONSOLIDATION = "XCAGI_MEMORY_CONSOLIDATION"

_BACKEND_VALUES = {"auto", "mem0", "legacy"}
_DEFAULT_PROMPT_CHARS = 1800
_MAX_MOD_DELETE_PAGES = 1000


class OfflineLLM:
    """占位 LLM：写入使用 infer=False，本类不应被调用。"""

    def __init__(self, config: Any = None) -> None:
        self.config = config

    def generate_response(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("长期记忆未启用在线模型，不执行 LLM 事实抽取。")


class FhdEmbedding:
    """把项目内 EmbeddingService 适配为 mem0 embedder。"""

    def __init__(self, config: Any = None) -> None:
        self.config = config

    def embed(self, text: str, memory_action: str | None = None) -> list[float]:
        from app.infrastructure.llm.embedding_service import get_default_embedding_service

        service = get_default_embedding_service()
        if service is None:
            raise RuntimeError("本地嵌入不可用，长期记忆写入已跳过。")
        vector = service.embed_one(str(text or ""))
        if not vector:
            raise RuntimeError("本地嵌入返回空向量，长期记忆写入已跳过。")
        return vector


def _bypass_validation(model_cls: Any, **fields: Any) -> Any:
    """跳过 mem0 配置类的 provider 白名单校验（我们注册了自定义 provider）。"""
    construct = getattr(model_cls, "model_construct", None) or getattr(model_cls, "construct", None)
    if construct is None:
        raise TypeError(f"{model_cls} 不支持绕过校验构造")
    return construct(**fields)


def _memory_root() -> Path:
    override = str(os.environ.get("XCAGI_LONG_TERM_MEMORY_DIR") or "").strip()
    if override:
        root = Path(override)
    else:
        from app.desktop_runtime.desktop_runtime_paths import get_desktop_data_dir

        root = get_desktop_data_dir() / "long-term-memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _backend_choice() -> str:
    raw = str(os.environ.get(_ENV_BACKEND) or "auto").strip().lower()
    return raw if raw in _BACKEND_VALUES else "auto"


def _consolidation_enabled() -> bool:
    raw = str(os.environ.get(_ENV_CONSOLIDATION) or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _result_id(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    rows = result.get("results")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return str(rows[0].get("id") or "") or None
    return str(result.get("id") or "") or None


class Mem0LongTermMemory:
    """mem0 同步封装；初始化失败即视为停用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._memory: Any | None = None
        self._failed = False
        self._initialized = False
        self._dims = 0
        self._mode = ""
        self._embedding_fingerprint = ""
        self._projection_lock = threading.RLock()
        self._projected_owners: set[str] = set()
        self._projection_retry_after: dict[str, float] = {}
        self._min_score = 0.0

    # ---------------- 生命周期 ----------------
    @property
    def enabled(self) -> bool:
        return self._active() is not None

    def _active(self) -> Any | None:
        """按配置与依赖状态返回可用实例；未启用时返回 None。"""
        choice = _backend_choice()
        if choice == "legacy":
            return None
        if choice == "auto" and not self._importable():
            return None
        return self._ensure()

    @staticmethod
    def _importable() -> bool:
        import importlib.util

        return (
            importlib.util.find_spec("mem0") is not None
            and importlib.util.find_spec("qdrant_client") is not None
        )

    def _ensure(self) -> Any | None:
        if self._initialized:
            return self._memory
        with self._lock:
            if self._initialized:
                return self._memory
            self._initialized = True
            try:
                self._memory = self._build()
            except RECOVERABLE_ERRORS as exc:  # 依赖/配置问题都不应影响主对话
                self._failed = True
                self._memory = None
                logger.warning("长期记忆后端未启用：%s", exc)
            return self._memory

    def _build(self) -> Any:
        from app.infrastructure.llm.embedding_service import EmbeddingService

        embedding = EmbeddingService.get_singleton()
        if not embedding.is_available():
            raise RuntimeError("嵌入服务已关闭")
        dims = int(embedding.dim())
        if dims <= 0:
            raise RuntimeError("嵌入维度为 0")
        self._dims = dims
        self._mode = str(embedding.mode)
        self._embedding_fingerprint = embedding.embedding_fingerprint
        # hash 向量相似度整体偏低，阈值单独放宽；本地模型用更严格阈值过滤噪声。
        default_score = 0.05 if self._mode == "hash" else 0.2
        self._min_score = _env_float(_ENV_MIN_SCORE, default_score)

        os.environ.setdefault("MEM0_TELEMETRY", "False")
        from mem0.configs.base import MemoryConfig
        from mem0.configs.llms.base import BaseLlmConfig as LlmConfigCls
        from mem0.embeddings.configs import EmbedderConfig
        from mem0.llms.configs import LlmConfig
        from mem0.utils.factory import EmbedderFactory, LlmFactory
        from mem0.vector_stores.configs import VectorStoreConfig

        LlmFactory.provider_to_class["fhd_offline"] = (
            "app.infrastructure.memory.mem0_backend.OfflineLLM",
            LlmConfigCls,
        )
        EmbedderFactory.provider_to_class["fhd"] = (
            "app.infrastructure.memory.mem0_backend.FhdEmbedding"
        )

        root = _memory_root()
        vector_store = VectorStoreConfig(
            provider="qdrant",
            config={
                "path": str(root / "vectors"),
                "collection_name": f"fhd_memory_{dims}_{self._embedding_fingerprint[:16]}",
                "embedding_model_dims": dims,
            },
        )
        config = _bypass_validation(
            MemoryConfig,
            llm=_bypass_validation(LlmConfig, provider="fhd_offline", config={}),
            embedder=_bypass_validation(
                EmbedderConfig,
                provider="fhd",
                config={"model": f"fhd-{self._mode}", "embedding_dims": dims},
            ),
            vector_store=vector_store,
            history_db_path=str(root / "history.db"),
            reranker=None,
            version="v1.1",
            custom_instructions=None,
        )
        from mem0 import Memory

        memory = Memory(config)
        # mem0 内置 BM25 稀疏编码会在首次写入时联网下载模型；本产品已在应用层做混合检索，
        # 这里关闭该槽位，保持长期记忆链路完全离线。
        store = getattr(memory, "vector_store", None)
        if store is not None and hasattr(store, "_has_bm25_slot"):
            store._has_bm25_slot = False
        logger.info("长期记忆后端已启用：mem0 + %s 嵌入（%s 维）", self._mode, dims)
        return memory

    # ---------------- 写入 / 检索 ----------------
    def remember(
        self,
        *,
        user_id: str,
        user_message: str,
        assistant_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        memory = self._active()
        if memory is None or not user_id:
            return False
        user_text = str(user_message or "").strip()
        assistant_text = str(assistant_message or "").strip()
        if not user_text and not assistant_text:
            return False
        content = f"用户：{user_text[:800]}\n回复：{assistant_text[:1200]}".strip()
        payload = {k: v for k, v in (metadata or {}).items() if v not in (None, "")}
        payload.setdefault("memory_type", "utterance")
        payload.setdefault("valid_from", iso_at())
        payload.setdefault("valid_to", "")
        payload.setdefault("superseded_by", "")
        payload.setdefault("expiration_date", expiration_iso(90))
        try:
            memory.add(
                messages=[{"role": "user", "content": content}],
                user_id=str(user_id),
                metadata=payload,
                infer=False,
            )
            return True
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆写入失败：%s", exc)
            return False

    def recall(self, *, user_id: str, query: str, limit: int = 3) -> list[dict[str, Any]]:
        memory = self._active()
        text = str(query or "").strip()
        if memory is None or not user_id or not text:
            return []
        from app.domain.shared_services.user_memory_service import get_user_memory_service

        authority = get_user_memory_service()
        self._rebuild_owner_projection(user_id, authority)
        top_k = max(1, min(20, int(limit)))
        started = time.perf_counter()
        # 多取候选再重排，给词法与时效留出调整空间。
        rows = self._search_rows(
            memory, text, user_id=user_id, limit=min(20, top_k * 3), threshold=self._min_score
        )
        hits: list[dict[str, Any]] = []
        for item in rows:
            content = str(item.get("memory") or item.get("data") or "").strip()
            if not content:
                continue
            raw_metadata = item.get("metadata")
            stored: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            hits.append(
                {
                    "chunk_id": str(item.get("id") or ""),
                    "content": content,
                    "score": float(item.get("score") or 0.0),
                    "metadata": {
                        **stored,
                        "source": "long_term_memory",
                        "memory_source": str(stored.get("source") or ""),
                        "last_used": str(item.get("updated_at") or ""),
                    },
                }
            )
        hits = authority.filter_recalled_memories(user_id, hits)
        ranked = rank_hits(hits, query=text, limit=top_k)
        from app.application.user_memory.retrieve import merge_relation_hits, relation_recall_hits

        related = relation_recall_hits(user_id, text, memory_service=authority)
        ranked = merge_relation_hits(ranked, related, limit=top_k)
        observe_memory_recall(
            outcome="hit" if ranked else "empty",
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return ranked

    def _rebuild_owner_projection(self, user_id: str, authority: Any) -> None:
        """Replay authority once per process/model generation, retrying failed work."""
        with self._projection_lock:
            if (
                user_id in self._projected_owners
                or time.monotonic() < self._projection_retry_after.get(user_id, 0)
            ):
                return
            generation = time.monotonic() + 30
            self._projection_retry_after[user_id] = generation
        # No global replay lock may be held while acquiring a source's file
        # lock or doing external IO. Failed writes invalidate this generation.
        try:
            result = authority.rebuild_memory_projections(user_id)
            with self._projection_lock:
                if (
                    not result.get("retry_required")
                    and self._projection_retry_after.get(user_id) == generation
                ):
                    self._projected_owners.add(user_id)
                    self._projection_retry_after.pop(user_id, None)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("Memory projection rebuild pending: %s", type(exc).__name__)

    def invalidate_projection(self, user_id: str) -> None:
        """A failed external write invalidates the successful replay cache."""
        with self._projection_lock:
            self._projected_owners.discard(user_id)
            self._projection_retry_after[user_id] = time.monotonic() + 30

    def extract_candidates(
        self,
        *,
        user_id: str,
        user_message: str,
        assistant_message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        from app.infrastructure.memory.candidate_extraction import extract_candidates

        if not user_id or not user_message.strip():
            return []
        if _backend_choice() == "legacy" or not _consolidation_enabled():
            return None
        return extract_candidates(user_message)

    def _source_rows(
        self, memory: Any, user_id: str, source_memory_id: str
    ) -> list[dict[str, Any]]:
        raw = memory.get_all(
            filters={"user_id": user_id, "source_memory_id": source_memory_id},
            top_k=100,
            show_expired=True,
        )
        rows = raw.get("results", []) if isinstance(raw, dict) else raw
        return [
            row
            for row in (rows or [])
            if isinstance(row, dict)
            and self._matches_owner(row, user_id)
            and isinstance(row.get("metadata"), dict)
            and (row.get("metadata") or {}).get("source_memory_id") == source_memory_id
        ]

    def upsert_governed(
        self,
        *,
        user_id: str,
        source_memory_id: str,
        revision: int,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Project a confirmed revision; application reads revalidate its authority."""
        if (
            not user_id
            or not source_memory_id
            or not text.strip()
            or type(revision) is not int
            or revision < 1
        ):
            return False
        memory = self._active()
        if memory is None:
            self.invalidate_projection(user_id)
            return False
        key = hashlib.sha256(f"{user_id}\0{source_memory_id}".encode()).hexdigest()
        payload = {
            **(metadata or {}),
            "memory_type": "fact",
            "user_id": user_id,
            "source": "memory_v2",
            "source_owner_id": user_id,
            "source_memory_id": source_memory_id,
            "source_revision": revision,
            "valid_to": "",
            "superseded_by": "",
        }
        try:
            with FileLock(str(_memory_root() / f"projection-{key}.lock"), timeout=5):
                rows = self._source_rows(memory, user_id, source_memory_id)
                if any(
                    int((row.get("metadata") or {}).get("source_revision") or 0) > revision
                    for row in rows
                ):
                    self.invalidate_projection(user_id)
                    return False
                if rows:
                    current = max(
                        rows,
                        key=lambda row: int(
                            (row.get("metadata") or {}).get("source_revision") or 0
                        ),
                    )
                    if (
                        int((current.get("metadata") or {}).get("source_revision") or 0) == revision
                        and str(current.get("memory") or current.get("data") or "") != text
                    ):
                        self.invalidate_projection(user_id)
                        return False
                    if str(current.get("memory") or current.get("data") or "") != text or any(
                        current["metadata"].get(key) != value for key, value in payload.items()
                    ):
                        memory.update(memory_id=str(current["id"]), text=text, metadata=payload)
                    duplicate_ids = [str(row["id"]) for row in rows if row["id"] != current["id"]]
                    if self._forget_ids(memory, user_id, duplicate_ids, None) < len(duplicate_ids):
                        self.invalidate_projection(user_id)
                        return False
                    return True
                result = memory.add(
                    messages=[{"role": "user", "content": text}],
                    user_id=user_id,
                    metadata=payload,
                    infer=False,
                )
                written = bool(_result_id(result))
                if not written:
                    self.invalidate_projection(user_id)
                return written
        except RECOVERABLE_ERRORS as exc:
            self.invalidate_projection(user_id)
            logger.warning("Governed memory projection failed: %s", type(exc).__name__)
            return False

    def forget_source(self, *, user_id: str, source_memory_id: str) -> int:
        """Remove only this owner's projection; never widen to user-wide deletion."""
        if not user_id or not source_memory_id:
            return 0
        memory = self._active()
        if memory is None:
            self.invalidate_projection(user_id)
            return -1
        deleted = 0
        key = hashlib.sha256(f"{user_id}\0{source_memory_id}".encode()).hexdigest()
        try:
            with FileLock(str(_memory_root() / f"projection-{key}.lock"), timeout=5):
                for _ in range(_MAX_MOD_DELETE_PAGES):
                    rows = self._source_rows(memory, user_id, source_memory_id)
                    if not rows:
                        return deleted
                    count = self._forget_ids(
                        memory, user_id, [str(row["id"]) for row in rows], None
                    )
                    deleted += count
                    if count < len(rows):
                        break
        except RECOVERABLE_ERRORS as exc:
            logger.warning("Governed memory projection removal failed: %s", type(exc).__name__)
        self.invalidate_projection(user_id)
        return -1

    # ---------------- 所有权校验与 SDK 适配 ----------------
    def _search_rows(
        self,
        memory: Any,
        text: str,
        *,
        user_id: str,
        limit: int,
        threshold: float,
        filters_extra: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        filters = {**dict(filters_extra or {}), "user_id": str(user_id)}
        try:
            parameters = inspect.signature(memory.search).parameters
            if "filters" in parameters:
                raw = memory.search(text, filters=filters, top_k=limit, threshold=threshold)
            elif "user_id" in parameters:
                raw = memory.search(text, user_id=str(user_id), limit=limit, threshold=threshold)
            else:
                return []
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆检索失败：%s", exc)
            return []
        rows = raw.get("results") if isinstance(raw, dict) else raw
        return [
            item
            for item in (rows or [])
            if isinstance(item, dict) and self._matches_owner(item, user_id)
        ]

    @staticmethod
    def _matches_owner(item: dict[str, Any], user_id: str, mod_id: str | None = None) -> bool:
        metadata = item.get("metadata")
        meta = metadata if isinstance(metadata, dict) else {}
        owners = [source["user_id"] for source in (item, meta) if "user_id" in source]
        if not user_id or not owners or any(str(owner) != str(user_id) for owner in owners):
            return False
        mods = [source["mod_id"] for source in (item, meta) if "mod_id" in source]
        return mod_id is None or bool(mods and all(str(mod) == str(mod_id) for mod in mods))

    def _owned_memory(
        self, memory: Any, user_id: str, memory_id: str, mod_id: str | None = None
    ) -> dict[str, Any] | None:
        # SDK identities are immutable; never authorize a mutation from an unscoped id alone.
        getter = getattr(memory, "get", None)
        if not callable(getter) or not user_id or not memory_id:
            return None
        try:
            item = getter(str(memory_id))
        except RECOVERABLE_ERRORS:
            return None
        if (
            isinstance(item, dict)
            and str(item.get("id") or "") == str(memory_id)
            and self._matches_owner(item, user_id, mod_id)
        ):
            return item
        return None

    def forget(
        self,
        *,
        user_id: str,
        memory_ids: list[str] | None = None,
        mod_id: str | None = None,
    ) -> int:
        """删除治理：按记忆 id、按用户、或按 Mod 清理；失败返回 0。"""
        memory = self._active()
        if memory is None or not user_id:
            return 0
        if mod_id is not None and not str(mod_id).strip():
            return 0
        if memory_ids is not None:
            return self._forget_ids(memory, user_id, memory_ids, mod_id)
        if mod_id is not None:
            # No delete_all fallback may widen a Mod-scoped request to the whole user.
            deleted = 0
            seen: set[str] = set()
            for _ in range(_MAX_MOD_DELETE_PAGES):
                try:
                    if "filters" not in inspect.signature(memory.get_all).parameters:
                        return deleted
                    rows = memory.get_all(
                        filters={"user_id": str(user_id), "mod_id": str(mod_id)},
                        top_k=100,
                        show_expired=True,
                    )
                except RECOVERABLE_ERRORS as exc:
                    logger.warning("长期记忆按 Mod 清理失败：%s", exc)
                    return deleted
                items = rows.get("results", []) if isinstance(rows, dict) else rows
                ids = [
                    str(row.get("id") or "")
                    for row in (items or [])
                    if isinstance(row, dict) and self._matches_owner(row, user_id, mod_id)
                ]
                pending = [mid for mid in ids if mid and mid not in seen]
                if not pending:
                    return deleted
                seen.update(pending)
                deleted += self._forget_ids(memory, user_id, pending, mod_id)
            # Return the exact partial count; never widen an exhausted Mod request.
            return deleted
        try:
            result = memory.delete_all(user_id=str(user_id))
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆批量删除失败：%s", exc)
            return 0
        return (
            int(result.get("deleted_count") or result.get("count") or 0)
            if isinstance(result, dict)
            else 0
        )

    def _forget_ids(
        self, memory: Any, user_id: str, memory_ids: list[str], mod_id: str | None
    ) -> int:
        deleted = 0
        for memory_id in dict.fromkeys(memory_ids):
            if self._owned_memory(memory, user_id, str(memory_id), mod_id) is None:
                continue
            try:
                memory.delete(str(memory_id))
                deleted += 1
            except RECOVERABLE_ERRORS as exc:
                logger.warning("长期记忆删除失败：%s", exc)
        return deleted

    def close(self) -> None:
        """释放本地向量库句柄；进程退出与测试清理都会调用。"""
        memory, self._memory = self._memory, None
        self._initialized = False
        self._projected_owners.clear()
        self._projection_retry_after.clear()
        if memory is None:
            return
        _close_memory_stores(memory)

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": "mem0" if self._memory is not None else "legacy",
            "embedding_mode": self._mode,
            "embedding_dims": self._dims,
            "embedding_fingerprint": self._embedding_fingerprint,
            "semantic_embedding_available": self._mode in {"local", "remote", "fastembed"},
            "min_score": self._min_score,
            "failed": self._failed,
        }


def format_recalled_memories(hits: list[dict[str, Any]], *, max_chars: int | None = None) -> str:
    """把召回片段格式化为提示词片段，带固定字符预算。"""
    if not hits:
        return ""
    budget = (
        int(_env_float(_ENV_MAX_CHARS, _DEFAULT_PROMPT_CHARS)) if max_chars is None else max_chars
    )
    from app.application.user_memory.retrieve import format_relation_evidence

    lines = ["【长期记忆】以下为历史会话中可能相关的片段，仅作参考，不要当成本轮已核实的事实："]
    for index, hit in enumerate(hits, start=1):
        if not isinstance(hit, dict):
            continue
        content = str(hit.get("content") or "").strip().replace("\n", " ")[:400]
        if not content:
            continue
        metadata = hit.get("metadata")
        meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}
        prefix = "事实：" if str(meta.get("memory_type") or "") == "fact" else ""
        line = f"{index}. {prefix}{content}{format_relation_evidence(hit)}"
        if len("\n".join([*lines, line])) > budget:
            break
        lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else ""


_service: Mem0LongTermMemory | None = None
_service_lock = threading.Lock()


def get_long_term_memory() -> Mem0LongTermMemory:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = Mem0LongTermMemory()
                import atexit

                atexit.register(_service.close)
    return _service


def _close_memory_stores(memory: Any) -> None:
    """关闭 mem0 持有的本地 Qdrant 句柄；同一 client 只关一次。"""
    clients: list[Any] = []
    # 用实例属性 _entity_store，避免触发会新建客户端的 entity_store 属性。
    for name in ("vector_store", "_telemetry_vector_store", "_entity_store"):
        client = getattr(getattr(memory, name, None), "client", None)
        if client is not None and client not in clients:
            clients.append(client)
    for client in clients:
        closer = getattr(client, "close", None)
        if not callable(closer):
            continue
        try:
            closer()
        except RECOVERABLE_ERRORS:
            logger.debug("长期记忆向量库关闭失败", exc_info=True)


def reset_long_term_memory_for_tests() -> None:
    global _service
    with _service_lock:
        service, _service = _service, None
    if service is not None:
        service.close()


__all__ = [
    "FhdEmbedding",
    "Mem0LongTermMemory",
    "OfflineLLM",
    "format_recalled_memories",
    "get_long_term_memory",
    "reset_long_term_memory_for_tests",
]
