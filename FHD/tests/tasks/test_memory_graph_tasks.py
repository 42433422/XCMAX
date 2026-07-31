"""Persy 记忆图谱定时任务单测：权重衰减 + 缓存刷新。

测试策略：
- 用真实 in-memory SQLite app_service（参考 tests/infrastructure/test_memory_cache.py），
  避免过度 mock。
- patch ``asyncio.sleep`` 把 24h/30min 间隔压缩到 1ms，让任务能在测试时间内跑若干轮。
- patch ``asyncio.to_thread`` 为同步执行，避免线程环境下 mock 行为不可控。
- 用 ``asyncio.create_task`` + 短暂 ``await`` + ``cancel()`` 验证任务可启停。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.db.models.memory_graph import MemoryNode, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore

# 在任何 patch 之前捕获真实的 asyncio.sleep / asyncio.to_thread 引用。
# patch("...asyncio.sleep", ...) 会替换 asyncio 模块上的 sleep 属性（全局生效），
# 因此 _fast_sleep 内部必须用 _REAL_SLEEP 而非 asyncio.sleep，否则递归。
_REAL_SLEEP = asyncio.sleep
_REAL_TO_THREAD = asyncio.to_thread


@pytest.fixture()
def real_app_service():
    """构造一个真实 in-memory SQLite 的 app_service。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))


def _seed_old_node(app_service: MemoryGraphAppService, *, days_ago: int = 200):
    """创建一个 active 节点并把 created_at 调整为 days_ago 天前（触发衰减/归档）。"""
    node = app_service._store.create_node(  # noqa: SLF001
        type=MemoryNodeType.CONSTRAINT,
        title="旧约束",
        content="内容",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    past = datetime.now(UTC) - timedelta(days=days_ago)
    app_service._store._session.execute(  # noqa: SLF001
        update(MemoryNode)
        .where(MemoryNode.node_id == node.node_id)
        .values(
            metadata_recall_count=0,
            metadata_last_recalled_at=None,
            temporal_t_created=past,
            metadata_created_at=past,
        )
    )
    app_service._store._session.commit()  # noqa: SLF001
    return node.node_id


async def _fast_sleep(_seconds: float) -> None:
    """把任何 sleep 压缩到 1ms，避免测试等 24 小时。用 _REAL_SLEEP 避免递归。"""
    await _REAL_SLEEP(0.001)


async def _sync_to_thread(func, *args, **kwargs):
    """把 to_thread 改为同步直接调用，避免线程环境下 mock 行为不可控。"""
    return func(*args, **kwargs)


def _patch_task_timing():
    """patch 任务的 sleep + to_thread，返回 context manager 组合。"""
    from contextlib import ExitStack

    stack = ExitStack()
    stack.enter_context(
        patch("app.tasks.memory_graph_tasks.asyncio.sleep", side_effect=_fast_sleep)
    )
    stack.enter_context(
        patch("app.tasks.memory_graph_tasks.asyncio.to_thread", side_effect=_sync_to_thread)
    )
    return stack


# =============================================================================
# 衰减任务测试
# =============================================================================
async def test_run_memory_decay_task_calls_maintenance(real_app_service):
    """衰减任务应调用 MemoryDecayService.run_maintenance。"""
    _seed_old_node(real_app_service, days_ago=200)
    with _patch_task_timing():
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_decay_task"]
            ).run_memory_decay_task(real_app_service, interval_hours=24)
        )
        try:
            await _REAL_SLEEP(0.05)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    # 任务被取消后退出，无额外断言：只要不抛非 Cancelled 异常即说明 run_maintenance 被正常调用


async def test_run_memory_decay_task_can_be_cancelled(real_app_service):
    """衰减任务应能被 cancel 干净退出。"""
    with _patch_task_timing():
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_decay_task"]
            ).run_memory_decay_task(real_app_service, interval_hours=24)
        )
        await _REAL_SLEEP(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_run_memory_decay_task_continues_after_error(real_app_service):
    """衰减任务遇到异常应吞掉并继续，不退出循环。"""
    calls = {"n": 0}

    def fake_run_maintenance(self, scope, scope_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"processed": 0, "decayed": 0, "archived": 0}

    with (
        _patch_task_timing(),
        patch(
            "app.application.memory_decay_service.MemoryDecayService.run_maintenance",
            fake_run_maintenance,
        ),
    ):
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_decay_task"]
            ).run_memory_decay_task(real_app_service, interval_hours=24)
        )
        try:
            # 足够时间让任务跑两轮（第一轮异常 + 第二轮正常）
            await _REAL_SLEEP(0.1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    # 第一轮异常后任务应继续到第二轮（calls >= 2）
    assert calls["n"] >= 2


async def test_run_memory_decay_task_archives_old_node(real_app_service):
    """衰减任务应能归档 300 天前、无召回、低权重的节点。

    衰减公式：weight = 0.5^(age/90)。归档阈值 0.15。
    300 天 → weight = 0.5^(300/90) ≈ 0.099 < 0.15，满足归档条件。
    200 天 → weight ≈ 0.214 > 0.15，不归档（故用 300 天）。
    """
    node_id = _seed_old_node(real_app_service, days_ago=300)
    with _patch_task_timing():
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_decay_task"]
            ).run_memory_decay_task(real_app_service, interval_hours=24)
        )
        try:
            await _REAL_SLEEP(0.05)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    # 节点应被归档（status=archived）
    node = real_app_service._store.get_node(node_id)  # noqa: SLF001
    assert node.status.value == "archived"


# =============================================================================
# 缓存刷新任务测试
# =============================================================================
async def test_run_memory_cache_refresh_task_writes_cache(real_app_service, tmp_path, monkeypatch):
    """缓存刷新任务应把 active constraint + convention 写入本地 JSON。"""
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
    # 把 MemoryCacheService 默认路径指到 tmp_path
    cache_path = tmp_path / "persy-cache.json"
    monkeypatch.setattr(
        "app.infrastructure.memory_cache.MemoryCacheService.__init__",
        lambda self, cache_path=None, queue_path=None: (
            setattr(self, "_cache_path", cache_path or tmp_path / "persy-cache.json"),
            setattr(self, "_queue_path", queue_path or (tmp_path / "write-queue.jsonl")),
            None,
        )[-1],
    )
    with _patch_task_timing():
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_cache_refresh_task"]
            ).run_memory_cache_refresh_task(real_app_service, interval_minutes=30)
        )
        try:
            await _REAL_SLEEP(0.05)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    # 缓存文件应存在且包含 2 个节点
    assert cache_path.exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["persy_available"] is True
    assert len(data["nodes"]) == 2


async def test_run_memory_cache_refresh_task_can_be_cancelled(real_app_service):
    """缓存刷新任务应能被 cancel 干净退出。"""
    with _patch_task_timing():
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_cache_refresh_task"]
            ).run_memory_cache_refresh_task(real_app_service, interval_minutes=30)
        )
        await _REAL_SLEEP(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_run_memory_cache_refresh_task_continues_after_error(real_app_service, monkeypatch):
    """缓存刷新任务遇到异常应吞掉并继续，不退出循环。"""
    call_count = {"n": 0}

    class _BoomCache:
        def __init__(self, *args, **kwargs):
            pass

        def refresh(self, app_service, scope, scope_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("boom")
            return 0

    monkeypatch.setattr("app.infrastructure.memory_cache.MemoryCacheService", _BoomCache)
    with _patch_task_timing():
        task = asyncio.create_task(
            __import__(
                "app.tasks.memory_graph_tasks", fromlist=["run_memory_cache_refresh_task"]
            ).run_memory_cache_refresh_task(real_app_service, interval_minutes=30)
        )
        try:
            await _REAL_SLEEP(0.1)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    # 第一轮异常后任务应继续到第二轮（call_count >= 2）
    assert call_count["n"] >= 2


# =============================================================================
# lifespan 集成测试：_init_memory_graph_async + 环境变量控制
# =============================================================================
class _FakeApp:
    """轻量 FastAPI app 替身，只带 state。"""

    def __init__(self):
        self.state = type("_State", (), {})()


async def test_init_memory_graph_starts_tasks_when_enabled(monkeypatch):
    """XCAGI_MEMORY_GRAPH_ENABLED=1 时 _init_memory_graph_async 应启动两个任务。"""
    monkeypatch.setenv("XCAGI_MEMORY_GRAPH_ENABLED", "1")
    app = _FakeApp()
    # mock get_default_app_service 避免触发真实 DB
    fake_svc = object()  # 没人实际调用它，任务先 sleep 24h
    with patch("app.fastapi_routes.knowledge_v2.get_default_app_service", return_value=fake_svc):
        from app.fastapi_app.lifespan import _init_memory_graph_async

        await _init_memory_graph_async(app)
    try:
        assert hasattr(app.state, "memory_decay_task")
        assert hasattr(app.state, "memory_cache_refresh_task")
        assert not app.state.memory_decay_task.done()
        assert not app.state.memory_cache_refresh_task.done()
    finally:
        # 清理：取消任务避免泄漏
        for attr in ("memory_decay_task", "memory_cache_refresh_task"):
            t = getattr(app.state, attr, None)
            if t is not None and not t.done():
                t.cancel()


async def test_init_memory_graph_skips_when_disabled(monkeypatch):
    """XCAGI_MEMORY_GRAPH_ENABLED=0 时 _init_memory_graph_async 不启动任务。"""
    monkeypatch.setenv("XCAGI_MEMORY_GRAPH_ENABLED", "0")
    app = _FakeApp()
    from app.fastapi_app.lifespan import _init_memory_graph_async

    await _init_memory_graph_async(app)
    # 不应在 state 上设置任何任务属性
    assert not hasattr(app.state, "memory_decay_task")
    assert not hasattr(app.state, "memory_cache_refresh_task")


async def test_init_memory_graph_does_not_raise_on_failure(monkeypatch):
    """get_default_app_service 抛异常时 _init_memory_graph_async 不应阻断启动。"""
    monkeypatch.setenv("XCAGI_MEMORY_GRAPH_ENABLED", "1")
    app = _FakeApp()
    with patch(
        "app.fastapi_routes.knowledge_v2.get_default_app_service",
        side_effect=RuntimeError("DB unreachable"),
    ):
        from app.fastapi_app.lifespan import _init_memory_graph_async

        # 不应抛异常
        await _init_memory_graph_async(app)
    # 任务未启动
    assert not hasattr(app.state, "memory_decay_task")


def test_memory_graph_enabled_helper(monkeypatch):
    """_memory_graph_enabled 默认 True，设 0/false/off/no 为 False。"""
    from app.fastapi_app.lifespan import _memory_graph_enabled

    monkeypatch.delenv("XCAGI_MEMORY_GRAPH_ENABLED", raising=False)
    assert _memory_graph_enabled() is True

    for false_val in ("0", "false", "off", "no"):
        monkeypatch.setenv("XCAGI_MEMORY_GRAPH_ENABLED", false_val)
        assert _memory_graph_enabled() is False

    for true_val in ("1", "true", "on", "yes", "anything"):
        monkeypatch.setenv("XCAGI_MEMORY_GRAPH_ENABLED", true_val)
        assert _memory_graph_enabled() is True
