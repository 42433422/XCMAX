"""工作记忆（WorkingMemory）——Conscious 处理器的会话级记忆。

复用 ``ConversationService`` 的短期会话消息（SQL）作为工作记忆源，
不依赖完整 ``EmployeeMemoryManager``（那需要 ``MemoryScope`` + EmployeeAgent 上下文）。

设计原则（与 ``EmployeeMemoryManager`` 一致）：
- best-effort：任何后端不可用都降级为空记忆，不阻断 Conscious 处理。
- 短期优先：默认只召回当前 session 的最近 N 条消息（< 5ms）。
- 长期可选：``enable_long_term=True`` 时追加向量召回（``UserMemoryRagApplicationService``）。

Phase 2 用途：为 ``AttentionSelector`` 提供候选上下文，供 LLM 生成时引用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_SHORT_TERM_LIMIT = 8
_LONG_TERM_TOPK = 3


@dataclass
class MemoryItem:
    """一条工作记忆条目。"""

    role: str  # "user" | "assistant" | "system"
    content: str
    source: str = "session"  # "session" | "long_term"
    score: float = 0.0  # 相关性分数（由 AttentionSelector 填充）
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkingMemorySnapshot:
    """一次召回的工作记忆快照。"""

    items: list[MemoryItem] = field(default_factory=list)
    session_id: str = ""
    user_id: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.items

    def as_messages(self) -> list[dict[str, str]]:
        """转为 OpenAI 消息格式（供 LLM 调用）。"""
        return [{"role": it.role, "content": it.content} for it in self.items]


class WorkingMemory:
    """Conscious 处理器的工作记忆。

    Args:
        session_id: 会话 ID（用于短期召回）。
        user_id: 用户 ID（用于长期向量召回的命名空间）。
        enable_long_term: 是否启用长期向量记忆（默认关闭，保持 <10ms SLA）。
    """

    def __init__(
        self,
        session_id: str = "",
        user_id: str = "",
        enable_long_term: bool = False,
    ) -> None:
        self._session_id = session_id
        self._user_id = user_id
        self._enable_long_term = enable_long_term

    def recall(self, query: str = "") -> WorkingMemorySnapshot:
        """召回工作记忆。

        Args:
            query: 当前查询（用于长期向量召回的相关性匹配）。

        Returns:
            ``WorkingMemorySnapshot``，包含短期 + 可选长期记忆条目。
        """
        snapshot = WorkingMemorySnapshot(
            session_id=self._session_id,
            user_id=self._user_id,
        )

        # 短期：会话消息
        short_items = self._recall_short_term()
        snapshot.items.extend(short_items)

        # 长期：向量召回（可选）
        if self._enable_long_term and query:
            long_items = self._recall_long_term(query)
            snapshot.items.extend(long_items)

        return snapshot

    def remember(
        self,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """写入短期记忆（持久化到会话消息表）。

        Args:
            role: 消息角色（``user`` / ``assistant`` / ``system``）。
            content: 消息内容。
            metadata: 附加元数据。
        """
        if not self._session_id:
            return
        try:
            import json

            from app.services.conversation_service import ConversationService

            ConversationService().save_message(
                self._session_id,
                self._user_id or "neuro",
                role,
                content,
                metadata=json.dumps(metadata or {}, ensure_ascii=False),
            )
        except RECOVERABLE_ERRORS:
            logger.debug(
                "WorkingMemory.remember skipped (session=%s)", self._session_id, exc_info=True
            )

    def _recall_short_term(self) -> list[MemoryItem]:
        """从会话消息表召回最近 N 条消息。"""
        sid = self._session_id.strip()
        if not sid:
            return []
        try:
            from app.services.conversation_service import ConversationService

            rows = ConversationService().get_session_messages(sid, limit=50)
        except RECOVERABLE_ERRORS:
            logger.debug("short-term recall skipped (session=%s)", sid, exc_info=True)
            return []

        items: list[MemoryItem] = []
        for row in rows or []:
            try:
                role = str(row[3] or "user")
                content = str(row[4] or "")
            except (IndexError, TypeError):
                continue
            if not content:
                continue
            items.append(
                MemoryItem(
                    role=role,
                    content=content,
                    source="session",
                )
            )
        # 取最近 N 条
        return items[-_SHORT_TERM_LIMIT:]

    def _recall_long_term(self, query: str) -> list[MemoryItem]:
        """从用户记忆向量索引召回相关条目。"""
        if not self._user_id:
            return []
        try:
            from app.application.user_memory_vector_app_service import (
                get_user_memory_rag_app_service,
            )

            svc = get_user_memory_rag_app_service()
            result = svc.query(self._user_id, query, top_k=_LONG_TERM_TOPK)
        except RECOVERABLE_ERRORS:
            logger.debug("long-term recall skipped (user=%s)", self._user_id, exc_info=True)
            return []

        hits = result.get("hits") or [] if isinstance(result, dict) else []
        items: list[MemoryItem] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            content = str(hit.get("content") or hit.get("text") or "")
            if not content:
                continue
            items.append(
                MemoryItem(
                    role="system",
                    content=content,
                    source="long_term",
                    score=float(hit.get("score", 0.0)),
                    metadata=dict(hit.get("metadata") or {}),
                )
            )
        return items


_memory: WorkingMemory | None = None


def get_working_memory(
    session_id: str = "",
    user_id: str = "",
    enable_long_term: bool = False,
) -> WorkingMemory:
    """获取全局 ``WorkingMemory`` 单例（按 session_id/user_id 初始化）。"""
    global _memory
    if _memory is None or _memory._session_id != session_id or _memory._user_id != user_id:
        _memory = WorkingMemory(
            session_id=session_id,
            user_id=user_id,
            enable_long_term=enable_long_term,
        )
    return _memory


def reset_working_memory() -> None:
    """重置单例（测试用）。"""
    global _memory
    _memory = None
