"""PersyDataMigrator 测试：从 UserMemoryService 迁移到 MemoryGraph。"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.db.models.memory_graph import MemoryNodeStatus, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore
from scripts.dev.migrate_persy_to_memory_graph import PersyDataMigrator


@pytest.fixture()
def app_service():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    return MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))


def _make_persy_record(
    *,
    memory_type: str = "preference",
    key: str = "favorite_customer",
    value: Any = "ACME 公司",
    status: str = "active",
    memory_id: str | None = None,
    source: str = "user_explicit",
    confidence: float = 0.8,
) -> dict[str, Any]:
    import uuid

    return {
        "memory_id": memory_id or f"mem_{uuid.uuid4().hex[:12]}",
        "memory_type": memory_type,
        "key": key,
        "value": value,
        "status": status,
        "confidence": confidence,
        "source": source,
        "source_policy": "trusted_pending",
        "updated_at": "2026-07-25T10:00:00",
        "created_at": "2026-07-25T09:00:00",
    }


def _make_mock_user_memory_service(records: list[dict[str, Any]]) -> MagicMock:
    """构造一个 mock UserMemoryService，list_memories 返回给定 records。"""
    svc = MagicMock()
    svc.list_memories.return_value = [dict(r) for r in records]
    return svc


def test_migrate_active_preference_to_memory_graph(app_service):
    records = [
        _make_persy_record(
            memory_type="preference",
            key="favorite_customer",
            value="ACME 公司",
            status="active",
        )
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    result = migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)

    assert result["total"] == 1
    assert result["migrated"] == 1
    assert result["skipped"] == 0
    assert result["by_type"]["preference"] == 1
    # 验证节点写入
    nodes = app_service._store.list_active_nodes(  # noqa: SLF001
        scope="user", scope_id="u1", node_type=MemoryNodeType.PREFERENCE
    )
    assert len(nodes) == 1
    assert "favorite_customer" in nodes[0].title


def test_migrate_preserves_pending_status(app_service):
    """pending 状态的 Persy 记忆应迁移为 PENDING 节点（不自动激活）。"""
    records = [
        _make_persy_record(
            memory_type="entity",
            key="客户 ABC",
            value={"industry": "retail"},
            status="pending",
        )
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)

    # pending 节点不会被 list_active_nodes 看到
    active_nodes = app_service._store.list_active_nodes(  # noqa: SLF001
        scope="user", scope_id="u1", node_type=MemoryNodeType.ENTITY
    )
    assert len(active_nodes) == 0
    # 但应该能通过直接查 store.get_node 找到；这里改用全量 list 检查
    # 由于 store 没有 list_all_nodes，用 _session 直接查
    from app.db.models.memory_graph import MemoryNode

    nodes = app_service._store._session.query(MemoryNode).all()  # noqa: SLF001
    assert len(nodes) == 1
    assert nodes[0].status == MemoryNodeStatus.PENDING
    assert nodes[0].type == MemoryNodeType.ENTITY


def test_migrate_skips_deleted_records(app_service):
    """deleted 状态的 Persy 记忆应跳过，不写入 MemoryGraph。"""
    records = [
        _make_persy_record(status="deleted", key="已删除的偏好"),
        _make_persy_record(status="active", key="active 偏好"),
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    result = migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)

    assert result["migrated"] == 1
    assert result["skipped"] == 1
    assert "deleted" in result["by_skipped_reason"]


def test_migrate_rejected_record_keeps_rejected_status(app_service):
    """rejected 状态保留为 REJECTED 节点（用于审计），不算迁移成功。"""
    records = [
        _make_persy_record(status="rejected", key="被拒绝的偏好"),
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    result = migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)

    assert result["migrated"] == 1
    from app.db.models.memory_graph import MemoryNode

    nodes = app_service._store._session.query(MemoryNode).all()  # noqa: SLF001
    assert len(nodes) == 1
    assert nodes[0].status == MemoryNodeStatus.REJECTED


def test_migrate_maps_memory_types(app_service):
    """preference/entity/episodic 三种类型应正确映射到 MemoryNodeType。"""
    records = [
        _make_persy_record(memory_type="preference", key="pref1", value="v1", status="active"),
        _make_persy_record(memory_type="entity", key="ent1", value="v2", status="active"),
        _make_persy_record(memory_type="episodic", key="ep1", value="v3", status="active"),
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    result = migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)

    assert result["migrated"] == 3
    assert result["by_type"]["preference"] == 1
    assert result["by_type"]["entity"] == 1
    assert result["by_type"]["episodic"] == 1


def test_migrate_is_idempotent(app_service):
    """重复迁移同一份数据不应产生重复节点。"""
    records = [
        _make_persy_record(
            memory_type="preference", key="favorite_customer", value="ACME", status="active"
        )
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)
    second = migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)
    # 第二次：MemoryUpdateEngine 判定为 NOOP（重复）
    assert second["migrated"] == 0
    assert second["noop"] == 1
    nodes = app_service._store.list_active_nodes(  # noqa: SLF001
        scope="user", scope_id="u1", node_type=MemoryNodeType.PREFERENCE
    )
    assert len(nodes) == 1


def test_migrate_dry_run_does_not_persist(app_service):
    records = [
        _make_persy_record(memory_type="preference", key="dry-run-pref", value="v"),
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    result = migrator.migrate(
        user_id="u1", scope="user", scope_id="u1", app_service=app_service, dry_run=True
    )
    assert result["migrated"] == 0
    assert result["dry_run"] is True
    assert result["would_migrate"] == 1
    nodes = app_service._store.list_active_nodes(  # noqa: SLF001
        scope="user", scope_id="u1", node_type=MemoryNodeType.PREFERENCE
    )
    assert len(nodes) == 0


def test_migrate_unknown_type_is_skipped(app_service):
    """未知 memory_type 应跳过并记录到 by_skipped_reason。"""
    records = [
        _make_persy_record(memory_type="preference", key="ok", value="v", status="active"),
        {**_make_persy_record(key="bad"), "memory_type": "unknown_type"},
    ]
    migrator = PersyDataMigrator(user_memory_service=_make_mock_user_memory_service(records))
    result = migrator.migrate(user_id="u1", scope="user", scope_id="u1", app_service=app_service)

    assert result["migrated"] == 1
    assert result["skipped"] == 1
    # 跳过原因 key 形如 "unknown_type:<type_str>"
    assert any(k.startswith("unknown_type:") for k in result["by_skipped_reason"])
