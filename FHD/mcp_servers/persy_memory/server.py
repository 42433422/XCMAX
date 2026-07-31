"""Persy Memory MCP Server.

通过 MCP 协议向 Trae IDE 暴露 Persy 记忆图谱的 6 个工具：

- ``search_memory`` — 语义/关键词搜索记忆
- ``get_active_constraints`` — 获取所有 active 约束
- ``get_active_conventions`` — 获取所有 active 约定
- ``ingest_engineering`` — 写入工程记忆（constraint/convention/lesson）
- ``export_markdown`` — 按 scope 导出 Markdown
- ``check_conflicts`` — 扫描 contradicts 边

实现要点：
- 使用 ``mcp`` Python 包 2.0 的 ``MCPServer``（前身 FastMCP，2.0 起重命名）。
- 每个 tool 函数同时导出为 ``_tool_call_<name>`` 别名，便于单测直接调用（绕过 MCP 框架）。
- ``build_server(app_service=None)`` 注入 app_service（默认走 ``get_default_app_service``）。
- 所有 tool 函数共享模块级 ``_app_service``；``build_server`` 负责初始化。

运行::

    python -m mcp_servers.persy_memory.server
    # 或
    python -c "from mcp_servers.persy_memory.server import build_server; build_server().run()"
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.db.models.memory_graph import EdgeType, MemoryNodeType
from app.fastapi_routes.knowledge_v2 import get_default_app_service

logger = logging.getLogger(__name__)

# 模块级 MCPServer 单例 + app_service 占位
_mcp = MCPServer("persy-memory")
_app_service: MemoryGraphAppService | None = None


def _get_svc() -> MemoryGraphAppService:
    """获取当前绑定的 app_service；未绑定时回退到 get_default_app_service。"""
    if _app_service is None:
        # 兜底：未调用 build_server 就直接调用 tool（罕见，但保持健壮）
        return get_default_app_service()
    return _app_service


def _parse_node_type(value: str) -> MemoryNodeType | None:
    """把字符串映射为 MemoryNodeType；空字符串或非法值返回 None。"""
    if not value:
        return None
    try:
        return MemoryNodeType(value)
    except ValueError:
        return None


# =============================================================================
# Tool 1: search_memory
# =============================================================================
@_mcp.tool()
def search_memory(
    query: str,
    scope: str = "project",
    scope_id: str = "",
    top_k: int = 10,
) -> list[dict]:
    """搜索 Persy 记忆图谱。

    Args:
        query: 搜索查询（关键词或自然语言）。
        scope: 作用域类型（project / user / tenant）。
        scope_id: 作用域内的标识。
        top_k: 最多返回的结果数。

    Returns:
        节点列表，每个节点含 node_id / type / title / content / weight 等。
    """
    return _get_svc().search_memory(query=query, scope=scope, scope_id=scope_id, top_k=top_k)


_tool_call_search_memory = search_memory


# =============================================================================
# Tool 2: get_active_constraints
# =============================================================================
@_mcp.tool()
def get_active_constraints(scope: str = "project", scope_id: str = "") -> list[dict]:
    """获取指定 scope 下所有 active 约束（constraint）。

    Args:
        scope: 作用域类型。
        scope_id: 作用域内的标识。

    Returns:
        约束节点列表。
    """
    return _get_svc().get_active_constraints(scope=scope, scope_id=scope_id)


_tool_call_get_active_constraints = get_active_constraints


# =============================================================================
# Tool 3: get_active_conventions
# =============================================================================
@_mcp.tool()
def get_active_conventions(scope: str = "project", scope_id: str = "") -> list[dict]:
    """获取指定 scope 下所有 active 约定（convention）。

    Args:
        scope: 作用域类型。
        scope_id: 作用域内的标识。

    Returns:
        约定节点列表。
    """
    return _get_svc().get_active_conventions(scope=scope, scope_id=scope_id)


_tool_call_get_active_conventions = get_active_conventions


# =============================================================================
# Tool 4: ingest_engineering
# =============================================================================
@_mcp.tool()
def ingest_engineering(
    type: str,
    title: str,
    content: str,
    scope: str = "project",
    scope_id: str = "",
    tags: list[str] | None = None,
) -> dict:
    """写入工程记忆（constraint / convention / lesson）。

    Args:
        type: 节点类型（constraint / convention / lesson）。
        title: 节点标题（≤160 字符）。
        content: 节点正文。
        scope: 作用域类型。
        scope_id: 作用域内的标识。
        tags: 可选标签列表。

    Returns:
        ``{"success": bool, "action": "ADD|UPDATE|NOOP", "node_id": str, ...}``
    """
    node_type = _parse_node_type(type)
    if node_type is None:
        return {
            "success": False,
            "error_code": "invalid_node_type",
            "message": f"unknown type: {type}",
        }
    return _get_svc().ingest_engineering(
        type=node_type,
        title=title,
        content=content,
        scope=scope,
        scope_id=scope_id,
        tags=tags,
    )


_tool_call_ingest_engineering = ingest_engineering


# =============================================================================
# Tool 5: export_markdown
# =============================================================================
@_mcp.tool()
def export_markdown(
    scope: str = "project",
    scope_id: str = "",
    node_type: str = "",
) -> str:
    """导出指定 scope 的记忆为 Markdown。

    Args:
        scope: 作用域类型。
        scope_id: 作用域内的标识。
        node_type: 可选节点类型过滤（constraint / convention / lesson 等）；空字符串表示全部。

    Returns:
        Markdown 字符串（按 type 分组，含 backlinks）。
    """
    parsed = _parse_node_type(node_type)
    return _get_svc().export_scope(scope=scope, scope_id=scope_id, node_type=parsed)


_tool_call_export_markdown = export_markdown


# =============================================================================
# Tool 6: check_conflicts
# =============================================================================
@_mcp.tool()
def check_conflicts(scope: str = "project", scope_id: str = "") -> list[dict]:
    """检查指定 scope 下的矛盾边（contradicts）。

    扫描 ``TypedEdge.type == CONTRADICTS`` 的有效边，返回结构化结果便于
    Trae 在写入新约束时主动提示冲突。

    Args:
        scope: 作用域类型。
        scope_id: 作用域内的标识。

    Returns:
        ``[{"edge_id": str, "source_node_id": str, "target_node_id": str,
           "source_title": str, "target_title": str, "type": "contradicts",
           "context": str}, ...]``
    """
    svc = _get_svc()
    store = svc._store  # noqa: SLF001 - MCP 层需要直接读取边，Store 暂未封装此查询
    session = store._session  # noqa: SLF001
    from sqlalchemy import select

    from app.db.models.memory_graph import TypedEdge

    stmt = select(TypedEdge).where(
        TypedEdge.type == EdgeType.CONTRADICTS,
        TypedEdge.temporal_t_valid_end.is_(None),
    )
    edges = list(session.scalars(stmt))
    result: list[dict[str, Any]] = []
    for edge in edges:
        source = store.get_node(edge.source_node_id)
        target = store.get_node(edge.target_node_id)
        # 仅返回 scope 匹配的边（source 或 target 任一在 scope 内即算）
        if source is None and target is None:
            continue
        in_scope = False
        if source is not None and source.scope == scope and source.scope_id == scope_id:
            in_scope = True
        if target is not None and target.scope == scope and target.scope_id == scope_id:
            in_scope = True
        if not in_scope:
            continue
        result.append(
            {
                "edge_id": edge.edge_id,
                "source_node_id": edge.source_node_id,
                "target_node_id": edge.target_node_id,
                "source_title": source.title if source else None,
                "target_title": target.title if target else None,
                "type": (edge.type.value if hasattr(edge.type, "value") else str(edge.type)),
                "context": edge.context or "",
                "bidirectional": edge.bidirectional,
            }
        )
    return result


_tool_call_check_conflicts = check_conflicts


# =============================================================================
# Server 构造入口
# =============================================================================
def build_server(app_service: MemoryGraphAppService | None = None) -> MCPServer:
    """构造并返回 MCPServer 单例。

    Args:
        app_service: 注入的 AppService；为 None 时使用 ``get_default_app_service()``。

    Returns:
        模块级 ``MCPServer`` 单例，所有 tool 已注册。
    """
    global _app_service
    if app_service is None:
        app_service = get_default_app_service()
    _app_service = app_service
    return _mcp


def main() -> None:
    """CLI 入口：以 stdio 传输启动 MCP server。"""
    build_server()
    _mcp.run()


if __name__ == "__main__":
    main()
