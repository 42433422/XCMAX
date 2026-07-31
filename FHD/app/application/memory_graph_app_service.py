"""Memory Graph Application Service.

业务编排层，整合 MemoryGraphStore + MemoryUpdateEngine。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from app.application.memory_export_service import MemoryExportService
from app.application.memory_link_service import MemoryLinkService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.models.memory_graph import (
    MemoryNode,
    MemoryNodeStatus,
    MemoryNodeType,
)
from app.infrastructure.memory_graph_store import MemoryGraphStore
from app.infrastructure.rag import get_default_embedder, is_rag_enabled
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度；长度不一致或零向量返回 0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryGraphAppService:
    """记忆图谱应用服务。"""

    def __init__(
        self,
        store: MemoryGraphStore,
        update_engine: MemoryUpdateEngine,
        link_service: MemoryLinkService | None = None,
        export_service: MemoryExportService | None = None,
    ) -> None:
        self._store = store
        self._update_engine = update_engine
        # 默认构造 link_service，保持向后兼容；显式传 None 可禁用双向链接
        self._link_service = link_service if link_service is not None else MemoryLinkService(store)
        self._export_service = (
            export_service if export_service is not None else MemoryExportService(store)
        )

    def ingest_engineering(
        self,
        *,
        type: MemoryNodeType,
        title: str,
        content: str,
        scope: str,
        scope_id: str,
        tags: list[str] | None = None,
        source: str = "trae",
        source_policy: str = "auto_active",
    ) -> dict[str, Any]:
        decision = self._update_engine.evaluate(
            type=type,
            title=title,
            content=content,
            scope=scope,
            scope_id=scope_id,
        )

        if decision.action == "NOOP":
            return {
                "success": True,
                "action": "NOOP",
                "node_id": decision.existing_node_id,
                "message": decision.reason,
            }

        node = self._store.create_node(
            type=type,
            title=title,
            content=content,
            scope=scope,
            scope_id=scope_id,
            source=source,
            source_policy=source_policy,
            tags=tags,
        )

        if decision.action == "UPDATE" and decision.existing_node_id:
            self._store.supersede_node(
                decision.existing_node_id, node.node_id, context=decision.reason
            )

        # 节点创建后自动同步双向链接（[[...]] 语法）
        if self._link_service is not None:
            self._link_service.sync_links(node.node_id, content)

        return {
            "success": True,
            "action": decision.action,
            "node_id": node.node_id,
            "superseded_node_id": decision.existing_node_id,
            "message": decision.reason,
        }

    def get_active_constraints(self, *, scope: str, scope_id: str) -> list[dict[str, Any]]:
        nodes = self._store.list_active_nodes(
            scope=scope, scope_id=scope_id, node_type=MemoryNodeType.CONSTRAINT
        )
        return [self._node_to_dict(n) for n in nodes]

    def get_active_conventions(self, *, scope: str, scope_id: str) -> list[dict[str, Any]]:
        nodes = self._store.list_active_nodes(
            scope=scope, scope_id=scope_id, node_type=MemoryNodeType.CONVENTION
        )
        return [self._node_to_dict(n) for n in nodes]

    def search_memory(
        self,
        *,
        query: str,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """搜索记忆：先尝试语义检索，无结果时降级为关键词匹配。

        降级链：
            1. 若 ``is_rag_enabled()`` 为 True 且 embedder 可用 → 语义检索（cosine）
            2. 若语义检索无结果，或 RAG/embedder 不可用 → 关键词匹配（标题/内容子串）
        """
        semantic_results = self._semantic_search(
            query=query,
            scope=scope,
            scope_id=scope_id,
            node_type=node_type,
            top_k=top_k,
        )
        if semantic_results:
            return semantic_results
        return self._keyword_search(
            query=query,
            scope=scope,
            scope_id=scope_id,
            node_type=node_type,
            top_k=top_k,
        )

    def _semantic_search(
        self,
        *,
        query: str,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """基于 embedder 的语义检索；任何环节不可用时返回空列表（让上层降级）。"""
        if not is_rag_enabled():
            return []
        try:
            embedder = get_default_embedder()
        except RECOVERABLE_ERRORS as e:
            logger.debug("[MemoryGraph] embedder 加载失败，降级关键词: %s", e)
            return []
        if embedder is None:
            return []

        nodes = self._store.list_active_nodes(scope=scope, scope_id=scope_id, node_type=node_type)
        if not nodes:
            return []

        try:
            query_vec = embedder(query)
        except RECOVERABLE_ERRORS as e:
            logger.warning("[MemoryGraph] 查询向量计算失败，降级关键词: %s", e)
            return []

        # 编码每个节点的 title + content，与查询向量计算 cosine
        scored: list[tuple[float, MemoryNode]] = []
        for node in nodes:
            text = f"{node.title}\n{node.content or ''}"
            try:
                node_vec = embedder(text)
            except RECOVERABLE_ERRORS as e:
                logger.debug("[MemoryGraph] 节点向量计算失败 node=%s: %s", node.node_id, e)
                continue
            sim = _cosine_similarity(query_vec, node_vec)
            if sim > 0:
                scored.append((sim * node.metadata_weight, node))

        if not scored:
            return []
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        for _, node in top:
            self._store.record_recall(node.node_id)
        return [self._node_to_dict(n) for _, n in top]

    def _keyword_search(
        self,
        *,
        query: str,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """关键词匹配：标题命中 1.0 分，内容命中 0.5 分。"""
        nodes = self._store.list_active_nodes(scope=scope, scope_id=scope_id, node_type=node_type)
        query_lower = query.lower()
        scored: list[tuple[float, MemoryNode]] = []
        for node in nodes:
            title_match = query_lower in node.title.lower()
            content_match = query_lower in (node.content or "").lower()
            score = (1.0 if title_match else 0.0) + (0.5 if content_match else 0.0)
            if score > 0:
                scored.append((score * node.metadata_weight, node))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, node in scored[:top_k]:
            self._store.record_recall(node.node_id)
        return [self._node_to_dict(n) for _, n in scored[:top_k]]

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """获取单个节点详情；不存在返回 None。"""
        node = self._store.get_node(node_id)
        if node is None:
            return None
        return self._node_to_dict(node)

    def list_backlinks(self, node_id: str) -> list[dict[str, Any]]:
        """列出指向 node_id 的所有有效反向边（含 source 节点摘要）。"""
        edges = self._store.list_backlinks(node_id)
        result: list[dict[str, Any]] = []
        for edge in edges:
            source = self._store.get_node(edge.source_node_id)
            result.append(
                {
                    "edge_id": edge.edge_id,
                    "source_node_id": edge.source_node_id,
                    "source_title": source.title if source else None,
                    "source_type": source.type.value if source else None,
                    "type": edge.type.value if hasattr(edge.type, "value") else str(edge.type),
                    "bidirectional": edge.bidirectional,
                    "context": edge.context,
                }
            )
        return result

    def export_node(self, node_id: str) -> str:
        """导出单个节点为 Markdown。"""
        return self._export_service.export_node(node_id)

    def export_scope(
        self,
        scope: str,
        scope_id: str,
        node_type: MemoryNodeType | None = None,
    ) -> str:
        """按 scope 导出所有 active 节点为 Markdown。"""
        return self._export_service.export_scope(scope, scope_id, node_type)

    def confirm_node(self, node_id: str) -> dict[str, Any]:
        """确认 pending 记忆：状态置为 active。"""
        return self._set_node_status(node_id, MemoryNodeStatus.ACTIVE, "confirmed")

    def reject_node(self, node_id: str, *, reason: str = "") -> dict[str, Any]:
        """拒绝 pending 记忆：状态置为 rejected。"""
        return self._set_node_status(node_id, MemoryNodeStatus.REJECTED, "rejected", reason=reason)

    def _set_node_status(
        self,
        node_id: str,
        status: MemoryNodeStatus,
        action_label: str,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        node = self._store.get_node(node_id)
        if node is None:
            return {"success": False, "error_code": "node_not_found", "message": "节点不存在"}
        if node.status == MemoryNodeStatus.DELETED:
            return {"success": False, "error_code": "invalid_state", "message": "节点已删除"}
        # 必须在 commit 前捕获旧状态：SQLAlchemy 默认 expire_on_commit=True，
        # commit 后访问 node.status 会触发重新加载，返回新值。
        previous_status = node.status.value if hasattr(node.status, "value") else str(node.status)
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": status,
            "metadata_updated_at": now,
        }
        if status == MemoryNodeStatus.ACTIVE:
            values["temporal_t_valid_start"] = now
        elif status == MemoryNodeStatus.REJECTED:
            values["temporal_t_valid_end"] = now
        self._store._session.execute(  # noqa: SLF001 - store 暴露的 update 接口暂未封装此操作
            update(MemoryNode).where(MemoryNode.node_id == node_id).values(**values)
        )
        self._store._session.commit()  # noqa: SLF001
        return {
            "success": True,
            "action": action_label,
            "node_id": node_id,
            "previous_status": previous_status,
            "new_status": status.value,
            "reason": reason,
        }

    def _node_to_dict(self, node: MemoryNode) -> dict[str, Any]:
        return {
            "node_id": node.node_id,
            "type": node.type.value if hasattr(node.type, "value") else str(node.type),
            "title": node.title,
            "content": node.content,
            "scope": node.scope,
            "scope_id": node.scope_id,
            "status": node.status.value if hasattr(node.status, "value") else str(node.status),
            "weight": node.metadata_weight,
            "recall_count": node.metadata_recall_count,
            "tags": node.tags_list(),
            "t_valid_start": node.temporal_t_valid_start.isoformat()
            if node.temporal_t_valid_start
            else None,
            "t_valid_end": node.temporal_t_valid_end.isoformat()
            if node.temporal_t_valid_end
            else None,
        }
