"""Trae Persy Memory MCP Server 单测。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

# CI 环境可能未安装 mcp 包（MCP server 仅在 Trae IDE 环境运行）
pytest.importorskip("mcp")


@pytest.fixture()
def mock_app_service():
    """Mock MemoryGraphAppService，记录所有调用。"""
    svc = MagicMock()
    svc.search_memory.return_value = [
        {
            "node_id": "n1",
            "type": "constraint",
            "title": "Ruff 唯一格式化工具",
            "content": "禁止 black/isort",
            "scope": "project",
            "scope_id": "XCMAX",
            "status": "active",
            "weight": 1.0,
            "recall_count": 0,
            "tags": ["ruff"],
            "t_valid_start": "2026-07-31T00:00:00+00:00",
            "t_valid_end": None,
        }
    ]
    svc.get_active_constraints.return_value = [
        {
            "node_id": "c1",
            "type": "constraint",
            "title": "约束 1",
            "content": "约束内容",
            "scope": "project",
            "scope_id": "XCMAX",
            "status": "active",
            "weight": 0.9,
            "recall_count": 1,
            "tags": [],
            "t_valid_start": "2026-07-31T00:00:00+00:00",
            "t_valid_end": None,
        }
    ]
    svc.get_active_conventions.return_value = [
        {
            "node_id": "v1",
            "type": "convention",
            "title": "约定 1",
            "content": "约定内容",
            "scope": "project",
            "scope_id": "XCMAX",
            "status": "active",
            "weight": 0.8,
            "recall_count": 0,
            "tags": [],
            "t_valid_start": "2026-07-31T00:00:00+00:00",
            "t_valid_end": None,
        }
    ]
    svc.ingest_engineering.return_value = {
        "success": True,
        "action": "ADD",
        "node_id": "new1",
        "superseded_node_id": None,
        "message": "新增约束",
    }
    svc.export_scope.return_value = "## constraint (1)\n### [active] 约束 1\n"
    svc.list_backlinks.return_value = []  # 默认无 backlinks
    # check_conflicts 通过遍历 contradicts 边实现；mock 返回空
    return svc


@pytest.fixture()
def server_with_mock(mock_app_service):
    """构造一个绑定了 mock app_service 的 MCP server。"""
    from mcp_servers.persy_memory.server import build_server

    return build_server(app_service=mock_app_service), mock_app_service


def _run(coro):
    """同步运行 async 函数。"""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_server_registers_six_tools(server_with_mock):
    """server 应注册 6 个 tool。"""
    server, _ = server_with_mock
    tools = _run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "search_memory",
        "get_active_constraints",
        "get_active_conventions",
        "ingest_engineering",
        "export_markdown",
        "check_conflicts",
    }


def test_search_memory_tool_calls_app_service(server_with_mock, mock_app_service):
    """search_memory tool 应转发到 app_service.search_memory。"""
    server, _ = server_with_mock
    # 直接调用注册的函数（@mcp.tool() 返回原函数）
    from mcp_servers.persy_memory.server import _tool_call_search_memory

    result = _tool_call_search_memory(query="ruff", scope="project", scope_id="XCMAX", top_k=5)
    mock_app_service.search_memory.assert_called_once_with(
        query="ruff", scope="project", scope_id="XCMAX", top_k=5
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["title"] == "Ruff 唯一格式化工具"


def test_get_active_constraints_tool(server_with_mock, mock_app_service):
    """get_active_constraints tool 应返回约束列表。"""
    from mcp_servers.persy_memory.server import _tool_call_get_active_constraints

    result = _tool_call_get_active_constraints(scope="project", scope_id="XCMAX")
    mock_app_service.get_active_constraints.assert_called_once_with(
        scope="project", scope_id="XCMAX"
    )
    assert len(result) == 1
    assert result[0]["title"] == "约束 1"


def test_get_active_conventions_tool(server_with_mock, mock_app_service):
    """get_active_conventions tool 应返回约定列表。"""
    from mcp_servers.persy_memory.server import _tool_call_get_active_conventions

    result = _tool_call_get_active_conventions(scope="project", scope_id="XCMAX")
    mock_app_service.get_active_conventions.assert_called_once_with(
        scope="project", scope_id="XCMAX"
    )
    assert len(result) == 1
    assert result[0]["title"] == "约定 1"


def test_ingest_engineering_tool_calls_app_service(server_with_mock, mock_app_service):
    """ingest_engineering tool 应转发参数并返回 dict。"""
    from mcp_servers.persy_memory.server import _tool_call_ingest_engineering

    result = _tool_call_ingest_engineering(
        type="constraint",
        title="新约束",
        content="内容",
        scope="project",
        scope_id="XCMAX",
        tags=["a", "b"],
    )
    mock_app_service.ingest_engineering.assert_called_once_with(
        type=__import__(
            "app.db.models.memory_graph", fromlist=["MemoryNodeType"]
        ).MemoryNodeType.CONSTRAINT,
        title="新约束",
        content="内容",
        scope="project",
        scope_id="XCMAX",
        tags=["a", "b"],
    )
    assert result["success"] is True
    assert result["node_id"] == "new1"


def test_export_markdown_tool(server_with_mock, mock_app_service):
    """export_markdown tool 应返回 markdown 字符串。"""
    from mcp_servers.persy_memory.server import _tool_call_export_markdown

    result = _tool_call_export_markdown(scope="project", scope_id="XCMAX", node_type="")
    mock_app_service.export_scope.assert_called_once()
    assert isinstance(result, str)
    assert "## constraint" in result


def test_export_markdown_tool_filters_by_type(server_with_mock, mock_app_service):
    """node_type=constraint 时只导出 constraint。"""
    from mcp_servers.persy_memory.server import _tool_call_export_markdown

    _tool_call_export_markdown(scope="project", scope_id="XCMAX", node_type="constraint")
    args = mock_app_service.export_scope.call_args
    assert args.kwargs["scope"] == "project"
    assert args.kwargs["scope_id"] == "XCMAX"
    # node_type 应为 MemoryNodeType.CONSTRAINT
    from app.db.models.memory_graph import MemoryNodeType

    assert args.kwargs["node_type"] == MemoryNodeType.CONSTRAINT


def test_check_conflicts_tool_returns_empty_when_no_edges(server_with_mock, mock_app_service):
    """check_conflicts 在无矛盾边时返回空列表。"""
    from mcp_servers.persy_memory.server import _tool_call_check_conflicts

    result = _tool_call_check_conflicts(scope="project", scope_id="XCMAX")
    assert isinstance(result, list)
    assert result == []


def test_check_conflicts_tool_returns_edges_when_present(server_with_mock, mock_app_service):
    """check_conflicts 应扫描 contradicts 边并返回结构化结果。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.application.memory_graph_app_service import MemoryGraphAppService
    from app.application.memory_update_engine import MemoryUpdateEngine
    from app.db.base import Base
    from app.db.models.memory_graph import EdgeType, MemoryNodeType
    from app.infrastructure.memory_graph_store import MemoryGraphStore
    from mcp_servers.persy_memory.server import _tool_call_check_conflicts, build_server

    # 用真实的 in-memory SQLite 构造一条 contradicts 边
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    real_svc = MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))

    node_a = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="约束 A",
        content="A",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    node_b = store.create_node(
        type=MemoryNodeType.CONSTRAINT,
        title="约束 B",
        content="B",
        scope="project",
        scope_id="XCMAX",
        source_policy="auto_active",
    )
    store.add_edge(
        source_node_id=node_a.node_id,
        target_node_id=node_b.node_id,
        type=EdgeType.CONTRADICTS,
        context="A 与 B 矛盾",
        bidirectional=False,
    )

    build_server(app_service=real_svc)
    result = _tool_call_check_conflicts(scope="project", scope_id="XCMAX")
    assert len(result) == 1
    assert result[0]["source_node_id"] == node_a.node_id
    assert result[0]["target_node_id"] == node_b.node_id
    assert result[0]["type"] == "contradicts"
    assert "A 与 B 矛盾" in result[0]["context"]


def test_build_server_uses_default_app_service_when_none(monkeypatch):
    """build_server(app_service=None) 应使用 get_default_app_service。

    必须显式清除 PERSY_DB_URL，否则会走独立 engine 分支。
    """
    from mcp_servers.persy_memory import server as server_module

    monkeypatch.delenv("PERSY_DB_URL", raising=False)
    captured = {}

    def fake_default():
        captured["called"] = True
        return MagicMock()

    original = server_module.get_default_app_service
    server_module.get_default_app_service = fake_default
    try:
        srv = server_module.build_server(app_service=None)
        assert captured["called"] is True
        assert srv is not None
    finally:
        server_module.get_default_app_service = original


def _reset_independent_engine() -> None:
    """重置 server 模块的独立 engine 单例（测试隔离用）。"""
    from mcp_servers.persy_memory import server as server_module

    server_module._independent_engine = None
    server_module._independent_session_factory = None


def test_get_independent_session_creates_engine_with_persy_db_url(monkeypatch, tmp_path):
    """设置 PERSY_DB_URL 时应用独立 engine 构造 session。"""
    from mcp_servers.persy_memory import server as server_module

    db_file = tmp_path / "test_persy.db"
    monkeypatch.setenv("PERSY_DB_URL", f"sqlite:///{db_file}")
    _reset_independent_engine()
    try:
        session = server_module._get_independent_session()
        # engine 已构造
        assert server_module._independent_engine is not None
        assert server_module._independent_session_factory is not None
        # 表已创建（可查询不报错）
        from sqlalchemy import inspect

        inspector = inspect(server_module._independent_engine)
        table_names = set(inspector.get_table_names())
        assert "persy_memory_nodes" in table_names
        assert "persy_memory_edges" in table_names
        # 第二次调用复用同一 engine
        session2 = server_module._get_independent_session()
        assert session2 is not None
    finally:
        _reset_independent_engine()


def test_get_svc_uses_independent_engine_when_persy_db_url_set(monkeypatch, tmp_path):
    """设置 PERSY_DB_URL 时 _get_svc 用独立 engine 构造 app_service。"""
    from mcp_servers.persy_memory import server as server_module

    db_file = tmp_path / "test_persy.db"
    monkeypatch.setenv("PERSY_DB_URL", f"sqlite:///{db_file}")
    # 清空模块级 _app_service，强制走 PERSY_DB_URL 分支
    original_app_service = server_module._app_service
    server_module._app_service = None
    _reset_independent_engine()
    try:
        svc = server_module._get_svc()
        # 应返回 MemoryGraphAppService 实例（非 mock）
        from app.application.memory_graph_app_service import MemoryGraphAppService

        assert isinstance(svc, MemoryGraphAppService)
        # engine 已构造
        assert server_module._independent_engine is not None
    finally:
        server_module._app_service = original_app_service
        _reset_independent_engine()


def test_get_svc_falls_back_to_default_when_no_persy_db_url(monkeypatch):
    """不设置 PERSY_DB_URL 时 _get_svc 回退到 get_default_app_service。"""
    from mcp_servers.persy_memory import server as server_module

    monkeypatch.delenv("PERSY_DB_URL", raising=False)
    original_app_service = server_module._app_service
    server_module._app_service = None
    captured = {}

    def fake_default():
        captured["called"] = True
        return MagicMock()

    original_default = server_module.get_default_app_service
    server_module.get_default_app_service = fake_default
    try:
        svc = server_module._get_svc()
        assert captured["called"] is True
        assert svc is not None
    finally:
        server_module._app_service = original_app_service
        server_module.get_default_app_service = original_default


def test_build_server_uses_independent_engine_when_persy_db_url_set(monkeypatch, tmp_path):
    """build_server(app_service=None) 在 PERSY_DB_URL 设置时用独立 engine。"""
    from mcp_servers.persy_memory import server as server_module

    db_file = tmp_path / "test_persy.db"
    monkeypatch.setenv("PERSY_DB_URL", f"sqlite:///{db_file}")
    original_app_service = server_module._app_service
    _reset_independent_engine()
    try:
        srv = server_module.build_server(app_service=None)
        assert srv is not None
        # _app_service 应为 MemoryGraphAppService 实例（独立 engine 构造）
        from app.application.memory_graph_app_service import MemoryGraphAppService

        assert isinstance(server_module._app_service, MemoryGraphAppService)
        assert server_module._independent_engine is not None
    finally:
        server_module._app_service = original_app_service
        _reset_independent_engine()


def test_build_server_reads_real_persy_memory_db(monkeypatch):
    """验证 MCP server 能读取真实 persy_memory.db 中的 61 个节点。

    仅当仓库根存在 persy_memory.db 时运行（CI 无此文件时跳过）。
    迁移数据：scope=project scope_id=XCMAX，共 61 个 ACTIVE 节点
    （24 constraint + 20 convention + 17 lesson）。
    """
    import os

    from mcp_servers.persy_memory import server as server_module

    db_path = os.path.join(os.getcwd(), "persy_memory.db")
    if not os.path.exists(db_path):
        pytest.skip("persy_memory.db 不存在（仅在已迁移环境运行）")

    monkeypatch.setenv("PERSY_DB_URL", f"sqlite:///{db_path}")
    original_app_service = server_module._app_service
    _reset_independent_engine()
    try:
        server_module.build_server(app_service=None)
        # 读取 active constraint + convention（lesson 不在 active 接口返回）
        constraints = server_module._tool_call_get_active_constraints(
            scope="project", scope_id="XCMAX"
        )
        conventions = server_module._tool_call_get_active_conventions(
            scope="project", scope_id="XCMAX"
        )
        # 24 constraint + 20 convention = 44
        assert len(constraints) == 24, f"期望 24 个 constraint，实际 {len(constraints)}"
        assert len(conventions) == 20, f"期望 20 个 convention，实际 {len(conventions)}"
        # search_memory 也能查到节点
        results = server_module._tool_call_search_memory(
            query="ruff", scope="project", scope_id="XCMAX", top_k=5
        )
        assert isinstance(results, list)
    finally:
        server_module._app_service = original_app_service
        _reset_independent_engine()
