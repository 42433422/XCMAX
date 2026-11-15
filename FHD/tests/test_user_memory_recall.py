"""写入去重与检索打分的回归用例（使用 tmp_path 隔离的记忆快照）。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.application.user_memory.retrieve import (
    build_memory_context,
    score_memory,
    search,
)
from app.application.user_memory.write import normalize_memory_text, remember


@pytest.fixture
def memory_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[Any, Path]]:
    """把用户记忆快照重定向到 tmp_path，返回真实存储与 JSON 路径。"""
    from app.domain.shared_services import user_memory_service as module

    json_path = tmp_path / "memory_store.json"
    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(tmp_path))
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(json_path))
    module.reset_user_memory_service()
    module.UserMemoryService._instance = None
    module.UserMemoryStore._instance = None
    store = module.UserMemoryStore(storage_type="json")
    yield store, json_path
    module.reset_user_memory_service()
    module.UserMemoryService._instance = None
    module.UserMemoryStore._instance = None


def _age_record(store: Any, owner: str, record_id: str, *, days: int, importance: float) -> None:
    memory = store.get_memory(owner)
    for record in memory.recall_facts:
        if record["id"] == record_id:
            record["updated_at"] = (datetime.now() - timedelta(days=days)).isoformat()
            record["importance"] = importance
    store.save_memory(owner, memory)


def test_remember_merges_duplicate_fact(memory_store: tuple[Any, Path]) -> None:
    store, json_path = memory_store
    first = remember("  我喜欢蓝色   咖啡 ", scope="chat", owner_id="alice", store=store)
    second = remember("我喜欢蓝色 咖啡", scope="chat", owner_id="alice", store=store)

    assert first["created"] is True
    assert first["merged"] is False
    assert second["created"] is False
    assert second["merged"] is True
    assert first["id"] == second["id"]

    facts = store.get_memory("alice").recall_facts
    assert len(facts) == 1
    assert facts[0]["hits"] == 2
    assert facts[0]["importance"] == pytest.approx(0.55)

    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(persisted["alice"]["recall_facts"]) == 1
    assert persisted["alice"]["recall_facts"][0]["hits"] == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  你好   世界  ", "你好 世界"),
        ("好的，收到！", "好的,收到"),
        ("我喜欢喝咖啡呢。", "我喜欢喝咖啡"),
        ("（重要）请记得呢", "(重要)请记得"),
    ],
)
def test_normalize_memory_text(raw: str, expected: str) -> None:
    assert normalize_memory_text(raw) == expected


def test_remember_truncates_long_text(memory_store: tuple[Any, Path]) -> None:
    store, _ = memory_store
    result = remember("超" * 600, scope="chat", owner_id="bob", store=store)

    assert result["truncated"] is True
    record = store.get_memory("bob").recall_facts[0]
    assert len(record["text"]) == 500
    assert record["truncated"] is True


def test_search_ranks_and_filters(memory_store: tuple[Any, Path]) -> None:
    store, _ = memory_store
    old = remember("客户偏好蓝色包装", scope="chat", owner_id="alice", importance=0.2, store=store)
    fresh = remember(
        "客户要求下周交付蓝色样品", scope="chat", owner_id="alice", importance=0.9, store=store
    )
    unrelated = remember("仓库温度记录", scope="chat", owner_id="alice", importance=0.1, store=store)
    _age_record(store, "alice", old["id"], days=120, importance=0.2)
    _age_record(store, "alice", unrelated["id"], days=120, importance=0.1)

    hits = search("蓝色样品交付", scope="chat", owner_id="alice", store=store)
    assert hits[0]["id"] == fresh["id"]
    assert all(hit["id"] != unrelated["id"] for hit in hits)
    assert set(hits[0]) == {"id", "text", "score", "importance", "updated_at"}

    unrelated_record = next(
        record
        for record in store.get_memory("alice").recall_facts
        if record["id"] == unrelated["id"]
    )
    assert score_memory("蓝色样品交付", unrelated_record) < 0.05
    strict = search("蓝色样品交付", scope="chat", owner_id="alice", min_score=0.5, store=store)
    assert [hit["id"] for hit in strict] == [fresh["id"]]


def test_search_isolates_scope_and_owner(memory_store: tuple[Any, Path]) -> None:
    store, _ = memory_store
    remember("我是蓝色偏好", scope="chat", owner_id="alice", store=store)

    assert search("蓝色", scope="profile", owner_id="alice", store=store) == []
    assert search("蓝色", scope="chat", owner_id="bob", store=store) == []


def test_build_memory_context_truncates(memory_store: tuple[Any, Path]) -> None:
    store, _ = memory_store
    remember("客户喜欢蓝色包装", scope="chat", owner_id="alice", store=store)

    context = build_memory_context("蓝色包装", scope="chat", owner_id="alice", max_chars=10, store=store)
    assert context
    assert len(context) <= 10

    full = build_memory_context("蓝色包装", scope="chat", owner_id="alice", store=store)
    assert "客户喜欢蓝色包装" in full


def test_build_memory_context_empty_without_hits(memory_store: tuple[Any, Path]) -> None:
    store, _ = memory_store
    remember("客户喜欢蓝色包装", scope="chat", owner_id="alice", store=store)

    assert build_memory_context("蓝色", scope="profile", owner_id="alice", store=store) == ""
    assert build_memory_context("蓝色", scope="chat", owner_id="carol", store=store) == ""
