"""MemoryCacheService 单测：本地兜底缓存 + 降级队列。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.db.models.memory_graph import MemoryNodeType
from app.infrastructure.memory_cache import MemoryCacheService
from app.infrastructure.memory_graph_store import MemoryGraphStore


@pytest.fixture()
def real_app_service():
    """构造一个真实 in-memory SQLite 的 app_service，便于测 refresh/drain。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))


@pytest.fixture()
def cache(tmp_path):
    """用 tmp_path 隔离每个用例的缓存目录。"""
    return MemoryCacheService(cache_path=tmp_path / "persy-cache.json")


def test_refresh_writes_cache_file(cache, real_app_service):
    """refresh 应把 active constraint + convention 写入本地 JSON。"""
    real_app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="约束 A",
        content="A",
        scope="project",
        scope_id="XCMAX",
    )
    real_app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="约定 B",
        content="B",
        scope="project",
        scope_id="XCMAX",
    )
    real_app_service.ingest_engineering(
        type=MemoryNodeType.LESSON,
        title="教训 C",
        content="C",
        scope="project",
        scope_id="XCMAX",
    )

    count = cache.refresh(app_service=real_app_service, scope="project", scope_id="XCMAX")
    # 只缓存 constraint + convention，lesson 不算
    assert count == 2

    data = cache.load()
    assert data["persy_available"] is True
    assert "last_synced_at" in data
    assert isinstance(data["nodes"], list)
    assert len(data["nodes"]) == 2
    titles = [n["title"] for n in data["nodes"]]
    assert "约束 A" in titles
    assert "约定 B" in titles
    assert "教训 C" not in titles


def test_refresh_creates_parent_directory(tmp_path, real_app_service):
    """refresh 应自动创建父目录。"""
    nested = tmp_path / "deep" / "nested" / "persy-cache.json"
    cache = MemoryCacheService(cache_path=nested)
    count = cache.refresh(app_service=real_app_service, scope="project", scope_id="XCMAX")
    assert count == 0
    assert nested.exists()


def test_load_returns_persy_unavailable_when_no_cache(cache):
    """缓存文件不存在时 load 应返回 persy_available=False + 空节点列表。"""
    data = cache.load()
    assert data["persy_available"] is False
    assert data["nodes"] == []
    assert "last_synced_at" in data  # 仍返回字段，但为 None 或占位


def test_is_available_false_when_no_cache(cache):
    """缓存文件不存在时 is_available 返回 False。"""
    assert cache.is_available() is False


def test_is_available_true_after_refresh(cache, real_app_service):
    """refresh 后缓存应在 24 小时内可用。"""
    cache.refresh(app_service=real_app_service, scope="project", scope_id="XCMAX")
    assert cache.is_available() is True


def test_is_available_false_when_expired(cache, real_app_service, tmp_path):
    """缓存超过 24 小时应判定为不可用。"""
    cache.refresh(app_service=real_app_service, scope="project", scope_id="XCMAX")
    # 把 last_synced_at 改成 25 小时前
    data = json.loads(cache._cache_path.read_text(encoding="utf-8"))  # noqa: SLF001
    past = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    data["last_synced_at"] = past
    cache._cache_path.write_text(json.dumps(data), encoding="utf-8")  # noqa: SLF001
    assert cache.is_available() is False


def test_is_available_false_when_last_synced_at_missing(cache, real_app_service):
    """last_synced_at 字段缺失时应判定为不可用。"""
    cache.refresh(app_service=real_app_service, scope="project", scope_id="XCMAX")
    data = json.loads(cache._cache_path.read_text(encoding="utf-8"))  # noqa: SLF001
    data["last_synced_at"] = None
    cache._cache_path.write_text(json.dumps(data), encoding="utf-8")  # noqa: SLF001
    assert cache.is_available() is False


def test_write_queue_appends_jsonl(cache, tmp_path):
    """write_queue 应把操作以 JSONL 追加到 write-queue.jsonl。"""
    cache.write_queue({"op": "ingest", "type": "constraint", "title": "T1", "content": "C1"})
    cache.write_queue({"op": "ingest", "type": "convention", "title": "T2", "content": "C2"})
    queue_path = cache._queue_path  # noqa: SLF001
    assert queue_path.exists()
    lines = queue_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["op"] == "ingest"
    assert first["title"] == "T1"


def test_drain_queue_replays_to_persy(cache, real_app_service):
    """drain_queue 应把队列中的 ingest 操作逐条同步到 Persy。"""
    cache.write_queue(
        {
            "op": "ingest",
            "type": "constraint",
            "title": "队列约束",
            "content": "队列内容",
            "scope": "project",
            "scope_id": "XCMAX",
            "tags": ["offline"],
        }
    )
    cache.write_queue(
        {
            "op": "ingest",
            "type": "convention",
            "title": "队列约定",
            "content": "队列约定内容",
            "scope": "project",
            "scope_id": "XCMAX",
            "tags": [],
        }
    )

    synced = cache.drain_queue(app_service=real_app_service)
    assert synced == 2

    # 队列应被清空
    assert not cache._queue_path.exists()  # noqa: SLF001

    # Persy 应能搜到刚同步的节点
    results = real_app_service.search_memory(query="队列", scope="project", scope_id="XCMAX")
    titles = [r["title"] for r in results]
    assert "队列约束" in titles
    assert "队列约定" in titles


def test_drain_queue_skips_unknown_op(cache, real_app_service):
    """未知 op 应被跳过但不报错。"""
    cache.write_queue({"op": "unknown", "foo": "bar"})
    cache.write_queue(
        {
            "op": "ingest",
            "type": "constraint",
            "title": "正常约束",
            "content": "内容",
            "scope": "project",
            "scope_id": "XCMAX",
        }
    )
    synced = cache.drain_queue(app_service=real_app_service)
    assert synced == 1  # 只算 ingest


def test_drain_queue_handles_empty_queue(cache, real_app_service):
    """空队列应返回 0。"""
    synced = cache.drain_queue(app_service=real_app_service)
    assert synced == 0


def test_drain_queue_continues_on_single_failure(cache, real_app_service):
    """单条失败不应中断后续同步。"""
    # 第一条：type 非法（app_service.ingest_engineering 接收 MemoryNodeType 枚举，
    # 传字符串会触发异常；但我们的实现应在 drain 时做类型转换并跳过）
    cache.write_queue(
        {
            "op": "ingest",
            "type": "unknown_type",
            "title": "非法类型",
            "content": "x",
            "scope": "project",
            "scope_id": "XCMAX",
        }
    )
    cache.write_queue(
        {
            "op": "ingest",
            "type": "constraint",
            "title": "正常约束",
            "content": "y",
            "scope": "project",
            "scope_id": "XCMAX",
        }
    )
    synced = cache.drain_queue(app_service=real_app_service)
    # 非法类型被跳过，正常约束成功同步
    assert synced == 1


def test_load_with_persy_unavailable_returns_cached_nodes(cache, real_app_service):
    """Persy 不可用时 load 仍应返回缓存节点（persy_available=False 模拟离线）。"""
    real_app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="离线约束",
        content="离线内容",
        scope="project",
        scope_id="XCMAX",
    )
    cache.refresh(app_service=real_app_service, scope="project", scope_id="XCMAX")

    # 模拟 Persy 不可用：直接读缓存
    data = cache.load()
    assert data["persy_available"] is True  # 刚 refresh 完，应是 True

    # 篡改缓存标记为不可用，节点应仍可读
    data["persy_available"] = False
    cache._cache_path.write_text(json.dumps(data), encoding="utf-8")  # noqa: SLF001
    offline_data = cache.load()
    assert offline_data["persy_available"] is False
    assert len(offline_data["nodes"]) == 1
    assert offline_data["nodes"][0]["title"] == "离线约束"


def test_default_cache_path_under_trae_home():
    """默认 cache_path 应位于 ~/.trae-cn/memory-cache/persy-cache.json。"""
    from app.infrastructure.memory_cache import DEFAULT_CACHE_PATH, DEFAULT_QUEUE_PATH

    assert DEFAULT_CACHE_PATH.name == "persy-cache.json"
    assert DEFAULT_CACHE_PATH.parent.name == "memory-cache"
    assert ".trae-cn" in str(DEFAULT_CACHE_PATH)

    assert DEFAULT_QUEUE_PATH.name == "write-queue.jsonl"
    assert DEFAULT_QUEUE_PATH.parent.name == "memory-cache"
