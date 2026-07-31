"""MemoryDecayService 单测：权重衰减 + 自动归档。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_decay_service import MemoryDecayService
from app.db.base import Base
from app.db.models.memory_graph import MemoryNodeStatus, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


@pytest.fixture()
def decay_service():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return MemoryDecayService(store)


def _create_active_node(
    decay_service: MemoryDecayService,
    *,
    title: str,
    content: str = "内容",
    half_life_days: int = 90,
    min_weight: float = 0.1,
    days_ago: int = 0,
    recall_count: int = 0,
):
    """创建一个 active 节点，并把 last_recalled_at/created_at 调整为 days_ago 天前。"""
    node = decay_service._store.create_node(  # noqa: SLF001 - 测试需要直接构造
        type=MemoryNodeType.CONSTRAINT,
        title=title,
        content=content,
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    # 直接 update 元数据，模拟历史节点
    from sqlalchemy import update

    from app.db.models.memory_graph import MemoryNode

    past = datetime.now(UTC) - timedelta(days=days_ago)
    decay_service._store._session.execute(  # noqa: SLF001
        update(MemoryNode)
        .where(MemoryNode.node_id == node.node_id)
        .values(
            metadata_decay_half_life_days=half_life_days,
            metadata_decay_min_weight=min_weight,
            metadata_recall_count=recall_count,
            metadata_last_recalled_at=past if recall_count > 0 else None,
            temporal_t_created=past,
            metadata_created_at=past,
        )
    )
    decay_service._store._session.commit()  # noqa: SLF001
    return decay_service._store.get_node(node.node_id)  # noqa: SLF001


def test_compute_weight_fresh_node_returns_one(decay_service):
    """刚创建的节点（age=0）权重应为 1.0。"""
    node = _create_active_node(decay_service, title="fresh", days_ago=0)
    weight = decay_service.compute_weight(node)
    assert weight == pytest.approx(1.0, abs=1e-6)


def test_compute_weight_decays_with_age(decay_service):
    """half_life=90 天的节点，180 天后权重应为 0.25。"""
    node = _create_active_node(decay_service, title="old", half_life_days=90, days_ago=180)
    weight = decay_service.compute_weight(node)
    # 1.0 * 0.5^(180/90) = 0.25
    assert weight == pytest.approx(0.25, abs=1e-4)


def test_compute_weight_floor_at_min_weight(decay_service):
    """权重不应低于 min_weight。"""
    node = _create_active_node(
        decay_service,
        title="very old",
        half_life_days=10,
        min_weight=0.3,
        days_ago=1000,
    )
    weight = decay_service.compute_weight(node)
    assert weight == pytest.approx(0.3, abs=1e-6)


def test_compute_weight_uses_last_recalled_at_when_present(decay_service):
    """有 last_recalled_at 时应基于它计算 age，而非 created_at。"""
    node = _create_active_node(
        decay_service,
        title="recalled",
        half_life_days=90,
        min_weight=0.01,  # 让 floor 不影响断言
        days_ago=365,  # created_at 一年前
        recall_count=5,  # last_recalled_at 也是 days_ago 天前
    )
    weight = decay_service.compute_weight(node)
    # age = 365 days, half_life = 90 → 1.0 * 0.5^(365/90)
    expected = 1.0 * 0.5 ** (365 / 90)
    assert weight == pytest.approx(expected, abs=1e-4)


def test_apply_decay_batch_updates_weights(decay_service):
    """批量衰减应更新所有 active 节点的 metadata_weight。"""
    _create_active_node(decay_service, title="fresh", days_ago=0)
    _create_active_node(decay_service, title="old", half_life_days=30, days_ago=120)
    result = decay_service.apply_decay_batch(scope="project", scope_id="XCMAX")
    assert result["processed"] == 2
    assert result["decayed"] >= 1  # 至少 old 节点被衰减
    assert result["archived"] == 0


def test_auto_archive_low_weight_unused_old_node(decay_service):
    """低权重 + 旧 + 无召回 → 归档。"""
    _create_active_node(
        decay_service,
        title="archive me",
        half_life_days=10,
        min_weight=0.05,
        days_ago=200,
        recall_count=0,
    )
    archived = decay_service.auto_archive(
        scope="project", scope_id="XCMAX", threshold=0.5, max_age_days=100
    )
    assert archived == 1
    nodes = decay_service._store.list_active_nodes(  # noqa: SLF001
        scope="project", scope_id="XCMAX"
    )
    assert len(nodes) == 0


def test_auto_archive_skips_high_weight_node(decay_service):
    """权重高的节点不应被归档。"""
    _create_active_node(decay_service, title="keep me", half_life_days=90, days_ago=10)
    archived = decay_service.auto_archive(
        scope="project", scope_id="XCMAX", threshold=0.15, max_age_days=180
    )
    assert archived == 0
    nodes = decay_service._store.list_active_nodes(  # noqa: SLF001
        scope="project", scope_id="XCMAX"
    )
    assert len(nodes) == 1


def test_auto_archive_skips_recently_recalled_node(decay_service):
    """recall_count > 0 的节点不应被归档（即使权重低、age 大）。"""
    _create_active_node(
        decay_service,
        title="recalled old",
        half_life_days=10,
        min_weight=0.05,
        days_ago=200,
        recall_count=3,
    )
    archived = decay_service.auto_archive(
        scope="project", scope_id="XCMAX", threshold=0.5, max_age_days=100
    )
    assert archived == 0


def test_auto_archive_sets_temporal_t_expired(decay_service):
    """归档节点应设置 temporal_t_expired。"""
    node = _create_active_node(
        decay_service,
        title="expire me",
        half_life_days=10,
        min_weight=0.05,
        days_ago=200,
        recall_count=0,
    )
    decay_service.auto_archive(scope="project", scope_id="XCMAX", threshold=0.5, max_age_days=100)
    refreshed = decay_service._store.get_node(node.node_id)  # noqa: SLF001
    assert refreshed.status == MemoryNodeStatus.ARCHIVED
    assert refreshed.temporal_t_expired is not None


def test_run_maintenance_combines_decay_and_archive(decay_service):
    """run_maintenance 应同时执行衰减和归档。"""
    _create_active_node(decay_service, title="fresh", days_ago=0)
    _create_active_node(
        decay_service,
        title="stale",
        half_life_days=10,
        min_weight=0.05,
        days_ago=200,
        recall_count=0,
    )
    result = decay_service.run_maintenance(scope="project", scope_id="XCMAX")
    assert result["processed"] == 2
    assert result["archived"] == 1
    # fresh 节点应仍为 active
    remaining = decay_service._store.list_active_nodes(  # noqa: SLF001
        scope="project", scope_id="XCMAX"
    )
    assert len(remaining) == 1
    assert remaining[0].title == "fresh"


def test_run_maintenance_handles_empty_scope(decay_service):
    """空 scope 不应报错。"""
    result = decay_service.run_maintenance(scope="project", scope_id="EMPTY")
    assert result["processed"] == 0
    assert result["decayed"] == 0
    assert result["archived"] == 0
