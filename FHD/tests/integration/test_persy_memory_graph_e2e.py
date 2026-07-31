from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_export_service import MemoryExportService
from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_link_service import MemoryLinkService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.db.models.memory_graph import EdgeType, MemoryNode, MemoryNodeStatus, MemoryNodeType
from app.infrastructure.memory_cache import MemoryCacheService
from app.infrastructure.memory_graph_store import MemoryGraphStore
from scripts.dev.migrate_persy_to_memory_graph import PersyDataMigrator
from scripts.dev.migrate_trae_memory_to_persy import TraeMemoryMigrator


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


def test_full_migration_and_search(app_service, tmp_path):
    """端到端：迁移 Trae memory → 检索约束。"""
    project_dir = tmp_path / "projects" / "XCMAX"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 是唯一格式化工具：禁止 black/isort 与 Ruff 冲突
- 覆盖率 floor 88/81：2026-07-25 自 89/83 下调

## Engineering Conventions
- SSOT drift gate：真实入口是 ssot_cli.py gate

## Lessons Learned
- 文件级复制 SQLite 会损坏数据：必须用 backup API
""",
        encoding="utf-8",
    )

    migrator = TraeMemoryMigrator(memory_root=tmp_path, scope="project", scope_id="XCMAX")
    result = migrator.migrate(app_service)
    assert result["constraint"] == 2
    assert result["convention"] == 1
    assert result["lesson"] == 1

    constraints = app_service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 2
    titles = [c["title"] for c in constraints]
    assert any("Ruff" in t for t in titles)
    assert any("覆盖率" in t for t in titles)

    search_results = app_service.search_memory(query="Ruff", scope="project", scope_id="XCMAX")
    assert len(search_results) >= 1
    assert "Ruff" in search_results[0]["title"]

    conventions = app_service.get_active_conventions(scope="project", scope_id="XCMAX")
    assert len(conventions) == 1
    assert "SSOT" in conventions[0]["title"]


def test_idempotent_migration(app_service, tmp_path):
    """迁移幂等性：重复迁移不产生重复节点。"""
    project_dir = tmp_path / "projects" / "XCMAX"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 唯一格式化工具：禁止 black/isort
""",
        encoding="utf-8",
    )

    migrator = TraeMemoryMigrator(memory_root=tmp_path, scope="project", scope_id="XCMAX")
    migrator.migrate(app_service)
    migrator.migrate(app_service)  # 第二次迁移

    constraints = app_service.get_active_constraints(scope="project", scope_id="XCMAX")
    assert len(constraints) == 1  # 幂等，不重复


# =============================================================================
# Phase 2 端到端测试：双向链接 + 导出 + 完整生命周期
# =============================================================================


def test_bidirectional_link_flow(app_service):
    """创建两个带 [[...]] 互链的节点，验证双向边自动建立。"""
    # 节点 A 引用 B
    result_a = app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="约定 A",
        content="这是约定 A，参见 [[约定 B]]",
        scope="project",
        scope_id="XCMAX",
    )
    # 节点 B 引用 A
    result_b = app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="约定 B",
        content="这是约定 B，参见 [[约定 A]]",
        scope="project",
        scope_id="XCMAX",
    )
    assert result_a["success"] and result_b["success"]

    # A 应有指向 B 的边；B 应有指向 A 的边（双向链接）
    a_backlinks = app_service.list_backlinks(result_a["node_id"])
    b_backlinks = app_service.list_backlinks(result_b["node_id"])

    # A 的 backlinks 应包含 B（B 引用 A）
    assert any(bl["source_node_id"] == result_b["node_id"] for bl in a_backlinks)
    # B 的 backlinks 应包含 A（A 引用 B）
    assert any(bl["source_node_id"] == result_a["node_id"] for bl in b_backlinks)

    # 验证边类型与双向标志
    for backlink in a_backlinks + b_backlinks:
        assert backlink["type"] == "relates_to"
        assert backlink["bidirectional"] is True


def test_export_flow(app_service):
    """创建节点 + 边，导出 Markdown，验证格式含分组与 backlinks。"""
    # 目标节点
    app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="导出目标约束",
        content="被引用的目标",
        scope="project",
        scope_id="XCMAX",
    )
    # 来源节点（带 wiki-link）
    app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="导出来源约定",
        content="参见 [[导出目标约束]]",
        scope="project",
        scope_id="XCMAX",
    )

    export_service = MemoryExportService(app_service._store)  # noqa: SLF001
    md = export_service.export_scope(scope="project", scope_id="XCMAX")

    # 应按 type 分组
    assert "## constraint (1)" in md
    assert "## convention (1)" in md
    # 节点标题应出现
    assert "### [active] 导出目标约束" in md
    assert "### [active] 导出来源约定" in md
    # 目标节点应有 backlinks 段且包含来源标题
    target_section = md.split("### [active] 导出目标约束", 1)[1]
    assert "- **backlinks**:" in target_section
    assert "导出来源约定" in target_section
    assert "relates_to" in target_section


def test_full_lifecycle(app_service, tmp_path):
    """完整生命周期：迁移 Trae memory → Persy 迁移 → 搜索 → 导出 → 反向引用。"""
    # 1. 迁移 Trae project_memory.md（含 constraint + convention + lesson）
    project_dir = tmp_path / "projects" / "XCMAX"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 唯一格式化工具：禁止 black/isort

## Engineering Conventions
- 备份脚本路径：FHD/scripts/backup/

## Lessons Learned
- SQLite 文件复制会损坏数据
""",
        encoding="utf-8",
    )
    trae_migrator = TraeMemoryMigrator(memory_root=tmp_path, scope="project", scope_id="XCMAX")
    trae_result = trae_migrator.migrate(app_service)
    assert trae_result["constraint"] == 1
    assert trae_result["convention"] == 1
    assert trae_result["lesson"] == 1

    # 2. Persy 数据迁移（mock UserMemoryService）
    persy_records = [
        {
            "memory_id": "mem_persy_001",
            "memory_type": "preference",
            "key": "favorite_customer",
            "value": "ACME 公司",
            "status": "active",
            "confidence": 0.9,
            "source": "user_explicit",
            "source_policy": "trusted_pending",
            "updated_at": "2026-07-25T10:00:00",
            "created_at": "2026-07-25T09:00:00",
        },
        {
            "memory_id": "mem_persy_002",
            "memory_type": "entity",
            "key": "客户 ABC",
            "value": {"industry": "retail"},
            "status": "pending",
            "confidence": 0.6,
            "source": "agent_observation",
            "source_policy": "observed_pending",
            "updated_at": "2026-07-25T10:00:00",
            "created_at": "2026-07-25T09:00:00",
        },
        {
            "memory_id": "mem_persy_003",
            "memory_type": "episodic",
            "key": "上次发货",
            "value": "2026-07-20 发了 100 件",
            "status": "deleted",  # 应被跳过
            "confidence": 0.3,
            "source": "chat_trace",
            "source_policy": "observed_pending",
            "updated_at": "2026-07-25T10:00:00",
            "created_at": "2026-07-25T09:00:00",
        },
    ]
    mock_persy_service = MagicMock()
    mock_persy_service.list_memories.return_value = persy_records
    persy_migrator = PersyDataMigrator(user_memory_service=mock_persy_service)
    persy_result = persy_migrator.migrate(
        user_id="u1", scope="user", scope_id="u1", app_service=app_service
    )
    assert persy_result["migrated"] == 2  # active + pending
    assert persy_result["skipped"] == 1  # deleted
    assert persy_result["by_type"]["preference"] == 1
    assert persy_result["by_type"]["entity"] == 1

    # 3. 搜索：在 project scope 搜 Ruff
    search_results = app_service.search_memory(query="Ruff", scope="project", scope_id="XCMAX")
    assert len(search_results) >= 1
    assert any("Ruff" in r["title"] for r in search_results)

    # 4. 搜索：在 user scope 搜 ACME（验证 Persy 数据已写入）
    user_search = app_service.search_memory(query="ACME", scope="user", scope_id="u1")
    assert len(user_search) >= 1
    assert any("favorite_customer" in r["title"] for r in user_search)

    # 5. 导出 project scope 为 Markdown
    export_service = MemoryExportService(app_service._store)  # noqa: SLF001
    project_md = export_service.export_scope(scope="project", scope_id="XCMAX")
    assert "## constraint (1)" in project_md
    assert "Ruff 唯一格式化工具" in project_md
    assert "## convention (1)" in project_md
    assert "## lesson (1)" in project_md

    # 6. 导出 user scope（pending entity 不会出现在 active 导出中，只有 active preference）
    user_md = export_service.export_scope(scope="user", scope_id="u1")
    assert "## preference (1)" in user_md
    assert "favorite_customer" in user_md
    # entity 是 pending，不应在 active 导出里
    assert "## entity" not in user_md

    # 7. 反向引用：在 project 内创建一个引用 Ruff 的新节点，验证 backlinks
    ref_result = app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="格式化补充约定",
        content="补充 [[Ruff 唯一格式化工具]] 的细节",
        scope="project",
        scope_id="XCMAX",
    )
    ruff_nodes = [
        n
        for n in app_service.get_active_constraints(scope="project", scope_id="XCMAX")
        if "Ruff" in n["title"]
    ]
    assert len(ruff_nodes) == 1
    ruff_backlinks = app_service.list_backlinks(ruff_nodes[0]["node_id"])
    assert len(ruff_backlinks) == 1
    assert ruff_backlinks[0]["source_node_id"] == ref_result["node_id"]
    assert ruff_backlinks[0]["type"] == "relates_to"
    assert ruff_backlinks[0]["bidirectional"] is True


# =============================================================================
# Phase 3 端到端测试：衰减归档 + 语义检索升级 + 离线缓存 + 完整生命周期
# =============================================================================


def _set_node_age(app_service: MemoryGraphAppService, node_id: str, days_ago: int) -> None:
    """把节点的 created_at / last_recalled_at 调整为 days_ago 天前，模拟历史节点。"""
    past = datetime.now(UTC) - timedelta(days=days_ago)
    session = app_service._store._session  # noqa: SLF001
    session.execute(
        update(MemoryNode)
        .where(MemoryNode.node_id == node_id)
        .values(
            temporal_t_created=past,
            metadata_created_at=past,
            metadata_last_recalled_at=None,
        )
    )
    session.commit()


def _set_node_decay_params(
    app_service: MemoryGraphAppService,
    node_id: str,
    *,
    half_life_days: int,
    min_weight: float,
    recall_count: int = 0,
) -> None:
    """覆盖节点的衰减参数与召回计数。"""
    session = app_service._store._session  # noqa: SLF001
    values = {
        "metadata_decay_half_life_days": half_life_days,
        "metadata_decay_min_weight": min_weight,
        "metadata_recall_count": recall_count,
    }
    if recall_count > 0:
        # last_recalled_at 也设为很久以前，确保 age 大
        values["metadata_last_recalled_at"] = datetime.now(UTC) - timedelta(days=200)
    session.execute(update(MemoryNode).where(MemoryNode.node_id == node_id).values(**values))
    session.commit()


def test_decay_and_archive_flow(app_service):
    """衰减 + 自动归档端到端：旧低权重节点应被归档，新节点保留。"""
    from app.application.memory_decay_service import MemoryDecayService

    # 新节点（age=0）→ 高权重 → 保留
    fresh = app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="新约束",
        content="新约束内容",
        scope="project",
        scope_id="XCMAX",
    )
    # 旧 + 低权重 + 无召回 → 应被归档
    stale = app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="旧约束",
        content="旧约束内容",
        scope="project",
        scope_id="XCMAX",
    )
    _set_node_age(app_service, stale["node_id"], days_ago=200)
    _set_node_decay_params(
        app_service,
        stale["node_id"],
        half_life_days=10,
        min_weight=0.05,
        recall_count=0,
    )

    decay_svc = MemoryDecayService(app_service._store)  # noqa: SLF001
    result = decay_svc.run_maintenance(scope="project", scope_id="XCMAX")

    assert result["processed"] == 2
    assert result["archived"] == 1

    # 验证 fresh 仍 active，stale 已 archived
    fresh_node = app_service._store.get_node(fresh["node_id"])  # noqa: SLF001
    stale_node = app_service._store.get_node(stale["node_id"])  # noqa: SLF001
    assert fresh_node.status == MemoryNodeStatus.ACTIVE
    assert stale_node.status == MemoryNodeStatus.ARCHIVED
    assert stale_node.temporal_t_expired is not None


def test_semantic_search_upgrade(app_service):
    """search_memory 在 RAG 启用/关闭时都不应报错。"""
    app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort 与 Ruff 冲突",
        scope="project",
        scope_id="XCMAX",
    )
    app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="备份脚本路径",
        content="FHD/scripts/backup/",
        scope="project",
        scope_id="XCMAX",
    )

    # RAG 关闭：关键词匹配
    from unittest.mock import patch

    with patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=False):
        results = app_service.search_memory(query="ruff", scope="project", scope_id="XCMAX")
    assert len(results) >= 1
    assert any("Ruff" in r["title"] for r in results)

    # RAG 启用但 embedder None：仍降级为关键词
    with (
        patch("app.application.memory_graph_app_service.is_rag_enabled", return_value=True),
        patch(
            "app.application.memory_graph_app_service.get_default_embedder",
            return_value=None,
        ),
    ):
        results = app_service.search_memory(query="备份", scope="project", scope_id="XCMAX")
    assert len(results) >= 1
    assert any("备份" in r["title"] for r in results)


def test_cache_offline_flow(app_service, tmp_path):
    """缓存离线流程：refresh → 模拟 Persy 不可用 → 缓存仍可读。"""
    import json

    app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="离线约束 1",
        content="约束内容",
        scope="project",
        scope_id="XCMAX",
    )
    app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="离线约定 1",
        content="约定内容",
        scope="project",
        scope_id="XCMAX",
    )

    cache = MemoryCacheService(cache_path=tmp_path / "persy-cache.json")
    count = cache.refresh(app_service=app_service, scope="project", scope_id="XCMAX")
    assert count == 2
    assert cache.is_available() is True

    # 模拟 Persy 不可用：把 persy_available 标记为 False
    data = json.loads((tmp_path / "persy-cache.json").read_text(encoding="utf-8"))
    data["persy_available"] = False
    (tmp_path / "persy-cache.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )

    offline_data = cache.load()
    assert offline_data["persy_available"] is False
    assert len(offline_data["nodes"]) == 2
    titles = [n["title"] for n in offline_data["nodes"]]
    assert "离线约束 1" in titles
    assert "离线约定 1" in titles


def test_full_phase3_lifecycle(app_service, tmp_path):
    """Phase 3 完整生命周期：迁移 Trae memory → 衰减 → 搜索 → 导出 → 缓存。"""
    from app.application.memory_decay_service import MemoryDecayService

    # 1. 迁移 Trae project_memory.md
    project_dir = tmp_path / "projects" / "XCMAX"
    project_dir.mkdir(parents=True)
    (project_dir / "project_memory.md").write_text(
        """# Project Memory

## Hard Constraints
- Ruff 唯一格式化工具：禁止 black/isort

## Engineering Conventions
- 备份脚本路径：FHD/scripts/backup/
""",
        encoding="utf-8",
    )
    migrator = TraeMemoryMigrator(memory_root=tmp_path, scope="project", scope_id="XCMAX")
    migration_result = migrator.migrate(app_service)
    assert migration_result["constraint"] == 1
    assert migration_result["convention"] == 1

    # 2. 衰减维护（无归档，节点都是新建的）
    decay_svc = MemoryDecayService(app_service._store)  # noqa: SLF001
    decay_result = decay_svc.run_maintenance(scope="project", scope_id="XCMAX")
    assert decay_result["processed"] == 2
    assert decay_result["archived"] == 0

    # 3. 搜索（关键词降级，因为测试环境 RAG 可能未启用）
    results = app_service.search_memory(query="Ruff", scope="project", scope_id="XCMAX")
    assert len(results) >= 1
    assert any("Ruff" in r["title"] for r in results)

    # 4. 导出 Markdown
    export_service = MemoryExportService(app_service._store)  # noqa: SLF001
    md = export_service.export_scope(scope="project", scope_id="XCMAX")
    assert "## constraint (1)" in md
    assert "Ruff 唯一格式化工具" in md
    assert "## convention (1)" in md

    # 5. 缓存到本地
    cache = MemoryCacheService(cache_path=tmp_path / "persy-cache.json")
    cache_count = cache.refresh(app_service=app_service, scope="project", scope_id="XCMAX")
    assert cache_count == 2
    assert cache.is_available() is True

    # 6. 降级队列：写入 + 排空
    cache.write_queue(
        {
            "op": "ingest",
            "type": "lesson",
            "title": "Phase 3 教训",
            "content": "衰减归档需要 half_life 与 recall_count 配合",
            "scope": "project",
            "scope_id": "XCMAX",
            "tags": ["phase3"],
        }
    )
    synced = cache.drain_queue(app_service=app_service)
    assert synced == 1

    # 验证 lesson 节点已同步到 Persy
    lessons = app_service._store.list_active_nodes(  # noqa: SLF001
        scope="project", scope_id="XCMAX", node_type=MemoryNodeType.LESSON
    )
    assert len(lessons) == 1
    assert lessons[0].title == "Phase 3 教训"
