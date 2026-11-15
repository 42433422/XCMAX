"""mem0 OSS 长期记忆后端。

设计原则：
- 可选依赖：未安装 mem0ai / qdrant-client 时静默停用，调用方继续走原有记忆链路。
- 离线可用：嵌入复用本地 ``EmbeddingService``（默认 hash，可切本地模型），不联网、无 torch。
- 写入分两段：主链只写原始轮次；后台用规则抽取事实并按 ADD / NOOP / SUPERSEDE 合并。
- 记忆带有效区间：``valid_from`` / ``valid_to`` / ``superseded_by``，召回时过滤失效项。
- 数据边界：所有查询强制带 ``user_id`` 过滤，租户/Mod/渠道在应用层再过滤。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

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
_ENV_FACT_TTL_DAYS = "XCAGI_LONG_TERM_MEMORY_FACT_TTL_DAYS"
_ENV_CONSOLIDATION = "XCAGI_MEMORY_CONSOLIDATION"

_BACKEND_VALUES = {"auto", "mem0", "legacy"}
_DEFAULT_PROMPT_CHARS = 1800
_DEFAULT_FACT_TTL_DAYS = 365
_CONSOLIDATION_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-facts")


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


def _fact_ttl_days() -> int:
    raw = str(os.environ.get(_ENV_FACT_TTL_DAYS) or "").strip()
    try:
        days = int(raw)
    except ValueError:
        days = _DEFAULT_FACT_TTL_DAYS
    return max(30, min(3650, days))


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
                "collection_name": f"fhd_memory_{dims}",
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
        ranked = rank_hits(hits, query=text, limit=top_k)
        observe_memory_recall(
            outcome="hit" if ranked else "empty",
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return ranked

    # ---------------- 事实合并（冷路径） ----------------
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
        filters = {"user_id": str(user_id), **dict(filters_extra or {})}
        try:
            try:
                raw = memory.search(text, filters=filters, top_k=limit, threshold=threshold)
            except TypeError:
                raw = memory.search(text, user_id=str(user_id), limit=limit, threshold=threshold)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆检索失败：%s", exc)
            return []
        rows = raw.get("results") if isinstance(raw, dict) else raw
        return [item for item in (rows or []) if isinstance(item, dict)]

    def search_facts(
        self, user_id: str, fact: dict[str, Any], limit: int = 5
    ) -> list[dict[str, Any]]:
        """按事实键找同主题的活跃记忆，供合并决策使用。"""
        memory = self._active()
        key = str(fact.get("key") or "").strip()
        query = str(fact.get("text") or fact.get("value") or key).strip()
        if memory is None or not user_id or not key or not query:
            return []
        rows = self._search_rows(
            memory,
            query,
            user_id=user_id,
            limit=max(1, min(20, int(limit))),
            threshold=0.0,
            filters_extra={"memory_type": "fact"},
        )
        hits: list[dict[str, Any]] = []
        for item in rows:
            raw_metadata = item.get("metadata")
            meta: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            if str(meta.get("memory_type") or "") != "fact":
                continue
            if str(meta.get("fact_key") or "") != key:
                continue
            content = str(item.get("memory") or item.get("data") or "").strip()
            hits.append(
                {
                    "chunk_id": str(item.get("id") or ""),
                    "content": content,
                    "score": float(item.get("score") or 0.0),
                    "metadata": meta,
                }
            )
        return hits

    def add_fact(self, user_id: str, fact: dict[str, Any], *, supersedes: str = "") -> str | None:
        memory = self._active()
        text = str(fact.get("text") or "").strip()
        key = str(fact.get("key") or "").strip()
        if memory is None or not user_id or not text or not key:
            return None
        metadata: dict[str, Any] = {
            "memory_type": "fact",
            "fact_key": key,
            "fact_value": str(fact.get("value") or ""),
            "confidence": float(fact.get("confidence") or 0.7),
            "valid_from": iso_at(),
            "valid_to": "",
            "superseded_by": "",
            "expiration_date": expiration_iso(_fact_ttl_days()),
            "source": "long_term_memory",
        }
        if supersedes:
            metadata["supersedes"] = supersedes
        try:
            result = memory.add(
                messages=[{"role": "user", "content": text}],
                user_id=str(user_id),
                metadata=metadata,
                infer=False,
            )
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆事实写入失败：%s", exc)
            return None
        return _result_id(result)

    def supersede_fact(
        self,
        user_id: str,
        memory_id: str,
        *,
        content: str,
        new_id: str,
        today: str,
    ) -> bool:
        """把旧事实标记为失效；兼容 mem0 各版本的 text/data 参数名。"""
        memory = self._active()
        if memory is None or not memory_id:
            return False
        metadata = {"valid_to": today, "superseded_by": new_id or "replacement"}
        try:
            try:
                memory.update(memory_id=memory_id, text=content or "", metadata=metadata)
            except TypeError:
                memory.update(memory_id=memory_id, data=content or "", metadata=metadata)
            return True
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆失效标记失败：%s", exc)
            return False

    def consolidate_facts(
        self, *, user_id: str, facts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        from app.infrastructure.memory.consolidation import consolidate

        if not facts or not user_id:
            return []
        return consolidate(self, user_id=user_id, facts=facts)

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
        if memory_ids:
            deleted = 0
            for memory_id in memory_ids:
                try:
                    memory.delete(str(memory_id))
                    deleted += 1
                except RECOVERABLE_ERRORS as exc:
                    logger.warning("长期记忆删除失败：%s", exc)
            return deleted
        result: Any = {}
        try:
            if mod_id:
                result = memory.delete_all(user_id=str(user_id), mod_id=str(mod_id))
            else:
                result = memory.delete_all(user_id=str(user_id))
        except TypeError:
            if mod_id:
                logger.warning("存储不支持按 Mod 删除，已跳过该清理请求")
                return 0
            try:
                result = memory.delete_all(user_id=str(user_id))
            except RECOVERABLE_ERRORS as exc:
                logger.warning("长期记忆批量删除失败：%s", exc)
                return 0
        except RECOVERABLE_ERRORS as exc:
            logger.warning("长期记忆批量删除失败：%s", exc)
            return 0
        if isinstance(result, dict):
            return int(result.get("deleted_count") or result.get("count") or 0)
        return 0

    def close(self) -> None:
        """释放本地向量库句柄；进程退出与测试清理都会调用。"""
        memory, self._memory = self._memory, None
        self._initialized = False
        if memory is None:
            return
        try:
            client = getattr(getattr(memory, "vector_store", None), "client", None)
            if client is not None:
                client.close()
        except RECOVERABLE_ERRORS:
            logger.debug("长期记忆向量库关闭失败", exc_info=True)

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": "mem0" if self._memory is not None else "legacy",
            "embedding_mode": self._mode,
            "embedding_dims": self._dims,
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
        line = f"{index}. {prefix}{content}"
        if len("\n".join([*lines, line])) > budget:
            break
        lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else ""


def schedule_fact_consolidation(*, user_id: str, facts: list[dict[str, Any]]) -> None:
    """主链只入队，抽取后的事实合并在单线程后台执行。"""
    if not facts or not user_id or not _consolidation_enabled():
        return
    service = get_long_term_memory()
    if not service.enabled:
        return
    _CONSOLIDATION_EXECUTOR.submit(_safe_consolidate, service, user_id, list(facts))


def _safe_consolidate(
    service: Mem0LongTermMemory, user_id: str, facts: list[dict[str, Any]]
) -> None:
    try:
        service.consolidate_facts(user_id=user_id, facts=facts)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("长期记忆事实合并失败：%s", exc)


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


def reset_long_term_memory_for_tests() -> None:
    global _service
    with _service_lock:
        _service = None


__all__ = [
    "FhdEmbedding",
    "Mem0LongTermMemory",
    "OfflineLLM",
    "format_recalled_memories",
    "get_long_term_memory",
    "reset_long_term_memory_for_tests",
    "schedule_fact_consolidation",
]
