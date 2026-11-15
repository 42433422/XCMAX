"""mem0 长期记忆后端：离线写入/召回与停用降级。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.infrastructure.llm.embedding_service import EmbeddingService
from app.infrastructure.memory import mem0_backend

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
def test_remember_then_recall_across_sessions(backend) -> None:
    assert backend.enabled is True
    assert backend.remember(
        user_id="owner-1",
        user_message="客户 张三 木门 订单 单价 二百元",
        assistant_message="已记录单价",
        metadata={"session_id": "s1", "source": "chat"},
    )
    hits = backend.recall(user_id="owner-1", query="张三 单价", limit=3)
    assert hits
    assert "张三" in hits[0]["content"]
    assert hits[0]["metadata"]["source"] == "long_term_memory"
    # 其他用户不可见。
    assert backend.recall(user_id="owner-2", query="张三 单价", limit=3) == []


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
