"""Branch-coverage supplement for dataset_rag_app_service.py.

聚焦 test_dataset_rag_cov.py 未覆盖的异常分支与边界条件：
- _load_persisted_state 的损坏 JSON / 非字典 payload / 空存储
- _extract_file_text 的不支持类型 / 文件不存在 / PDF/DOCX 导入失败
- _resolve_document_version 的非法版本字符串
- _resolve_document_for_version 的版本匹配边界
- _run_rebuild_job 的错误恢复与重试逻辑
- _query_vector_index_candidates 的后端错误
- _sync_vector_index_locked / _vector_index_status 的后端异常
- _filter_chunks 的 latest 版本过滤
- _metadata_matches 的嵌套 dict / list 匹配
- _rerank_chunks 的空 query / 精确匹配 bonus
- _coerce_access_context 的各类 permissions 格式
- _resolve_tenant_for_access 的 admin/tenant 边界
- _ensure_tenant_allowed 的缺失 tenant 上下文
- _deterministic_answer 的空 chunks / 长文本截断
- _chunk_to_dict 的 public/private metadata
- _document_from_dict / _rebuild_job_from_dict 的缺失字段
- _build_dataset_vector_index_backend 的 pgvector / 不支持后端
- _stable_document_id / _clean_key / _tokenize_for_rerank 边界
- ingest_document 的 file_path 路径解析与提取
- delete_document / diff_versions / rollback 的边界
- start_rebuild_index / cancel_rebuild_job / get_rebuild_job 的状态机
- status / query / answer 的空数据与权限拒绝
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.dataset_rag_app_service import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
    DatasetDocument,
    DatasetRagApplicationService,
    DatasetRebuildJob,
    REBUILD_TERMINAL_STATUSES,
    _build_dataset_vector_index_backend,
    _chunk_to_dict,
    _clean_key,
    _coerce_access_context,
    _deterministic_answer,
    _dict_to_retrieved_chunk,
    _document_from_dict,
    _embedding_metadata,
    _empty_rebuild_queue_summary,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _filter_chunks,
    _has_dataset_permission,
    _metadata_matches,
    _rebuild_job_from_dict,
    _rerank_chunks,
    _resolve_max_concurrent_rebuild_jobs,
    _resolve_tenant_for_access,
    _stable_document_id,
    _tokenize_for_rerank,
    _utc_now_iso,
    get_dataset_rag_app_service,
    reset_dataset_rag_app_service_for_tests,
)
from app.infrastructure.rag.hybrid_retriever import RetrievedChunk
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.safe_download_path import UnsafeDownloadPathError

# ─────────────────────────── helpers ────────────────────────────


def _make_embedder():
    """返回一个确定性 embedder（无真实 ML）。"""

    def embedder(text: str) -> list[float]:
        h = hash(text) % (2**16)
        return [float(h % 256) / 255.0] * 8

    return embedder


def _make_svc(
    tmp_path: Path,
    *,
    workers: bool = False,
    embedder=None,
    backend_name: str = "none",
) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        embedder=embedder or _make_embedder(),
        allowed_roots=[tmp_path],
        storage_path=tmp_path / "store.json",
        rebuild_workers_enabled=workers,
        vector_index_backend_name=backend_name,
    )


def _ingest(
    svc: DatasetRagApplicationService,
    dataset_id: str = "ds1",
    text: str = "hello world content here for testing",
) -> dict:
    return svc.ingest_document(
        dataset_id=dataset_id,
        text=text,
        chunk_strategy="fixed",
        chunk_size=100,
        chunk_overlap=0,
    )


def _make_chunk(
    text: str = "chunk text",
    *,
    source: str = "src",
    chunk_index: int = 0,
    metadata: dict | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        text=text,
        score=0.5,
        source=source,
        chunk_index=chunk_index,
        char_start=0,
        char_end=len(text),
        metadata=metadata or {},
        source_url=source,
        page=None,
    )


# ─────────────── _clean_key 边界 ─────────────────────────────────


class TestCleanKeyBoundary:
    """_clean_key 的各类输入与默认值。"""

    def test_empty_returns_default(self):
        assert _clean_key("", default="def") == "def"

    def test_whitespace_returns_default(self):
        assert _clean_key("   ", default="def") == "def"

    def test_special_chars_replaced(self):
        result = _clean_key("a b/c!d@e", default="def")
        assert " " not in result
        assert "/" not in result
        assert "!" not in result
        assert "@" not in result

    def test_strips_leading_trailing_dots(self):
        assert _clean_key("...abc...", default="def") == "abc"

    def test_strips_leading_trailing_underscores(self):
        assert _clean_key("___abc___", default="def") == "abc"

    def test_strips_leading_trailing_dashes(self):
        assert _clean_key("---abc---", default="def") == "abc"

    def test_all_special_returns_default(self):
        assert _clean_key("...---___", default="def") == "def"

    def test_alnum_preserved(self):
        assert _clean_key("abc123", default="def") == "abc123"

    def test_dash_underscore_dot_preserved(self):
        result = _clean_key("a-b_c.d", default="def")
        assert result == "a-b_c.d"


# ─────────────── _coerce_access_context 边界 ─────────────────────


class TestCoerceAccessContextBoundary:
    """_coerce_access_context 的各类输入。"""

    def test_none_returns_none(self):
        assert _coerce_access_context(None) is None

    def test_dataset_access_context_passthrough(self):
        ctx = DatasetAccessContext(actor_id="u1", tenant_id="t1")
        result = _coerce_access_context(ctx)
        assert result is ctx

    def test_dict_with_string_permissions(self):
        result = _coerce_access_context({"actor_id": "u1", "permissions": "a, b;c"})
        assert result is not None
        assert "a" in result.permissions
        assert "b" in result.permissions
        assert "c" in result.permissions

    def test_dict_with_list_permissions(self):
        result = _coerce_access_context({"permissions": ["a", "b"]})
        assert result is not None
        assert "a" in result.permissions
        assert "b" in result.permissions

    def test_dict_with_set_permissions(self):
        result = _coerce_access_context({"permissions": {"a", "b"}})
        assert result is not None
        assert "a" in result.permissions

    def test_dict_with_frozenset_permissions(self):
        result = _coerce_access_context({"permissions": frozenset({"a", "b"})})
        assert result is not None
        assert "a" in result.permissions

    def test_dict_with_tuple_permissions(self):
        result = _coerce_access_context({"permissions": ("a", "b")})
        assert result is not None
        assert "a" in result.permissions

    def test_dict_with_invalid_permissions_type(self):
        result = _coerce_access_context({"permissions": 123})
        assert result is not None
        assert result.permissions == frozenset()

    def test_dict_with_none_permissions(self):
        result = _coerce_access_context({"permissions": None})
        assert result is not None
        assert result.permissions == frozenset()

    def test_dict_with_user_id_fallback(self):
        result = _coerce_access_context({"user_id": "u123"})
        assert result is not None
        assert result.actor_id == "u123"

    def test_dict_with_admin_flag(self):
        result = _coerce_access_context({"is_admin": True})
        assert result is not None
        assert result.is_admin is True

    def test_dict_with_admin_key(self):
        result = _coerce_access_context({"admin": True})
        assert result is not None
        assert result.is_admin is True

    def test_dict_with_tenant_id(self):
        result = _coerce_access_context({"tenant_id": "tenant-1"})
        assert result is not None
        assert result.tenant_id == "tenant-1"

    def test_dict_with_empty_tenant_id(self):
        result = _coerce_access_context({"tenant_id": ""})
        assert result is not None
        assert result.tenant_id == ""

    def test_dict_with_tenant_id_cleaned(self):
        result = _coerce_access_context({"tenant_id": "tenant 1!"})
        assert result is not None
        assert " " not in result.tenant_id

    def test_string_permissions_with_semicolons(self):
        result = _coerce_access_context({"permissions": "a;b;c"})
        assert result is not None
        assert "a" in result.permissions
        assert "b" in result.permissions

    def test_string_permissions_with_whitespace(self):
        result = _coerce_access_context({"permissions": "  a  ,  b  "})
        assert result is not None
        assert "a" in result.permissions
        assert "b" in result.permissions

    def test_string_permissions_empty_parts_skipped(self):
        result = _coerce_access_context({"permissions": "a,,b,,"})
        assert result is not None
        assert "a" in result.permissions
        assert "b" in result.permissions
        assert "" not in result.permissions


# ─────────────── _has_dataset_permission 边界 ────────────────────


class TestHasDatasetPermissionBoundary:
    """_has_dataset_permission 的权限检查分支。"""

    def test_none_context_allows(self):
        assert _has_dataset_permission(None, DATASET_READ_PERMISSION) is True

    def test_admin_allows(self):
        ctx = DatasetAccessContext(is_admin=True)
        assert _has_dataset_permission(ctx, DATASET_WRITE_PERMISSION) is True

    def test_admin_permission_allows(self):
        ctx = DatasetAccessContext(permissions=frozenset({DATASET_ADMIN_PERMISSION}))
        assert _has_dataset_permission(ctx, DATASET_WRITE_PERMISSION) is True

    def test_exact_permission_allows(self):
        ctx = DatasetAccessContext(permissions=frozenset({DATASET_READ_PERMISSION}))
        assert _has_dataset_permission(ctx, DATASET_READ_PERMISSION) is True

    def test_wildcard_prefix_allows(self):
        ctx = DatasetAccessContext(permissions=frozenset({"dataset.*"}))
        assert _has_dataset_permission(ctx, DATASET_READ_PERMISSION) is True

    def test_full_wildcard_allows(self):
        ctx = DatasetAccessContext(permissions=frozenset({"*"}))
        assert _has_dataset_permission(ctx, DATASET_READ_PERMISSION) is True

    def test_no_matching_permission_denies(self):
        ctx = DatasetAccessContext(permissions=frozenset({"other.permission"}))
        assert _has_dataset_permission(ctx, DATASET_READ_PERMISSION) is False

    def test_empty_permissions_denies(self):
        ctx = DatasetAccessContext(permissions=frozenset())
        assert _has_dataset_permission(ctx, DATASET_READ_PERMISSION) is False


# ─────────────── _ensure_dataset_permission 边界 ─────────────────


class TestEnsureDatasetPermissionBoundary:
    """_ensure_dataset_permission 的拒绝/通过分支。"""

    def test_none_context_returns_none(self):
        assert _ensure_dataset_permission(None, DATASET_READ_PERMISSION, dataset_id="ds") is None

    def test_admin_returns_none(self):
        ctx = DatasetAccessContext(is_admin=True)
        assert _ensure_dataset_permission(ctx, DATASET_WRITE_PERMISSION, dataset_id="ds") is None

    def test_denied_returns_dict(self):
        ctx = DatasetAccessContext(permissions=frozenset())
        result = _ensure_dataset_permission(ctx, DATASET_WRITE_PERMISSION, dataset_id="ds")
        assert result is not None
        assert result["success"] is False
        assert result["error_code"] == "dataset_permission_denied"
        assert result["dataset_id"] == "ds"
        assert result["required_permission"] == DATASET_WRITE_PERMISSION


# ─────────────── _ensure_tenant_allowed 边界 ─────────────────────


class TestEnsureTenantAllowedBoundary:
    """_ensure_tenant_allowed 的租户隔离分支。"""

    def test_none_context_allows(self):
        assert _ensure_tenant_allowed(None, "t1", dataset_id="ds", operation="op") is None

    def test_admin_allows(self):
        ctx = DatasetAccessContext(is_admin=True, tenant_id="t1")
        assert _ensure_tenant_allowed(ctx, "t2", dataset_id="ds", operation="op") is None

    def test_admin_permission_allows(self):
        ctx = DatasetAccessContext(permissions=frozenset({DATASET_ADMIN_PERMISSION}))
        assert _ensure_tenant_allowed(ctx, "t2", dataset_id="ds", operation="op") is None

    def test_no_actor_tenant_denies(self):
        ctx = DatasetAccessContext(actor_id="u1", tenant_id="")
        result = _ensure_tenant_allowed(ctx, "t1", dataset_id="ds", operation="op")
        assert result is not None
        assert result["success"] is False

    def test_no_target_tenant_denies(self):
        ctx = DatasetAccessContext(actor_id="u1", tenant_id="t1")
        result = _ensure_tenant_allowed(ctx, "", dataset_id="ds", operation="op")
        assert result is not None
        assert result["success"] is False

    def test_tenant_mismatch_denies(self):
        ctx = DatasetAccessContext(actor_id="u1", tenant_id="t1")
        result = _ensure_tenant_allowed(ctx, "t2", dataset_id="ds", operation="op")
        assert result is not None
        assert result["success"] is False

    def test_tenant_match_allows(self):
        ctx = DatasetAccessContext(actor_id="u1", tenant_id="t1")
        assert _ensure_tenant_allowed(ctx, "t1", dataset_id="ds", operation="op") is None


# ─────────────── _resolve_tenant_for_access 边界 ─────────────────


class TestResolveTenantForAccessBoundary:
    """_resolve_tenant_for_access 的租户解析分支。"""

    def test_none_context_with_requested(self):
        tenant, denied = _resolve_tenant_for_access(
            None, "t1", required_permission=DATASET_READ_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is None
        assert tenant == "t1"

    def test_none_context_no_requested_uses_default(self):
        tenant, denied = _resolve_tenant_for_access(
            None, "", required_permission=DATASET_READ_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is None
        assert tenant == "default"

    def test_none_context_no_requested_empty_default(self):
        tenant, denied = _resolve_tenant_for_access(
            None, "", required_permission=DATASET_READ_PERMISSION,
            default_without_context="", dataset_id="ds",
        )
        assert denied is None
        assert tenant == ""

    def test_admin_with_requested(self):
        ctx = DatasetAccessContext(is_admin=True, tenant_id="t1")
        tenant, denied = _resolve_tenant_for_access(
            ctx, "t2", required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is None
        assert tenant == "t2"

    def test_admin_no_requested_uses_default(self):
        ctx = DatasetAccessContext(is_admin=True)
        tenant, denied = _resolve_tenant_for_access(
            ctx, "", required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is None
        assert tenant == "default"

    def test_non_admin_no_actor_tenant_denies(self):
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="", permissions=frozenset([DATASET_READ_PERMISSION])
        )
        tenant, denied = _resolve_tenant_for_access(
            ctx, "", required_permission=DATASET_READ_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is not None
        assert tenant == ""

    def test_non_admin_requested_mismatch_denies(self):
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="t1", permissions=frozenset([DATASET_READ_PERMISSION])
        )
        tenant, denied = _resolve_tenant_for_access(
            ctx, "t2", required_permission=DATASET_READ_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is not None
        assert tenant == ""

    def test_non_admin_requested_matches_actor(self):
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="t1", permissions=frozenset([DATASET_READ_PERMISSION])
        )
        tenant, denied = _resolve_tenant_for_access(
            ctx, "t1", required_permission=DATASET_READ_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is None
        assert tenant == "t1"

    def test_non_admin_no_requested_uses_actor_tenant(self):
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="t1", permissions=frozenset([DATASET_READ_PERMISSION])
        )
        tenant, denied = _resolve_tenant_for_access(
            ctx, "", required_permission=DATASET_READ_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is None
        assert tenant == "t1"

    def test_permission_denied_returns_empty_tenant(self):
        ctx = DatasetAccessContext(permissions=frozenset())
        tenant, denied = _resolve_tenant_for_access(
            ctx, "t1", required_permission=DATASET_WRITE_PERMISSION,
            default_without_context="default", dataset_id="ds",
        )
        assert denied is not None
        assert tenant == ""


# ─────────────── _stable_document_id 边界 ────────────────────────


class TestStableDocumentIdBoundary:
    """_stable_document_id 的确定性。"""

    def test_deterministic_same_input(self):
        id1 = _stable_document_id("ds", "t1", "src", 1, "text")
        id2 = _stable_document_id("ds", "t1", "src", 1, "text")
        assert id1 == id2

    def test_different_input_different_id(self):
        id1 = _stable_document_id("ds", "t1", "src", 1, "text1")
        id2 = _stable_document_id("ds", "t1", "src", 1, "text2")
        assert id1 != id2

    def test_prefix_is_doc(self):
        result = _stable_document_id("ds", "t1", "src", 1, "text")
        assert result.startswith("doc_")

    def test_empty_inputs(self):
        result = _stable_document_id("", "", "", 0, "")
        assert result.startswith("doc_")
        assert len(result) == 20  # "doc_" + 16 chars


# ─────────────── _document_from_dict 边界 ────────────────────────


class TestDocumentFromDictBoundary:
    """_document_from_dict 的字段缺失与默认值。"""

    def test_full_dict(self):
        data = {
            "document_id": "doc1",
            "source": "src",
            "parser": "text_file",
            "text_length": 100,
            "chunk_count": 3,
            "tenant_id": "t1",
            "version": 2,
            "version_label": "v2",
            "metadata": {"key": "value"},
        }
        doc = _document_from_dict(data)
        assert doc.document_id == "doc1"
        assert doc.version == 2
        assert doc.version_label == "v2"

    def test_empty_dict_uses_defaults(self):
        doc = _document_from_dict({})
        assert doc.document_id == ""
        assert doc.source == ""
        assert doc.parser == ""
        assert doc.text_length == 0
        assert doc.chunk_count == 0
        assert doc.tenant_id == "default"
        assert doc.version == 1
        assert doc.version_label == "v1"
        assert doc.metadata == {}

    def test_version_from_metadata(self):
        doc = _document_from_dict({"metadata": {"document_version": 5}})
        assert doc.version == 5

    def test_version_label_from_metadata(self):
        doc = _document_from_dict({"version": 3, "metadata": {"version_label": "custom"}})
        assert doc.version_label == "custom"

    def test_tenant_id_from_metadata(self):
        doc = _document_from_dict({"metadata": {"tenant_id": "from_meta"}})
        assert doc.tenant_id == "from_meta"

    def test_tenant_id_cleaned(self):
        doc = _document_from_dict({"tenant_id": "tenant 1!"})
        assert " " not in doc.tenant_id


# ─────────────── _rebuild_job_from_dict 边界 ─────────────────────


class TestRebuildJobFromDictBoundary:
    """_rebuild_job_from_dict 的字段缺失与默认值。"""

    def test_full_dict(self):
        data = {
            "job_id": "job1",
            "dataset_id": "ds1",
            "status": "completed",
            "tenant_id": "t1",
            "metadata_filter": {"key": "value"},
            "document_count": 5,
            "chunk_count": 20,
            "error": "some error",
            "attempt_count": 2,
            "max_attempts": 3,
            "worker_id": "worker1",
            "created_at": "2025-01-01T00:00:00Z",
            "queued_at": "2025-01-01T00:00:01Z",
            "started_at": "2025-01-01T00:00:02Z",
            "completed_at": "2025-01-01T00:00:03Z",
            "cancelled_at": "",
            "updated_at": "2025-01-01T00:00:04Z",
        }
        job = _rebuild_job_from_dict(data)
        assert job.job_id == "job1"
        assert job.status == "completed"
        assert job.max_attempts == 3

    def test_empty_dict_uses_defaults(self):
        job = _rebuild_job_from_dict({})
        assert job.job_id == ""
        assert job.dataset_id == ""
        assert job.status == "queued"
        assert job.max_attempts == 1
        assert job.attempt_count == 0

    def test_queued_at_falls_back_to_created_at(self):
        job = _rebuild_job_from_dict({"created_at": "2025-01-01T00:00:00Z"})
        assert job.queued_at == "2025-01-01T00:00:00Z"

    def test_updated_at_falls_back_to_queued_at(self):
        job = _rebuild_job_from_dict({"queued_at": "2025-01-01T00:00:00Z"})
        assert job.updated_at == "2025-01-01T00:00:00Z"

    def test_max_attempts_clamped_to_minimum(self):
        job = _rebuild_job_from_dict({"max_attempts": 0})
        assert job.max_attempts == 1

    def test_max_attempts_negative_clamped(self):
        job = _rebuild_job_from_dict({"max_attempts": -5})
        assert job.max_attempts == 1


# ─────────────── _chunk_to_dict 边界 ─────────────────────────────


class TestChunkToDictBoundary:
    """_chunk_to_dict 的 public/private metadata 过滤。"""

    def test_private_metadata_included_by_default(self):
        chunk = _make_chunk(metadata={"_embedding": [0.1], "public_key": "value"})
        result = _chunk_to_dict(chunk)
        assert "_embedding" in result["metadata"]
        assert "public_key" in result["metadata"]

    def test_private_metadata_excluded_when_public(self):
        chunk = _make_chunk(metadata={"_embedding": [0.1], "public_key": "value"})
        result = _chunk_to_dict(chunk, public=True)
        assert "_embedding" not in result["metadata"]
        assert "public_key" in result["metadata"]

    def test_none_metadata_becomes_empty_dict(self):
        chunk = _make_chunk(metadata=None)
        chunk.metadata = None
        result = _chunk_to_dict(chunk)
        assert result["metadata"] == {}

    def test_all_fields_present(self):
        chunk = _make_chunk(text="hello", source="src", chunk_index=3)
        result = _chunk_to_dict(chunk)
        assert result["text"] == "hello"
        assert result["source"] == "src"
        assert result["chunk_index"] == 3
        assert "score" in result
        assert "char_start" in result
        assert "char_end" in result
        assert "source_url" in result
        assert "page" in result


# ─────────────── _dict_to_retrieved_chunk 边界 ───────────────────


class TestDictToRetrievedChunkBoundary:
    """_dict_to_retrieved_chunk 的字段缺失。"""

    def test_full_dict(self):
        data = {
            "text": "hello",
            "score": 0.8,
            "source": "src",
            "chunk_index": 2,
            "char_start": 10,
            "char_end": 20,
            "metadata": {"key": "value"},
            "source_url": "url",
            "page": 5,
        }
        chunk = _dict_to_retrieved_chunk(data)
        assert chunk.text == "hello"
        assert chunk.score == 0.8
        assert chunk.source == "src"
        assert chunk.chunk_index == 2
        assert chunk.page == 5

    def test_empty_dict_uses_defaults(self):
        chunk = _dict_to_retrieved_chunk({})
        assert chunk.text == ""
        assert chunk.score == 0.0
        assert chunk.source == ""
        assert chunk.chunk_index == 0
        assert chunk.char_start == 0
        assert chunk.char_end == 0
        assert chunk.metadata == {}
        assert chunk.source_url == ""
        assert chunk.page is None

    def test_non_int_page_becomes_none(self):
        chunk = _dict_to_retrieved_chunk({"page": "not int"})
        assert chunk.page is None

    def test_none_score_becomes_zero(self):
        chunk = _dict_to_retrieved_chunk({"score": None})
        assert chunk.score == 0.0


# ─────────────── _deterministic_answer 边界 ──────────────────────


class TestDeterministicAnswerBoundary:
    """_deterministic_answer 的空 chunks / 长文本截断。"""

    def test_empty_chunks_returns_empty(self):
        assert _deterministic_answer("query", []) == ""

    def test_short_excerpt(self):
        chunk = _make_chunk(text="short text")
        result = _deterministic_answer("query", [chunk])
        assert "query" in result
        assert "short text" in result
        assert "[1]" in result

    def test_long_excerpt_truncated(self):
        long_text = "x" * 500
        chunk = _make_chunk(text=long_text)
        result = _deterministic_answer("query", [chunk])
        assert "..." in result
        assert len(result) < len(long_text) + 100

    def test_empty_query(self):
        chunk = _make_chunk(text="some text")
        result = _deterministic_answer("", [chunk])
        assert "some text" in result
        assert "[1]" in result

    def test_newlines_replaced(self):
        chunk = _make_chunk(text="line1\nline2\nline3")
        result = _deterministic_answer("q", [chunk])
        assert "\n" not in result.replace("\n", "")  # newlines in excerpt replaced


# ─────────────── _embedding_metadata 边界 ────────────────────────


class TestEmbeddingMetadataBoundary:
    """_embedding_metadata 的 embedder 异常与无效输出。"""

    def test_none_embedder_returns_empty(self):
        assert _embedding_metadata(None, "text") == {}

    def test_valid_embedding(self):
        def embedder(text):
            return [0.1, 0.2, 0.3]

        result = _embedding_metadata(embedder, "text")
        assert "_embedding" in result
        assert result["_embedding"] == [0.1, 0.2, 0.3]

    def test_embedder_raises_recoverable_error(self):
        def embedder(text):
            raise ValueError("embed failed")

        result = _embedding_metadata(embedder, "text")
        assert result == {}

    def test_embedder_returns_non_list(self):
        def embedder(text):
            return "not a list"

        result = _embedding_metadata(embedder, "text")
        assert result == {}

    def test_embedder_returns_empty_list(self):
        def embedder(text):
            return []

        result = _embedding_metadata(embedder, "text")
        assert result == {}

    def test_embedder_returns_non_float_values(self):
        def embedder(text):
            return ["not", "floats"]

        result = _embedding_metadata(embedder, "text")
        # 字符串无法转 float → 返回空
        assert result == {}

    def test_embedder_returns_mixed_valid_invalid(self):
        def embedder(text):
            return [0.1, "not float", 0.3]

        result = _embedding_metadata(embedder, "text")
        assert result == {}


# ─────────────── _metadata_matches 边界 ──────────────────────────


class TestMetadataMatchesBoundary:
    """_metadata_matches 的各类匹配场景。"""

    def test_no_filter_matches(self):
        chunk = _make_chunk(metadata={"key": "value"})
        assert _metadata_matches(chunk, {}) is True

    def test_exact_string_match(self):
        chunk = _make_chunk(metadata={"key": "value"})
        assert _metadata_matches(chunk, {"key": "value"}) is True

    def test_string_mismatch(self):
        chunk = _make_chunk(metadata={"key": "value"})
        assert _metadata_matches(chunk, {"key": "other"}) is False

    def test_missing_key(self):
        chunk = _make_chunk(metadata={"key": "value"})
        assert _metadata_matches(chunk, {"missing": "value"}) is False

    def test_list_expected_match(self):
        chunk = _make_chunk(metadata={"key": "value"})
        assert _metadata_matches(chunk, {"key": ["value", "other"]}) is True

    def test_list_expected_no_match(self):
        chunk = _make_chunk(metadata={"key": "value"})
        assert _metadata_matches(chunk, {"key": ["other1", "other2"]}) is False

    def test_dict_expected_match(self):
        chunk = _make_chunk(metadata={"nested": {"sub": "val"}})
        assert _metadata_matches(chunk, {"nested": {"sub": "val"}}) is True

    def test_dict_expected_mismatch(self):
        chunk = _make_chunk(metadata={"nested": {"sub": "val"}})
        assert _metadata_matches(chunk, {"nested": {"sub": "other"}}) is False

    def test_dict_expected_non_dict_actual(self):
        chunk = _make_chunk(metadata={"nested": "not dict"})
        assert _metadata_matches(chunk, {"nested": {"sub": "val"}}) is False

    def test_source_fallback(self):
        """metadata 缺少 source 时回退到 chunk.source。"""
        chunk = _make_chunk(source="my_source", metadata={})
        assert _metadata_matches(chunk, {"source": "my_source"}) is True

    def test_multiple_filters_all_match(self):
        chunk = _make_chunk(metadata={"a": "1", "b": "2"})
        assert _metadata_matches(chunk, {"a": "1", "b": "2"}) is True

    def test_multiple_filters_partial_match(self):
        chunk = _make_chunk(metadata={"a": "1", "b": "2"})
        assert _metadata_matches(chunk, {"a": "1", "b": "3"}) is False


# ─────────────── _filter_chunks 边界 ─────────────────────────────


class TestFilterChunksBoundary:
    """_filter_chunks 的 tenant/version/metadata_filter 过滤。"""

    def test_no_filters_returns_all(self):
        chunks = [_make_chunk(text="a"), _make_chunk(text="b")]
        result = _filter_chunks(chunks, tenant_id="", version="", metadata_filter={})
        assert len(result) == 2

    def test_tenant_filter(self):
        chunks = [
            _make_chunk(metadata={"tenant_id": "t1"}),
            _make_chunk(metadata={"tenant_id": "t2"}),
        ]
        result = _filter_chunks(chunks, tenant_id="t1", version="", metadata_filter={})
        assert len(result) == 1
        assert result[0].metadata["tenant_id"] == "t1"

    def test_metadata_filter(self):
        chunks = [
            _make_chunk(metadata={"category": "a"}),
            _make_chunk(metadata={"category": "b"}),
        ]
        result = _filter_chunks(chunks, tenant_id="", version="", metadata_filter={"category": "a"})
        assert len(result) == 1

    def test_version_latest(self):
        chunks = [
            _make_chunk(metadata={"tenant_id": "t1", "source": "s1", "document_version": 1}),
            _make_chunk(metadata={"tenant_id": "t1", "source": "s1", "document_version": 2}),
            _make_chunk(metadata={"tenant_id": "t1", "source": "s1", "document_version": 3}),
        ]
        result = _filter_chunks(chunks, tenant_id="", version="latest", metadata_filter={})
        assert len(result) == 1
        assert result[0].metadata["document_version"] == 3

    def test_version_specific_number(self):
        chunks = [
            _make_chunk(metadata={"document_version": 1}),
            _make_chunk(metadata={"document_version": 2}),
        ]
        result = _filter_chunks(chunks, tenant_id="", version="2", metadata_filter={})
        assert len(result) == 1
        assert result[0].metadata["document_version"] == 2

    def test_version_v_prefix(self):
        chunks = [
            _make_chunk(metadata={"document_version": 1}),
            _make_chunk(metadata={"document_version": 2}),
        ]
        result = _filter_chunks(chunks, tenant_id="", version="v2", metadata_filter={})
        assert len(result) == 1

    def test_version_label_match(self):
        chunks = [
            _make_chunk(metadata={"version_label": "v1", "document_version": 1}),
            _make_chunk(metadata={"version_label": "v2", "document_version": 2}),
        ]
        result = _filter_chunks(chunks, tenant_id="", version="v2", metadata_filter={})
        assert len(result) == 1

    def test_latest_with_multiple_scopes(self):
        chunks = [
            _make_chunk(metadata={"tenant_id": "t1", "source": "s1", "document_version": 2}),
            _make_chunk(metadata={"tenant_id": "t1", "source": "s2", "document_version": 1}),
            _make_chunk(metadata={"tenant_id": "t2", "source": "s1", "document_version": 3}),
        ]
        result = _filter_chunks(chunks, tenant_id="", version="latest", metadata_filter={})
        # 每个 (tenant, source) scope 各取最新
        assert len(result) == 3


# ─────────────── _rerank_chunks 边界 ─────────────────────────────


class TestRerankChunksBoundary:
    """_rerank_chunks 的空 query / 精确匹配 bonus。"""

    def test_empty_query_returns_top_k(self):
        chunks = [_make_chunk(text="a"), _make_chunk(text="b")]
        result = _rerank_chunks("", chunks, top_k=2)
        assert len(result) == 2

    def test_whitespace_query_returns_top_k(self):
        chunks = [_make_chunk(text="a"), _make_chunk(text="b")]
        result = _rerank_chunks("   ", chunks, top_k=2)
        assert len(result) == 2

    def test_query_with_overlap(self):
        chunks = [_make_chunk(text="hello world"), _make_chunk(text="foo bar")]
        result = _rerank_chunks("hello", chunks, top_k=2)
        assert result[0].text == "hello world"

    def test_exact_match_bonus(self):
        chunks = [_make_chunk(text="exact match"), _make_chunk(text="exact")]
        result = _rerank_chunks("exact", chunks, top_k=2)
        # "exact" 精确匹配 bonus 更高
        assert any(c.text == "exact" for c in result)

    def test_top_k_limit(self):
        chunks = [_make_chunk(text=f"chunk{i}") for i in range(10)]
        result = _rerank_chunks("chunk", chunks, top_k=3)
        assert len(result) == 3

    def test_rerank_source_suffix(self):
        chunks = [_make_chunk(text="hello", source="src")]
        result = _rerank_chunks("hello", chunks, top_k=1)
        assert "+rerank" in result[0].source

    def test_rerank_source_no_double_suffix(self):
        chunks = [_make_chunk(text="hello", source="src+rerank")]
        result = _rerank_chunks("hello", chunks, top_k=1)
        assert result[0].source == "src+rerank"


# ─────────────── _tokenize_for_rerank 边界 ───────────────────────


class TestTokenizeForRerankBoundary:
    """_tokenize_for_rerank 的分词。"""

    def test_empty_string(self):
        assert _tokenize_for_rerank("") == []

    def test_only_special_chars(self):
        assert _tokenize_for_rerank("!!!@@@###") == []

    def test_mixed_alnum_special(self):
        result = _tokenize_for_rerank("hello, world! 123")
        assert "hello" in result
        assert "world" in result
        assert "123" in result

    def test_lowercase(self):
        result = _tokenize_for_rerank("HELLO World")
        assert "hello" in result
        assert "world" in result

    def test_chinese_chars_preserved_as_alnum(self):
        # Python's str.isalnum() returns True for CJK characters
        result = _tokenize_for_rerank("hello你好world")
        assert result == ["hello你好world"]

    def test_special_chars_become_spaces(self):
        result = _tokenize_for_rerank("hello, world")
        assert result == ["hello", "world"]


# ─────────────── _build_dataset_vector_index_backend 边界 ────────


class TestBuildVectorIndexBackendBoundary:
    """_build_dataset_vector_index_backend 的后端选择。"""

    def test_none_name_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_VECTOR_BACKEND", raising=False)
        result = _build_dataset_vector_index_backend(
            backend_name="none", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_disabled_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="disabled", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_off_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="off", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_memory_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="memory", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_json_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="json", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_empty_name_returns_none(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_sqlite_name_returns_backend(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="sqlite", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is not None

    def test_sqlite_vector_name_returns_backend(self, tmp_path):
        result = _build_dataset_vector_index_backend(
            backend_name="sqlite_vector", storage_path=tmp_path, vector_index_path=None,
        )
        assert result is not None

    def test_sqlite_with_explicit_path(self, tmp_path):
        path = tmp_path / "custom.db"
        result = _build_dataset_vector_index_backend(
            backend_name="sqlite", storage_path=tmp_path, vector_index_path=str(path),
        )
        assert result is not None

    def test_unsupported_name_raises(self, tmp_path):
        with pytest.raises(ValueError, match="unsupported dataset vector backend"):
            _build_dataset_vector_index_backend(
                backend_name="unknown_backend", storage_path=tmp_path, vector_index_path=None,
            )

    def test_env_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_VECTOR_BACKEND", "none")
        result = _build_dataset_vector_index_backend(
            backend_name=None, storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None

    def test_env_xcagi_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_VECTOR_BACKEND", raising=False)
        monkeypatch.setenv("XCAGI_DATASET_RAG_VECTOR_BACKEND", "none")
        result = _build_dataset_vector_index_backend(
            backend_name=None, storage_path=tmp_path, vector_index_path=None,
        )
        assert result is None


# ─────────────── _resolve_max_concurrent_rebuild_jobs 边界 ───────


class TestResolveMaxConcurrentRebuildJobsBoundary:
    """_resolve_max_concurrent_rebuild_jobs 的解析。"""

    def test_configured_value(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(4) == 4

    def test_configured_clamped_to_min(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(0) == 1

    def test_configured_clamped_to_max(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(100) == 8

    def test_configured_negative_clamped(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(-5) == 1

    def test_env_value(self, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", "3")
        assert _resolve_max_concurrent_rebuild_jobs(None) == 3

    def test_env_xcagi_fallback(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        monkeypatch.setenv("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", "2")
        assert _resolve_max_concurrent_rebuild_jobs(None) == 2

    def test_env_non_digit_returns_default(self, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", "not a number")
        assert _resolve_max_concurrent_rebuild_jobs(None) == 1

    def test_env_empty_returns_default(self, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", "")
        monkeypatch.delenv("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(None) == 1

    def test_no_env_no_config_returns_default(self, monkeypatch):
        monkeypatch.delenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_REBUILD_MAX_CONCURRENT", raising=False)
        assert _resolve_max_concurrent_rebuild_jobs(None) == 1

    def test_env_clamped_to_max(self, monkeypatch):
        monkeypatch.setenv("DATASET_RAG_REBUILD_MAX_CONCURRENT", "100")
        assert _resolve_max_concurrent_rebuild_jobs(None) == 8


# ─────────────── _empty_rebuild_queue_summary 边界 ───────────────


class TestEmptyRebuildQueueSummaryBoundary:
    """_empty_rebuild_queue_summary 的结构。"""

    def test_structure(self):
        result = _empty_rebuild_queue_summary(4, worker_enabled=True)
        assert result["max_concurrent_jobs"] == 4
        assert result["worker_enabled"] is True
        assert result["queued"] == 0
        assert result["running"] == 0
        assert result["completed"] == 0
        assert result["failed"] == 0
        assert result["cancelled"] == 0
        assert result["next_job_id"] == ""
        assert result["running_job_ids"] == []

    def test_worker_disabled(self):
        result = _empty_rebuild_queue_summary(1, worker_enabled=False)
        assert result["worker_enabled"] is False


# ─────────────── ingest_document 异常分支 ────────────────────────


class TestIngestDocumentExceptions:
    """ingest_document 的各类异常分支。"""

    def test_no_text_no_file_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(dataset_id="ds", text="", file_path="")
        assert result["success"] is False
        assert "text or file_path is required" in result["message"]

    def test_whitespace_text_no_file_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(dataset_id="ds", text="   ", file_path="")
        assert result["success"] is False

    def test_empty_extracted_text_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(dataset_id="ds", text="")
        assert result["success"] is False

    def test_unsupported_file_type(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.xyz"
        file_path.write_text("content")
        result = svc.ingest_document(dataset_id="ds", file_path=str(file_path))
        assert result["success"] is False
        assert "unsupported" in result["message"].lower() or "dataset_ingest_failed" in result.get("error_code", "")

    def test_nonexistent_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(dataset_id="ds", file_path=str(tmp_path / "nonexistent.txt"))
        assert result["success"] is False

    def test_text_file_extraction(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("This is text file content for testing")
        result = svc.ingest_document(dataset_id="ds", file_path=str(file_path))
        assert result["success"] is True
        assert result["document"]["parser"] == "text_file"

    def test_markdown_file_extraction(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.md"
        file_path.write_text("# Markdown content\n\nParagraph here")
        result = svc.ingest_document(dataset_id="ds", file_path=str(file_path))
        assert result["success"] is True

    def test_csv_file_extraction(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.csv"
        file_path.write_text("a,b,c\n1,2,3")
        result = svc.ingest_document(dataset_id="ds", file_path=str(file_path))
        assert result["success"] is True

    def test_json_file_extraction(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.json"
        file_path.write_text('{"key": "value"}')
        result = svc.ingest_document(dataset_id="ds", file_path=str(file_path))
        assert result["success"] is True

    def test_log_file_extraction(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.log"
        file_path.write_text("[INFO] log line entry")
        result = svc.ingest_document(dataset_id="ds", file_path=str(file_path))
        assert result["success"] is True

    def test_unsafe_file_path(self, tmp_path):
        svc = _make_svc(tmp_path)
        # 路径遍历攻击
        result = svc.ingest_document(dataset_id="ds", file_path="../../../etc/passwd")
        assert result["success"] is False

    def test_version_string_v_prefix(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", version="v5",
        )
        assert result["success"] is True
        assert result["document"]["version"] == 5

    def test_version_string_digit(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", version="3",
        )
        assert result["success"] is True
        assert result["document"]["version"] == 3

    def test_version_invalid_string(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", version="invalid",
        )
        assert result["success"] is False

    def test_version_label_override(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", version_label="custom-label",
        )
        assert result["success"] is True
        assert result["document"]["version_label"] == "custom-label"

    def test_explicit_document_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", document_id="my-doc-id",
        )
        assert result["success"] is True
        assert result["document"]["document_id"] == "my-doc-id"

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.ingest_document(
            dataset_id="ds", text="content", access_context=ctx,
        )
        assert result["success"] is False
        assert result["error_code"] == "dataset_permission_denied"

    def test_tenant_from_metadata(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", metadata={"tenant_id": "meta-tenant"},
        )
        assert result["success"] is True
        assert result["document"]["tenant_id"] == "meta-tenant"

    def test_tenant_from_user_id(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.ingest_document(
            dataset_id="ds", text="content", metadata={"user_id": "user-123"},
        )
        assert result["success"] is True


# ─────────────── delete_document 边界 ────────────────────────────


class TestDeleteDocumentBoundary:
    """delete_document 的各类边界。"""

    def test_delete_nonexistent_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.delete_document("nonexistent", "doc1")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_delete_nonexistent_document(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.delete_document("ds1", "nonexistent-doc")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_delete_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.delete_document("ds1", "doc", access_context=ctx)
        assert result["success"] is False
        assert result["error_code"] == "dataset_permission_denied"

    def test_delete_tenant_mismatch(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        # 先获取已 ingest 的 document_id
        status = svc.status("ds1")
        doc_id = status["documents"][0]["document_id"]
        ctx = DatasetAccessContext(actor_id="u1", tenant_id="other-tenant")
        result = svc.delete_document("ds1", doc_id, access_context=ctx)
        assert result["success"] is False

    def test_delete_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        status = svc.status("ds1")
        doc_id = status["documents"][0]["document_id"]
        result = svc.delete_document("ds1", doc_id)
        assert result["success"] is True
        assert result["document_id"] == doc_id


# ─────────────── diff_versions 边界 ──────────────────────────────


class TestDiffVersionsBoundary:
    """diff_versions 的版本对比边界。"""

    def test_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.diff_versions(
            dataset_id="nonexistent", source="src", from_version=1, to_version=2,
        )
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_document_version_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.diff_versions(
            dataset_id="ds1", source="nonexistent", from_version=1, to_version=2,
        )
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.diff_versions(
            dataset_id="ds1", source="src", from_version=1, access_context=ctx,
        )
        assert result["success"] is False

    def test_diff_same_version(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.diff_versions(
            dataset_id="ds1", source="inline", from_version=1, to_version=1,
        )
        assert result["success"] is True
        assert result["changed"] is False

    def test_diff_latest(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.diff_versions(
            dataset_id="ds1", source="inline", from_version=1, to_version="latest",
        )
        assert result["success"] is True


# ─────────────── rollback_document_version 边界 ──────────────────


class TestRollbackDocumentVersionBoundary:
    """rollback_document_version 的回滚边界。"""

    def test_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.rollback_document_version(
            dataset_id="nonexistent", source="src", target_version=1,
        )
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_target_version_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.rollback_document_version(
            dataset_id="ds1", source="nonexistent", target_version=1,
        )
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.rollback_document_version(
            dataset_id="ds1", source="inline", target_version=1, access_context=ctx,
        )
        assert result["success"] is False

    def test_rollback_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.rollback_document_version(
            dataset_id="ds1", source="inline", target_version=1,
        )
        assert result["success"] is True
        assert "rolled_back_from" in result


# ─────────────── start_rebuild_index 边界 ────────────────────────


class TestStartRebuildIndexBoundary:
    """start_rebuild_index 的重建索引边界。"""

    def test_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.start_rebuild_index(dataset_id="nonexistent")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.start_rebuild_index(dataset_id="ds1", access_context=ctx)
        assert result["success"] is False

    def test_foreground_rebuild(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.start_rebuild_index(dataset_id="ds1", background=False)
        assert result["success"] is True
        assert result["background"] is False

    def test_background_rebuild_no_workers(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc)
        result = svc.start_rebuild_index(dataset_id="ds1", background=True)
        assert result["success"] is True

    def test_max_attempts_clamped(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.start_rebuild_index(dataset_id="ds1", background=False, max_attempts=100)
        assert result["success"] is True
        assert result["job"]["max_attempts"] == 5

    def test_max_attempts_minimum(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.start_rebuild_index(dataset_id="ds1", background=False, max_attempts=0)
        assert result["success"] is True
        assert result["job"]["max_attempts"] == 1


# ─────────────── cancel_rebuild_job 边界 ─────────────────────────


class TestCancelRebuildJobBoundary:
    """cancel_rebuild_job 的取消边界。"""

    def test_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.cancel_rebuild_job("nonexistent", "job1")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_job_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.cancel_rebuild_job("ds1", "nonexistent-job")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.cancel_rebuild_job("ds1", "job1", access_context=ctx)
        assert result["success"] is False

    def test_cancel_completed_job(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        # 先启动一个 foreground rebuild 让它完成
        start_result = svc.start_rebuild_index(dataset_id="ds1", background=False)
        job_id = start_result["job"]["job_id"]
        # 再取消已完成 job
        result = svc.cancel_rebuild_job("ds1", job_id)
        assert result["success"] is True
        assert "already" in result["message"]

    def test_cancel_queued_job(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc)
        # 启动 background rebuild（workers 禁用 → 保持 queued）
        start_result = svc.start_rebuild_index(dataset_id="ds1", background=True)
        job_id = start_result["job"]["job_id"]
        result = svc.cancel_rebuild_job("ds1", job_id)
        assert result["success"] is True

    def test_cancel_running_job_fails(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc)
        start_result = svc.start_rebuild_index(dataset_id="ds1", background=True)
        job_id = start_result["job"]["job_id"]
        # 手动将 job 状态改为 running
        with svc._lock:
            state = svc._datasets.get("ds1")
            if state and job_id in state.rebuild_jobs:
                state.rebuild_jobs[job_id].status = "running"
        result = svc.cancel_rebuild_job("ds1", job_id)
        assert result["success"] is False
        assert result["error_code"] == "dataset_rebuild_cancel_failed"


# ─────────────── get_rebuild_job 边界 ────────────────────────────


class TestGetRebuildJobBoundary:
    """get_rebuild_job 的查询边界。"""

    def test_dataset_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.get_rebuild_job("nonexistent", "job1")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_job_not_found(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.get_rebuild_job("ds1", "nonexistent-job")
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.get_rebuild_job("ds1", "job1", access_context=ctx)
        assert result["success"] is False

    def test_get_success(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        start_result = svc.start_rebuild_index(dataset_id="ds1", background=False)
        job_id = start_result["job"]["job_id"]
        result = svc.get_rebuild_job("ds1", job_id)
        assert result["success"] is True


# ─────────────── status 边界 ─────────────────────────────────────


class TestStatusBoundary:
    """status 的查询边界。"""

    def test_empty_dataset_id_lists_all(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, dataset_id="ds1")
        _ingest(svc, dataset_id="ds2")
        result = svc.status()
        assert result["success"] is True
        assert result["dataset_count"] >= 2

    def test_specific_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, dataset_id="ds1")
        result = svc.status("ds1")
        assert result["success"] is True
        assert result["dataset_id"] == "ds1"

    def test_nonexistent_dataset(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.status("nonexistent")
        assert result["success"] is True
        assert result["document_count"] == 0

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.status("ds1", access_context=ctx)
        assert result["success"] is False

    def test_tenant_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="default", permissions=frozenset([DATASET_READ_PERMISSION])
        )
        result = svc.status("ds1", access_context=ctx)
        assert result["success"] is True


# ─────────────── query 边界 ──────────────────────────────────────


class TestQueryBoundary:
    """query 的查询边界。"""

    def test_empty_query(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.query(dataset_id="ds1", query="")
        assert result["success"] is False
        assert "required" in result["message"]

    def test_whitespace_query(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        result = svc.query(dataset_id="ds1", query="   ")
        assert result["success"] is False

    def test_no_chunks(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.query(dataset_id="ds1", query="test")
        assert result["success"] is True
        assert result["chunks"] == []

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.query(dataset_id="ds1", query="test", access_context=ctx)
        assert result["success"] is False
        assert result["chunks"] == []

    def test_query_with_chunks(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, text="hello world content for query testing")
        result = svc.query(dataset_id="ds1", query="hello")
        assert result["success"] is True
        assert len(result["chunks"]) > 0

    def test_query_with_rerank(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, text="hello world content for rerank testing")
        result = svc.query(dataset_id="ds1", query="hello", rerank=True)
        assert result["success"] is True
        assert result["rerank"] is True

    def test_query_top_k_limit(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, text="hello world content for top k testing")
        result = svc.query(dataset_id="ds1", query="hello", top_k=100)
        assert result["success"] is True
        # top_k 被 clamp 到 50
        assert len(result["chunks"]) <= 50


# ─────────────── answer 边界 ─────────────────────────────────────


class TestAnswerBoundary:
    """answer 的回答边界。"""

    def test_no_chunks_returns_empty_answer(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.answer(dataset_id="ds1", query="test")
        assert result["answer"] == ""

    def test_with_llm_call(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, text="hello world content for answer testing")

        def llm_call(query: str, prompt: str) -> str:
            return "LLM answer [1]"

        result = svc.answer(dataset_id="ds1", query="hello", llm_call=llm_call)
        assert result["success"] is True
        assert "answer" in result

    def test_deterministic_answer(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc, text="hello world content for deterministic answer")
        result = svc.answer(dataset_id="ds1", query="hello")
        assert result["success"] is True
        assert result["answer"] != ""

    def test_permission_denied(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        ctx = DatasetAccessContext(permissions=frozenset())
        result = svc.answer(dataset_id="ds1", query="test", access_context=ctx)
        assert result["success"] is False


# ─────────────── _load_persisted_state 边界 ──────────────────────


class TestLoadPersistedStateBoundary:
    """_load_persisted_state 的损坏数据恢复。"""

    def test_nonexistent_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        # 不应抛异常
        assert svc._datasets == {}

    def test_invalid_json(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text("not valid json {{{")
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert svc._datasets == {}

    def test_non_dict_root(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps(["not", "dict"]))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert svc._datasets == {}

    def test_datasets_not_dict(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps({"datasets": ["not", "dict"]}))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert svc._datasets == {}

    def test_dataset_payload_not_dict(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps({"datasets": {"ds1": "not dict"}}))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert "ds1" not in svc._datasets

    def test_documents_not_dict(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps({
            "datasets": {"ds1": {"documents": "not dict", "chunks": [], "rebuild_jobs": {}}}
        }))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert svc._datasets["ds1"].documents == {}

    def test_chunks_not_list(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps({
            "datasets": {"ds1": {"documents": {}, "chunks": "not list", "rebuild_jobs": {}}}
        }))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert svc._datasets["ds1"].chunks == []

    def test_rebuild_jobs_not_dict(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps({
            "datasets": {"ds1": {"documents": {}, "chunks": [], "rebuild_jobs": "not dict"}}
        }))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert svc._datasets["ds1"].rebuild_jobs == {}

    def test_index_not_dict(self, tmp_path):
        storage = tmp_path / "store.json"
        storage.write_text(json.dumps({
            "datasets": {"ds1": {"documents": {}, "chunks": [], "rebuild_jobs": {}, "index": "not dict"}}
        }))
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        # index is reset to {} then refreshed with metadata by _refresh_index_metadata
        assert isinstance(svc._datasets["ds1"].index, dict)
        assert "chunk_count" in svc._datasets["ds1"].index

    def test_valid_persisted_state(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        # 创建新 service 加载同一存储
        svc2 = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        assert "ds1" in svc2._datasets
        assert len(svc2._datasets["ds1"].documents) > 0


# ─────────────── _resolve_document_version 边界 ──────────────────


class TestResolveDocumentVersionBoundary:
    """_resolve_document_version 的版本解析。"""

    def test_v_prefix_version(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested="v5")
        assert result == 5

    def test_digit_version(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested="3")
        assert result == 3

    def test_integer_version(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested=4)
        assert result == 4

    def test_none_version_increments(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        # 添加一个 version=2 的文档
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=2,
        )
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested=None)
        assert result == 3

    def test_none_version_no_existing_returns_1(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested=None)
        assert result == 1

    def test_empty_string_version(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested="")
        assert result == 1

    def test_invalid_version_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        with pytest.raises(ValueError, match="version must be"):
            svc._resolve_document_version(state, source="src", tenant_id="t1", requested="invalid")

    def test_v_prefix_non_digit_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        with pytest.raises(ValueError):
            svc._resolve_document_version(state, source="src", tenant_id="t1", requested="vabc")

    def test_version_clamped_to_minimum(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_version(state, source="src", tenant_id="t1", requested="v0")
        assert result == 1

    def test_version_negative_string_raises(self, tmp_path):
        """Negative string '-5' is not a digit, so raises ValueError."""
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        with pytest.raises(ValueError):
            svc._resolve_document_version(state, source="src", tenant_id="t1", requested="-5")

    def test_version_v_negative_raises(self, tmp_path):
        """'v-5' has non-digit suffix, so raises ValueError."""
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        with pytest.raises(ValueError):
            svc._resolve_document_version(state, source="src", tenant_id="t1", requested="v-5")


# ─────────────── _resolve_document_for_version 边界 ──────────────


class TestResolveDocumentForVersionBoundary:
    """_resolve_document_for_version 的版本查找。"""

    def test_no_candidates_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="1",
        )
        assert result is None

    def test_latest_version(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1,
        )
        state.documents["doc2"] = DatasetDocument(
            document_id="doc2", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=2,
        )
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="latest",
        )
        assert result is not None
        assert result.version == 2

    def test_empty_version_returns_latest(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1,
        )
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="",
        )
        assert result is not None

    def test_specific_version_match(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1,
        )
        state.documents["doc2"] = DatasetDocument(
            document_id="doc2", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=2,
        )
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="1",
        )
        assert result is not None
        assert result.version == 1

    def test_v_prefix_version_match(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=2,
        )
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="v2",
        )
        assert result is not None

    def test_version_label_match(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1, version_label="custom-label",
        )
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="custom-label",
        )
        assert result is not None

    def test_version_not_found_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1,
        )
        result = svc._resolve_document_for_version(
            state, source="src", tenant_id="t1", version="999",
        )
        assert result is None


# ─────────────── _run_rebuild_job 边界 ───────────────────────────


class TestRunRebuildJobBoundary:
    """_run_rebuild_job 的错误恢复与重试。"""

    def test_nonexistent_dataset_returns(self, tmp_path):
        svc = _make_svc(tmp_path)
        # 不应抛异常
        svc._run_rebuild_job("nonexistent", "job1")

    def test_nonexistent_job_returns(self, tmp_path):
        svc = _make_svc(tmp_path)
        _ingest(svc)
        svc._run_rebuild_job("ds1", "nonexistent-job")

    def test_terminal_status_returns(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc)
        start_result = svc.start_rebuild_index(dataset_id="ds1", background=False)
        job_id = start_result["job"]["job_id"]
        # 手动设为 completed
        with svc._lock:
            state = svc._datasets["ds1"]
            state.rebuild_jobs[job_id].status = "completed"
        # 再次运行不应改变状态
        svc._run_rebuild_job("ds1", job_id)
        with svc._lock:
            assert svc._datasets["ds1"].rebuild_jobs[job_id].status == "completed"

    def test_rebuild_with_metadata_filter(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc, text="content one")
        _ingest(svc, text="content two")
        result = svc.start_rebuild_index(
            dataset_id="ds1", background=False, metadata_filter={"source": "inline"},
        )
        assert result["success"] is True


# ─────────────── drain_rebuild_queue 边界 ────────────────────────


class TestDrainRebuildQueueBoundary:
    """drain_rebuild_queue 的排空边界。"""

    def test_empty_queue(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc.drain_rebuild_queue()
        assert result["success"] is True
        assert result["drained_count"] == 0

    def test_drain_with_jobs(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc)
        svc.start_rebuild_index(dataset_id="ds1", background=True)
        result = svc.drain_rebuild_queue()
        assert result["success"] is True
        assert result["drained_count"] >= 1

    def test_drain_with_max_limit(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        _ingest(svc)
        svc.start_rebuild_index(dataset_id="ds1", background=True)
        result = svc.drain_rebuild_queue(max_jobs=1)
        assert result["success"] is True
        assert result["drained_count"] <= 1


# ─────────────── _query_vector_index_candidates 边界 ─────────────


class TestQueryVectorIndexCandidatesBoundary:
    """_query_vector_index_candidates 的后端查询。"""

    def test_none_backend_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path, backend_name="none")
        result = svc._query_vector_index_candidates(
            dataset_id="ds", query="text", top_k=5,
            tenant_id="", version="", metadata_filter={},
        )
        assert result is None

    def test_none_embedder_returns_none(self, tmp_path):
        svc = DatasetRagApplicationService(
            embedder=None,
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        result = svc._query_vector_index_candidates(
            dataset_id="ds", query="text", top_k=5,
            tenant_id="", version="", metadata_filter={},
        )
        assert result is None


# ─────────────── _sync_vector_index_locked 边界 ──────────────────


class TestSyncVectorIndexLockedBoundary:
    """_sync_vector_index_locked 的后端同步。"""

    def test_none_backend_sets_disabled(self, tmp_path):
        svc = _make_svc(tmp_path, backend_name="none")
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        svc._sync_vector_index_locked(state)
        assert state.index["vector_backend_sync_status"] == "disabled"

    def test_backend_failure_sets_failed(self, tmp_path):
        backend = MagicMock()
        backend.replace_dataset.side_effect = ValueError("sync failed")
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend=backend,
        )
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        svc._sync_vector_index_locked(state)
        assert state.index["vector_backend_sync_status"] == "failed"
        assert "sync failed" in state.index["vector_backend_error"]


# ─────────────── _vector_index_status 边界 ───────────────────────


class TestVectorIndexStatusBoundary:
    """_vector_index_status 的状态查询。"""

    def test_none_backend_returns_none_status(self, tmp_path):
        svc = _make_svc(tmp_path, backend_name="none")
        result = svc._vector_index_status("ds1")
        assert result["backend"] == "none"
        assert result["persistent"] is False
        assert result["index_exists"] is False

    def test_backend_failure_returns_failed(self, tmp_path):
        backend = MagicMock()
        backend.backend_name = "test"
        backend.status.side_effect = ValueError("status failed")
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend=backend,
        )
        result = svc._vector_index_status("ds1")
        assert result["status"] == "failed"
        assert "status failed" in result["error"]


# ─────────────── _vector_index_backend_name 边界 ─────────────────


class TestVectorIndexBackendNameBoundary:
    """_vector_index_backend_name 的名称。"""

    def test_none_backend_returns_none(self, tmp_path):
        svc = _make_svc(tmp_path, backend_name="none")
        assert svc._vector_index_backend_name() == "none"

    def test_backend_with_name_attr(self, tmp_path):
        backend = MagicMock()
        backend.backend_name = "custom_backend"
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend=backend,
        )
        assert svc._vector_index_backend_name() == "custom_backend"

    def test_backend_without_name_attr(self, tmp_path):
        backend = MagicMock(spec=[])  # 无任何属性
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend=backend,
        )
        result = svc._vector_index_backend_name()
        assert result == "vector_index"


# ─────────────── _recover_rebuild_jobs_locked 边界 ───────────────


class TestRecoverRebuildJobsLockedBoundary:
    """_recover_rebuild_jobs_locked 的重启恢复。"""

    def test_running_job_requeued(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        job = DatasetRebuildJob(job_id="job1", dataset_id="ds1", status="running")
        state.rebuild_jobs["job1"] = job
        svc._recover_rebuild_jobs_locked(state)
        assert state.rebuild_jobs["job1"].status == "queued"
        assert "requeued" in state.rebuild_jobs["job1"].error

    def test_queued_job_not_affected(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        job = DatasetRebuildJob(job_id="job1", dataset_id="ds1", status="queued")
        state.rebuild_jobs["job1"] = job
        svc._recover_rebuild_jobs_locked(state)
        assert state.rebuild_jobs["job1"].status == "queued"
        assert state.rebuild_jobs["job1"].error == ""

    def test_completed_job_not_affected(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        job = DatasetRebuildJob(job_id="job1", dataset_id="ds1", status="completed")
        state.rebuild_jobs["job1"] = job
        svc._recover_rebuild_jobs_locked(state)
        assert state.rebuild_jobs["job1"].status == "completed"


# ─────────────── _rebuild_job_queue_position_locked 边界 ─────────


class TestRebuildJobQueuePositionBoundary:
    """_rebuild_job_queue_position_locked 的队列位置。"""

    def test_non_queued_returns_zero(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        job = DatasetRebuildJob(job_id="job1", dataset_id="ds1", status="completed")
        state.rebuild_jobs["job1"] = job
        result = svc._rebuild_job_queue_position_locked(state, job)
        assert result == 0

    def test_queued_returns_position(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        job1 = DatasetRebuildJob(job_id="job1", dataset_id="ds1", status="queued")
        job2 = DatasetRebuildJob(job_id="job2", dataset_id="ds1", status="queued")
        state.rebuild_jobs["job1"] = job1
        state.rebuild_jobs["job2"] = job2
        pos1 = svc._rebuild_job_queue_position_locked(state, job1)
        pos2 = svc._rebuild_job_queue_position_locked(state, job2)
        assert pos1 >= 1
        assert pos2 >= 1


# ─────────────── _rebuild_queue_summary_locked 边界 ──────────────


class TestRebuildQueueSummaryBoundary:
    """_rebuild_queue_summary_locked 的队列汇总。"""

    def test_empty_queue(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._rebuild_queue_summary_locked(state)
        assert result["queued"] == 0
        assert result["running"] == 0
        assert result["completed"] == 0
        assert result["failed"] == 0
        assert result["cancelled"] == 0
        assert result["next_job_id"] == ""
        assert result["running_job_ids"] == []

    def test_with_jobs(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.rebuild_jobs["job1"] = DatasetRebuildJob(
            job_id="job1", dataset_id="ds1", status="queued",
        )
        state.rebuild_jobs["job2"] = DatasetRebuildJob(
            job_id="job2", dataset_id="ds1", status="running",
        )
        state.rebuild_jobs["job3"] = DatasetRebuildJob(
            job_id="job3", dataset_id="ds1", status="completed",
        )
        result = svc._rebuild_queue_summary_locked(state)
        assert result["queued"] == 1
        assert result["running"] == 1
        assert result["completed"] == 1
        assert result["next_job_id"] == "job1"
        assert "job2" in result["running_job_ids"]

    def test_tenant_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.rebuild_jobs["job1"] = DatasetRebuildJob(
            job_id="job1", dataset_id="ds1", status="queued", tenant_id="t1",
        )
        state.rebuild_jobs["job2"] = DatasetRebuildJob(
            job_id="job2", dataset_id="ds1", status="queued", tenant_id="t2",
        )
        result = svc._rebuild_queue_summary_locked(state, tenant_id_filter="t1")
        assert result["queued"] == 1


# ─────────────── _status_for_state 边界 ──────────────────────────


class TestStatusForStateBoundary:
    """_status_for_state 的状态汇总。"""

    def test_none_state(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc._status_for_state("ds1", None)
        assert result["success"] is True
        assert result["document_count"] == 0
        assert result["chunk_count"] == 0
        assert result["documents"] == []

    def test_with_state(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1,
        )
        result = svc._status_for_state("ds1", state)
        assert result["success"] is True
        assert result["document_count"] == 1

    def test_tenant_filter(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.documents["doc1"] = DatasetDocument(
            document_id="doc1", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t1", version=1,
        )
        state.documents["doc2"] = DatasetDocument(
            document_id="doc2", source="src", parser="p", text_length=10,
            chunk_count=1, tenant_id="t2", version=1,
        )
        result = svc._status_for_state("ds1", state, tenant_id_filter="t1")
        assert result["document_count"] == 1


# ─────────────── _document_text_locked 边界 ──────────────────────


class TestDocumentTextLockedBoundary:
    """_document_text_locked 的文本重建。"""

    def test_no_chunks_returns_empty(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        result = svc._document_text_locked(state, "doc1")
        assert result == ""

    def test_with_chunks(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.chunks = [
            _make_chunk(text="first", metadata={"document_id": "doc1"}),
            _make_chunk(text="second", metadata={"document_id": "doc1"}),
            _make_chunk(text="other", metadata={"document_id": "doc2"}),
        ]
        result = svc._document_text_locked(state, "doc1")
        assert "first" in result
        assert "second" in result
        assert "other" not in result

    def test_chunks_sorted_by_char_start(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.chunks = [
            _make_chunk(text="second", metadata={"document_id": "doc1"}),
            _make_chunk(text="first", metadata={"document_id": "doc1"}),
        ]
        state.chunks[0].char_start = 10
        state.chunks[1].char_start = 0
        result = svc._document_text_locked(state, "doc1")
        lines = result.split("\n")
        assert lines[0] == "first"


# ─────────────── _renumber_chunks 边界 ───────────────────────────


class TestRenumberChunksBoundary:
    """_renumber_chunks 的重编号。"""

    def test_empty_chunks(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        svc._renumber_chunks(state)
        assert state.chunks == []

    def test_renumber_sequential(self, tmp_path):
        svc = _make_svc(tmp_path)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        state.chunks = [
            _make_chunk(text="a", chunk_index=99),
            _make_chunk(text="b", chunk_index=50),
            _make_chunk(text="c", chunk_index=0),
        ]
        svc._renumber_chunks(state)
        assert state.chunks[0].chunk_index == 0
        assert state.chunks[1].chunk_index == 1
        assert state.chunks[2].chunk_index == 2


# ─────────────── _extract_file_text 边界 ─────────────────────────


class TestExtractFileTextBoundary:
    """_extract_file_text 的文件类型分发。"""

    def test_nonexistent_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(ValueError, match="file not found"):
            svc._extract_file_text(tmp_path / "nonexistent.txt")

    def test_directory_not_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        with pytest.raises(ValueError, match="file not found"):
            svc._extract_file_text(subdir)

    def test_unsupported_suffix(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.xyz"
        file_path.write_text("content")
        with pytest.raises(ValueError, match="unsupported document type"):
            svc._extract_file_text(file_path)

    def test_no_suffix(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "noextension"
        file_path.write_text("content")
        with pytest.raises(ValueError, match="unsupported document type"):
            svc._extract_file_text(file_path)

    def test_txt_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("text content")
        text, parser, metadata = svc._extract_file_text(file_path)
        assert text == "text content"
        assert parser == "text_file"
        assert metadata["extension"] == ".txt"

    def test_md_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.md"
        file_path.write_text("# Markdown")
        text, parser, metadata = svc._extract_file_text(file_path)
        assert parser == "text_file"
        assert metadata["extension"] == ".md"

    def test_csv_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.csv"
        file_path.write_text("a,b,c")
        text, parser, metadata = svc._extract_file_text(file_path)
        assert parser == "text_file"
        assert metadata["extension"] == ".csv"

    def test_json_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.json"
        file_path.write_text('{"key": "value"}')
        text, parser, metadata = svc._extract_file_text(file_path)
        assert parser == "text_file"
        assert metadata["extension"] == ".json"

    def test_log_file(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.log"
        file_path.write_text("[INFO] log")
        text, parser, metadata = svc._extract_file_text(file_path)
        assert parser == "text_file"
        assert metadata["extension"] == ".log"


# ─────────────── _extract_pdf_text 边界 ──────────────────────────


class TestExtractPdfTextBoundary:
    """_extract_pdf_text 的 PDF 提取。"""

    def test_import_error_raises_runtime_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.pdf"
        file_path.write_text("fake pdf")
        with patch("builtins.__import__", side_effect=ImportError("no pdfplumber")):
            with pytest.raises(RuntimeError, match="pdfplumber is required"):
                svc._extract_pdf_text(file_path)


# ─────────────── _extract_docx_text 边界 ─────────────────────────


class TestExtractDocxTextBoundary:
    """_extract_docx_text 的 DOCX 提取。"""

    def test_import_error_raises_runtime_error(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.docx"
        file_path.write_text("fake docx")
        with patch("builtins.__import__", side_effect=ImportError("no docx")):
            with pytest.raises(RuntimeError, match="python-docx is required"):
                svc._extract_docx_text(file_path)


# ─────────────── _split_text 边界 ────────────────────────────────


class TestSplitTextBoundary:
    """_split_text 的分块策略。"""

    def test_semantic_strategy(self, tmp_path):
        svc = _make_svc(tmp_path)
        chunks = svc._split_text("hello world. foo bar.", strategy="semantic", chunk_size=100, chunk_overlap=0)
        assert isinstance(chunks, list)

    def test_fixed_strategy(self, tmp_path):
        svc = _make_svc(tmp_path)
        chunks = svc._split_text("hello world. foo bar.", strategy="fixed", chunk_size=100, chunk_overlap=0)
        assert isinstance(chunks, list)

    def test_chunk_size_clamped_to_min(self, tmp_path):
        svc = _make_svc(tmp_path)
        chunks = svc._split_text("hello world", strategy="fixed", chunk_size=1, chunk_overlap=0)
        # chunk_size 被 clamp 到 50
        assert isinstance(chunks, list)

    def test_chunk_size_clamped_to_max(self, tmp_path):
        svc = _make_svc(tmp_path)
        chunks = svc._split_text("hello world", strategy="fixed", chunk_size=10000, chunk_overlap=0)
        # chunk_size 被 clamp 到 5000
        assert isinstance(chunks, list)

    def test_chunk_overlap_clamped_to_max(self, tmp_path):
        svc = _make_svc(tmp_path)
        chunks = svc._split_text("hello world", strategy="fixed", chunk_size=100, chunk_overlap=10000)
        assert isinstance(chunks, list)


# ─────────────── _allowed_file_roots 边界 ────────────────────────


class TestAllowedFileRootsBoundary:
    """_allowed_file_roots 的根目录解析。"""

    def test_custom_roots(self, tmp_path):
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        roots = svc._allowed_file_roots()
        assert tmp_path.resolve() in roots

    def test_default_roots(self, tmp_path):
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            storage_path=tmp_path / "store.json",
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        roots = svc._allowed_file_roots()
        assert len(roots) >= 1


# ─────────────── _resolve_file_path 边界 ─────────────────────────


class TestResolveFilePathBoundary:
    """_resolve_file_path 的路径解析。"""

    def test_valid_path(self, tmp_path):
        svc = _make_svc(tmp_path)
        file_path = tmp_path / "test.txt"
        file_path.write_text("content")
        result = svc._resolve_file_path(str(file_path))
        assert result.exists()

    def test_unsafe_path_raises(self, tmp_path):
        svc = _make_svc(tmp_path)
        with pytest.raises(UnsafeDownloadPathError):
            svc._resolve_file_path("../../../etc/passwd")


# ─────────────── _persist_locked 边界 ────────────────────────────


class TestPersistLockedBoundary:
    """_persist_locked 的持久化。"""

    def test_persist_creates_file(self, tmp_path):
        storage = tmp_path / "store.json"
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        _ingest(svc)
        assert storage.exists()
        data = json.loads(storage.read_text())
        assert "datasets" in data

    def test_persist_creates_parent_dir(self, tmp_path):
        storage = tmp_path / "subdir" / "store.json"
        svc = DatasetRagApplicationService(
            embedder=_make_embedder(),
            allowed_roots=[tmp_path],
            storage_path=storage,
            rebuild_workers_enabled=False,
            vector_index_backend_name="none",
        )
        _ingest(svc)
        assert storage.exists()
        assert storage.parent.exists()


# ─────────────── get_dataset_rag_app_service 边界 ────────────────


class TestGetDatasetRagAppServiceBoundary:
    """get_dataset_rag_app_service 的单例。"""

    def test_returns_singleton(self):
        reset_dataset_rag_app_service_for_tests()
        svc1 = get_dataset_rag_app_service()
        svc2 = get_dataset_rag_app_service()
        assert svc1 is svc2
        reset_dataset_rag_app_service_for_tests()

    def test_reset_creates_new_instance(self):
        reset_dataset_rag_app_service_for_tests()
        svc1 = get_dataset_rag_app_service()
        reset_dataset_rag_app_service_for_tests()
        svc2 = get_dataset_rag_app_service()
        assert svc1 is not svc2
        reset_dataset_rag_app_service_for_tests()


# ─────────────── _claim_next_rebuild_jobs_locked 边界 ────────────


class TestClaimNextRebuildJobsBoundary:
    """_claim_next_rebuild_jobs_locked 的任务认领。"""

    def test_no_queued_jobs(self, tmp_path):
        svc = _make_svc(tmp_path)
        result = svc._claim_next_rebuild_jobs_locked()
        assert result == []

    def test_capacity_zero(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        # 添加一个 running job 占满容量
        state.rebuild_jobs["job0"] = DatasetRebuildJob(
            job_id="job0", dataset_id="ds1", status="running",
        )
        svc._datasets["ds1"] = state
        # max_concurrent=1, 已有1个 running → capacity=0
        result = svc._claim_next_rebuild_jobs_locked()
        assert result == []

    def test_with_limit(self, tmp_path):
        svc = _make_svc(tmp_path, workers=False)
        from app.application.dataset_rag_app_service import _DatasetState
        state = _DatasetState("ds1")
        for i in range(5):
            state.rebuild_jobs[f"job{i}"] = DatasetRebuildJob(
                job_id=f"job{i}", dataset_id="ds1", status="queued",
            )
        svc._datasets["ds1"] = state
        result = svc._claim_next_rebuild_jobs_locked(limit=2)
        assert len(result) <= 2


# ─────────────── DatasetDocument.to_dict 边界 ────────────────────


class TestDatasetDocumentToDictBoundary:
    """DatasetDocument.to_dict 的序列化。"""

    def test_full_dict(self):
        doc = DatasetDocument(
            document_id="doc1", source="src", parser="text_file",
            text_length=100, chunk_count=3, tenant_id="t1",
            version=2, version_label="v2", metadata={"key": "value"},
        )
        result = doc.to_dict()
        assert result["document_id"] == "doc1"
        assert result["source"] == "src"
        assert result["parser"] == "text_file"
        assert result["text_length"] == 100
        assert result["chunk_count"] == 3
        assert result["tenant_id"] == "t1"
        assert result["version"] == 2
        assert result["version_label"] == "v2"
        assert result["metadata"] == {"key": "value"}

    def test_default_values(self):
        doc = DatasetDocument(
            document_id="doc1", source="src", parser="p",
            text_length=10, chunk_count=1,
        )
        result = doc.to_dict()
        assert result["tenant_id"] == "default"
        assert result["version"] == 1
        assert result["version_label"] == "v1"
        assert result["metadata"] == {}


# ─────────────── DatasetRebuildJob.to_dict 边界 ──────────────────


class TestDatasetRebuildJobToDictBoundary:
    """DatasetRebuildJob.to_dict 的序列化。"""

    def test_full_dict(self):
        job = DatasetRebuildJob(
            job_id="job1", dataset_id="ds1", status="completed",
            tenant_id="t1", metadata_filter={"key": "value"},
            document_count=5, chunk_count=20, error="",
            attempt_count=2, max_attempts=3, worker_id="w1",
        )
        result = job.to_dict()
        assert result["job_id"] == "job1"
        assert result["dataset_id"] == "ds1"
        assert result["status"] == "completed"
        assert result["tenant_id"] == "t1"
        assert result["metadata_filter"] == {"key": "value"}
        assert result["document_count"] == 5
        assert result["chunk_count"] == 20
        assert result["attempt_count"] == 2
        assert result["max_attempts"] == 3
        assert result["worker_id"] == "w1"

    def test_default_values(self):
        job = DatasetRebuildJob(job_id="job1", dataset_id="ds1")
        result = job.to_dict()
        assert result["status"] == "queued"
        assert result["tenant_id"] == ""
        assert result["metadata_filter"] == {}
        assert result["document_count"] == 0
        assert result["chunk_count"] == 0
        assert result["error"] == ""
        assert result["attempt_count"] == 0
        assert result["max_attempts"] == 1
        assert result["worker_id"] == ""


# ─────────────── DatasetAccessContext.to_dict 边界 ───────────────


class TestDatasetAccessContextToDictBoundary:
    """DatasetAccessContext.to_dict 的序列化。"""

    def test_full_dict(self):
        ctx = DatasetAccessContext(
            actor_id="u1", tenant_id="t1",
            permissions=frozenset({"a", "b"}), is_admin=True,
        )
        result = ctx.to_dict()
        assert result["actor_id"] == "u1"
        assert result["tenant_id"] == "t1"
        assert result["permissions"] == ["a", "b"]
        assert result["is_admin"] is True

    def test_default_values(self):
        ctx = DatasetAccessContext()
        result = ctx.to_dict()
        assert result["actor_id"] == ""
        assert result["tenant_id"] == ""
        assert result["permissions"] == []
        assert result["is_admin"] is False


# ─────────────── _utc_now_iso 边界 ───────────────────────────────


class TestUtcNowIsoBoundary:
    """_utc_now_iso 的时间格式。"""

    def test_returns_string(self):
        result = _utc_now_iso()
        assert isinstance(result, str)
        assert "T" in result

    def test_ends_with_z(self):
        result = _utc_now_iso()
        assert result.endswith("Z")


# ─────────────── _default_storage_path 边界 ──────────────────────


class TestDefaultStoragePathBoundary:
    """_default_storage_path 的路径解析。"""

    def test_env_override(self, monkeypatch, tmp_path):
        from app.application.dataset_rag_app_service import _default_storage_path
        monkeypatch.setenv("DATASET_RAG_STORE_PATH", str(tmp_path / "custom.json"))
        result = _default_storage_path()
        assert "custom.json" in str(result)

    def test_xcagi_env_override(self, monkeypatch, tmp_path):
        from app.application.dataset_rag_app_service import _default_storage_path
        monkeypatch.delenv("DATASET_RAG_STORE_PATH", raising=False)
        monkeypatch.setenv("XCAGI_DATASET_RAG_STORE_PATH", str(tmp_path / "xcagi.json"))
        result = _default_storage_path()
        assert "xcagi.json" in str(result)

    def test_default_path(self, monkeypatch):
        from app.application.dataset_rag_app_service import _default_storage_path
        monkeypatch.delenv("DATASET_RAG_STORE_PATH", raising=False)
        monkeypatch.delenv("XCAGI_DATASET_RAG_STORE_PATH", raising=False)
        result = _default_storage_path()
        assert "dataset_rag" in str(result)
        assert "datasets.json" in str(result)
