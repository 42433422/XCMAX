"""Mem0 is a projection of confirmed authority, never a raw-turn bypass."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.infrastructure.llm.embedding_service import EmbeddingService
from app.infrastructure.memory import mem0_backend
from tests.fixtures.governed_memory_runtime import governed_memory as governed_memory
from tests.fixtures.governed_memory_runtime import owner_id

_HAS_MEM0 = importlib.util.find_spec("mem0") is not None and (
    importlib.util.find_spec("qdrant_client") is not None
)


@pytest.fixture
def backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_DIR", str(tmp_path / "ltm"))
    monkeypatch.setenv("FHD_EMBEDDING_MODE", "hash")
    EmbeddingService.reset_singleton_for_tests()
    mem0_backend.reset_long_term_memory_for_tests()
    service = mem0_backend.get_long_term_memory()
    yield service
    service.close()
    mem0_backend.reset_long_term_memory_for_tests()
    EmbeddingService.reset_singleton_for_tests()


@pytest.mark.skipif(not _HAS_MEM0, reason="mem0 未安装")
def test_confirmed_authority_is_recalled_across_sessions(governed_memory) -> None:
    from app.application.agent_task_context import scoped_personal_memory_id

    runtime = governed_memory
    candidate = runtime.propose("客户张三的木门单价为二百元", key="customer.price")
    assert runtime.backend.recall(user_id=owner_id(), query="张三 单价", limit=3) == []
    record = runtime.confirm(candidate)
    later_owner = scoped_personal_memory_id(
        {"local_user_id": 7, "tenant_id": 2, "mod_id": "sales", "session_id": "later-session"}
    )
    assert later_owner == owner_id()
    hits = runtime.backend.recall(user_id=later_owner, query="张三 单价", limit=3)
    assert hits
    assert "张三" in hits[0]["content"]
    assert hits[0]["metadata"]["source"] == "long_term_memory"
    assert hits[0]["metadata"]["source_memory_id"] == record["memory_id"]
    assert hits[0]["metadata"]["source_revision"] == record["revision"]
    assert runtime.rag.query(later_owner, "张三 单价")["hits"]
    for foreign in (owner_id(8), owner_id(tenant=3), owner_id(mod="finance")):
        assert runtime.backend.recall(user_id=foreign, query="张三 单价", limit=3) == []
        assert runtime.rag.query(foreign, "张三 单价")["hits"] == []


def test_raw_remember_is_retained_only_as_untrusted_archive(governed_memory) -> None:
    runtime = governed_memory
    assert runtime.backend.remember(
        user_id=owner_id(),
        user_message="客户张三的单价为9999元",
        assistant_message="未确认建议",
        metadata={"session_id": "raw", "source": "chat"},
    )
    assert len(runtime.native_rows()) == 1
    assert runtime.backend.recall(user_id=owner_id(), query="张三 单价", limit=3) == []
    assert runtime.rag.query(owner_id(), "张三 单价")["hits"] == []
    assert runtime.authority.list_memories(owner_id()) == []


@pytest.mark.skipif(not _HAS_MEM0, reason="mem0 未安装")
def test_empty_input_is_ignored(backend) -> None:
    assert backend.remember(user_id="", user_message="内容", assistant_message="回复") is False
    assert backend.remember(user_id="u", user_message="", assistant_message="") is False
    assert backend.recall(user_id="u", query="", limit=3) == []


def test_legacy_backend_disables_memory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_DIR", str(tmp_path / "ltm"))
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_BACKEND", "legacy")
    mem0_backend.reset_long_term_memory_for_tests()
    service = mem0_backend.get_long_term_memory()
    try:
        assert service.enabled is False
        assert service.remember(user_id="u", user_message="a", assistant_message="b") is False
        assert service.recall(user_id="u", query="a", limit=3) == []
    finally:
        service.close()
        mem0_backend.reset_long_term_memory_for_tests()


def test_prompt_format_respects_budget() -> None:
    hits = [{"content": "片段内容" * 10, "score": 0.9} for _ in range(5)]
    prompt = mem0_backend.format_recalled_memories(hits, max_chars=200)
    assert prompt
    assert len(prompt) <= 200
    assert mem0_backend.format_recalled_memories([]) == ""


@pytest.mark.skipif(not _HAS_MEM0, reason="mem0 未安装")
def test_reset_releases_default_vector_lock_for_a_later_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跨测试重置必须关掉默认路径上的 Qdrant 锁，否则后续用例再打开会泄漏 .lock。"""
    import gc
    import warnings

    monkeypatch.setenv("FHD_EMBEDDING_MODE", "hash")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("XCAGI_LONG_TERM_MEMORY_DIR", raising=False)
    EmbeddingService.reset_singleton_for_tests()
    mem0_backend.reset_long_term_memory_for_tests()
    first = mem0_backend.get_long_term_memory()
    assert first.enabled is True

    # 模拟合并套件：切到临时目录并重置，再回到默认路径。
    monkeypatch.setenv("XCAGI_LONG_TERM_MEMORY_DIR", str(tmp_path / "ltm"))
    EmbeddingService.reset_singleton_for_tests()
    mem0_backend.reset_long_term_memory_for_tests()
    other = mem0_backend.get_long_term_memory()
    assert other.enabled is True
    other.close()
    mem0_backend.reset_long_term_memory_for_tests()

    monkeypatch.delenv("XCAGI_LONG_TERM_MEMORY_DIR", raising=False)
    EmbeddingService.reset_singleton_for_tests()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        later = mem0_backend.get_long_term_memory()
        gc.collect()
        assert later.enabled is True
        assert later._failed is False
        leaked = [str(item.message) for item in caught if "vectors/.lock" in str(item.message)]
    later.close()
    mem0_backend.reset_long_term_memory_for_tests()
    EmbeddingService.reset_singleton_for_tests()
    assert leaked == []
