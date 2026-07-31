"""双向链接解析器 MemoryLinkService.

解析节点 content 中的 ``[[node_title]]`` wiki-link 语法，自动在 source 与匹配
target 之间创建 ``EdgeType.RELATES_TO`` 双向边。借鉴 Obsidian / Logseq 的反向
链接机制，让记忆图谱在写入时即建立结构化关联，无需用户手工维护边。

匹配策略：
1. 精确匹配：target.title == 链接文本
2. 模糊匹配：target.title 包含链接文本（取第一个命中）

幂等性：同一 (source, target, RELATES_TO) 组合只创建一条边。
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.db.models.memory_graph import EdgeType, MemoryNode, MemoryNodeStatus, TypedEdge
from app.infrastructure.memory_graph_store import MemoryGraphStore

# 匹配 [[...]] 中的标题；不跨行；不允许嵌套中括号
_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


class MemoryLinkService:
    """解析 content 中的 wiki-link 并同步双向边。"""

    def __init__(self, store: MemoryGraphStore) -> None:
        self._store = store

    def extract_links(self, content: str) -> list[str]:
        """提取 content 中所有 ``[[title]]`` 的标题，按出现顺序去重。"""
        if not content:
            return []
        seen: set[str] = set()
        titles: list[str] = []
        for match in _LINK_PATTERN.finditer(content):
            title = match.group(1).strip()
            if not title or title in seen:
                continue
            seen.add(title)
            titles.append(title)
        return titles

    def sync_links(self, node_id: str, content: str) -> int:
        """解析 content 中的链接，为每个匹配节点创建 ``RELATES_TO`` 双向边。

        除前向链接（本节点 → 已有节点）外，还会做反向回链扫描：已有节点的
        content 中如果包含 ``[[本节点标题]]``，则补建一条 ``已有节点 → 本节点``
        的双向边。这样先建的节点也能在后续节点入库时自动建立互链关系，
        行为与 Obsidian / Logseq 一致。

        Returns:
            本次新建的边数（已存在的重复边不计入）。
        """
        titles = self.extract_links(content)
        created = 0

        # 1. 前向链接：本节点 content 中的 [[...]] → 已有节点
        for title in titles:
            target = self._find_target_node(title)
            if target is None:
                continue
            if target.node_id == node_id:
                # 防止自环
                continue
            if self._edge_exists(node_id, target.node_id, EdgeType.RELATES_TO):
                continue
            self._store.add_edge(
                source_node_id=node_id,
                target_node_id=target.node_id,
                type=EdgeType.RELATES_TO,
                context=f"wiki-link: [[{title}]]",
                bidirectional=True,
            )
            created += 1

        # 2. 反向回链：已有节点 content 中引用了本节点标题 → 补建边
        created += self._sync_retroactive_backlinks(node_id)
        return created

    def _sync_retroactive_backlinks(self, node_id: str) -> int:
        """扫描已有 active 节点，若其 content 含 [[本节点标题]] 则补建双向边。"""
        node = self._store.get_node(node_id)
        if node is None or not node.title:
            return 0
        session = self._store._session  # noqa: SLF001
        # LIKE 模式匹配 [[标题]]；标题内含 % 或 _ 时用 ESCAPE 过于复杂，Phase 2 不处理
        pattern = f"%[[{node.title}]]%"
        stmt = select(MemoryNode).where(
            MemoryNode.content.like(pattern),
            MemoryNode.node_id != node_id,
            MemoryNode.status == MemoryNodeStatus.ACTIVE,
            MemoryNode.temporal_t_valid_end.is_(None),
        )
        candidates = list(session.scalars(stmt))
        created = 0
        for candidate in candidates:
            if self._edge_exists(candidate.node_id, node_id, EdgeType.RELATES_TO):
                continue
            self._store.add_edge(
                source_node_id=candidate.node_id,
                target_node_id=node_id,
                type=EdgeType.RELATES_TO,
                context=f"retroactive wiki-link: [[{node.title}]]",
                bidirectional=True,
            )
            created += 1
        return created

    def _find_target_node(self, title: str) -> MemoryNode | None:
        """先精确标题匹配，再回退到子串模糊匹配。"""
        session = self._store._session  # noqa: SLF001 - Store 已封装但这里需要读查询
        # 1. 精确匹配 title（同 scope 内的 active 节点）
        stmt = select(MemoryNode).where(
            MemoryNode.title == title,
            MemoryNode.status == MemoryNodeStatus.ACTIVE,
            MemoryNode.temporal_t_valid_end.is_(None),
        )
        node = session.scalars(stmt).first()
        if node is not None:
            return node

        # 2. 模糊匹配：title 包含链接文本（取第一个命中）
        fuzzy_stmt = select(MemoryNode).where(
            MemoryNode.title.like(f"%{title}%"),
            MemoryNode.status == MemoryNodeStatus.ACTIVE,
            MemoryNode.temporal_t_valid_end.is_(None),
        )
        return session.scalars(fuzzy_stmt).first()

    def _edge_exists(self, source_node_id: str, target_node_id: str, edge_type: EdgeType) -> bool:
        """检查同一 (source, target, type) 的有效边是否已存在。"""
        session = self._store._session  # noqa: SLF001
        stmt = select(TypedEdge).where(
            TypedEdge.source_node_id == source_node_id,
            TypedEdge.target_node_id == target_node_id,
            TypedEdge.type == edge_type,
            TypedEdge.temporal_t_valid_end.is_(None),
        )
        return session.scalars(stmt).first() is not None
