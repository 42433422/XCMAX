"""双向链接解析器 MemoryLinkService 的测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_link_service import MemoryLinkService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.db.models.memory_graph import EdgeType, MemoryNodeType
from app.infrastructure.memory_graph_store import MemoryGraphStore


@pytest.fixture()
def store() -> MemoryGraphStore:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return MemoryGraphStore(Session(engine))


@pytest.fixture()
def link_service(store: MemoryGraphStore) -> MemoryLinkService:
    return MemoryLinkService(store)


def test_extract_links_finds_all_wiki_titles(link_service: MemoryLinkService):
    content = "参考 [[Ruff 唯一格式化工具]] 与 [[覆盖率 floor 88/81]] 的约定。"
    titles = link_service.extract_links(content)
    assert titles == ["Ruff 唯一格式化工具", "覆盖率 floor 88/81"]


def test_extract_links_dedupes_repeated_titles(link_service: MemoryLinkService):
    content = "见 [[A]]，再参见 [[A]] 与 [[B]]。"
    titles = link_service.extract_links(content)
    assert titles == ["A", "B"]


def test_extract_links_returns_empty_when_no_brackets(link_service: MemoryLinkService):
    assert link_service.extract_links("普通文本没有链接") == []


def test_sync_links_creates_bidirectional_edge_for_exact_title(
    store: MemoryGraphStore, link_service: MemoryLinkService
):
    target = store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    source = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="格式化约束",
        content="参见 [[Ruff 唯一格式化工具]]",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )

    created = link_service.sync_links(source.node_id, source.content)

    assert created == 1
    edges = store.list_backlinks(target.node_id)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.source_node_id == source.node_id
    assert edge.target_node_id == target.node_id
    assert edge.type == EdgeType.RELATES_TO
    assert edge.bidirectional is True


def test_sync_links_skips_self_reference(store: MemoryGraphStore, link_service: MemoryLinkService):
    """节点引用自身标题不应创建自环。"""
    node = store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="自指约定",
        content="参见 [[自指约定]]",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    created = link_service.sync_links(node.node_id, node.content)
    assert created == 0


def test_sync_links_falls_back_to_substring_match(
    store: MemoryGraphStore, link_service: MemoryLinkService
):
    """无精确标题匹配时，回退到子串模糊匹配（取第一个命中的节点）。"""
    target = store.create_node(
        type=MemoryNodeType.LESSON,
        title="文件级复制 SQLite 会损坏数据",
        content="必须用 backup API",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    source = store.create_node(
        type=MemoryNodeType.LESSON,
        title="备份教训汇总",
        content="记得 [[SQLite]] 的教训",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    created = link_service.sync_links(source.node_id, source.content)
    assert created == 1
    edges = store.list_backlinks(target.node_id)
    assert len(edges) == 1
    assert edges[0].source_node_id == source.node_id


def test_sync_links_skips_when_no_matching_node(
    store: MemoryGraphStore, link_service: MemoryLinkService
):
    """找不到任何匹配节点时，跳过该链接且不报错。"""
    source = store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="空引用约定",
        content="参见 [[不存在的节点]]",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    created = link_service.sync_links(source.node_id, source.content)
    assert created == 0


def test_sync_links_idempotent(store: MemoryGraphStore, link_service: MemoryLinkService):
    """重复 sync_links 同一对节点不应累积重复边。"""
    target = store.create_node(
        type=MemoryNodeType.CONVENTION,
        title="目标约定",
        content="...",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    source = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="来源约束",
        content="参见 [[目标约定]]",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    first = link_service.sync_links(source.node_id, source.content)
    second = link_service.sync_links(source.node_id, source.content)
    assert first == 1
    assert second == 0
    edges = store.list_backlinks(target.node_id)
    assert len(edges) == 1


def test_app_service_ingest_triggers_sync_links():
    """MemoryGraphAppService.ingest_engineering 应自动触发 sync_links。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    app_service = MemoryGraphAppService(
        store=store,
        update_engine=MemoryUpdateEngine(store),
        link_service=MemoryLinkService(store),
    )

    app_service.ingest_engineering(
        type=MemoryNodeType.CONVENTION,
        title="Ruff 唯一格式化工具",
        content="禁止 black/isort",
        scope="project",
        scope_id="XCMAX",
    )
    result = app_service.ingest_engineering(
        type=MemoryNodeType.CONSTRAINT,
        title="格式化约束",
        content="参见 [[Ruff 唯一格式化工具]]",
        scope="project",
        scope_id="XCMAX",
    )
    assert result["success"] is True
    assert result["action"] == "ADD"
    # result.node_id 是 source；用 store 查 target 的 backlinks 验证双向边
    target_nodes = store.list_active_nodes(
        scope="project", scope_id="XCMAX", node_type=MemoryNodeType.CONVENTION
    )
    assert len(target_nodes) == 1
    backlinks = store.list_backlinks(target_nodes[0].node_id)
    assert len(backlinks) == 1
    assert backlinks[0].source_node_id == result["node_id"]
    assert backlinks[0].bidirectional is True
