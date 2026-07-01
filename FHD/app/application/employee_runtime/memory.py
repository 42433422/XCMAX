"""员工记忆管理器：短期会话（SQL）+ 长期向量记忆。

打通此前断开的链路：
- 短期：``ConversationService.save_message / get_session_messages``，按 session_id 落库，
  metadata 携带 employee_id 以便回放时只取本员工历史。
- 长期：``UserMemoryVectorIngest.ingest_chunks`` 写、``UserMemoryRag.query`` 读，
  index 命名空间 ``emp:<employee_id>``（见 MemoryScope.long_term_index）。

所有操作 best-effort：任何后端不可用都降级为空记忆，绝不让员工执行因记忆失败而中断。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from app.domain.employee.memory_scope import MemoryScope

logger = logging.getLogger(__name__)

_SHORT_TERM_RECALL = 8
_LONG_TERM_TOPK = 5


class MemoryContext:
    """一次召回的记忆上下文。"""

    def __init__(
        self,
        long_term_prompt: str = "",
        short_term_messages: list[dict[str, str]] | None = None,
        hits: list[dict[str, Any]] | None = None,
    ) -> None:
        self.long_term_prompt = long_term_prompt or ""
        self.short_term_messages = short_term_messages or []
        self.hits = hits or []

    @property
    def has_content(self) -> bool:
        return bool(self.long_term_prompt or self.short_term_messages)

    def as_system_suffix(self) -> str:
        """拼成可追加到 system_prompt 的记忆段落。"""
        blocks: list[str] = []
        if self.short_term_messages:
            lines = [
                f"- {m.get('role', 'user')}: {str(m.get('content', ''))[:200]}"
                for m in self.short_term_messages[-_SHORT_TERM_RECALL:]
            ]
            blocks.append("【近期会话记忆】\n" + "\n".join(lines))
        if self.long_term_prompt:
            blocks.append(self.long_term_prompt)
        return "\n\n".join(blocks)


class EmployeeMemoryManager:
    def __init__(self, scope: MemoryScope) -> None:
        self.scope = scope

    # ---- recall ----
    def recall(
        self,
        task: str,
        *,
        user_id: Any = 0,
        session_id: str | None = None,
        top_k: int = _LONG_TERM_TOPK,
    ) -> MemoryContext:
        short = self._recall_short_term(session_id) if self.scope.short_term_enabled else []
        long_prompt, hits = ("", [])
        if self.scope.long_term_enabled:
            long_prompt, hits = self._recall_long_term(task, user_id=user_id, top_k=top_k)
        return MemoryContext(long_term_prompt=long_prompt, short_term_messages=short, hits=hits)

    def _recall_short_term(self, session_id: str | None) -> list[dict[str, str]]:
        sid = str(session_id or "").strip()
        if not sid:
            return []
        try:
            from app.services.conversation_service import ConversationService

            rows = ConversationService().get_session_messages(sid, limit=50)
        except Exception:  # noqa: BLE001 - 记忆读写是尽力而为的旁路,任何失败都不能搞崩员工回复
            logger.debug("short-term recall skipped (session=%s)", sid, exc_info=True)
            return []
        out: list[dict[str, str]] = []
        for row in rows or []:
            try:
                role = str(row[3] or "user")
                content = str(row[4] or "")
                meta_raw = row[6] or ""
            except (IndexError, TypeError):
                continue
            if not self._meta_matches_employee(meta_raw):
                continue
            if content:
                out.append({"role": role, "content": content})
        return out[-_SHORT_TERM_RECALL:]

    def _meta_matches_employee(self, meta_raw: Any) -> bool:
        if not meta_raw:
            return True
        try:
            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
        except (json.JSONDecodeError, TypeError):
            return True
        if not isinstance(meta, dict):
            return True
        emp = str(meta.get("employee_id") or "").strip()
        return (not emp) or emp == self.scope.employee_id

    def _recall_long_term(
        self, task: str, *, user_id: Any, top_k: int
    ) -> tuple[str, list[dict[str, Any]]]:
        index_ns = self.scope.long_term_index(user_id)
        query_text = str(task or "").strip()
        if not query_text:
            return "", []
        try:
            from app.application.user_memory_vector_app_service import (
                get_user_memory_rag_app_service,
            )

            rag = get_user_memory_rag_app_service()
            res = rag.query(index_ns, query_text, top_k=top_k)
            if not res.get("success"):
                return "", []
            hits = res.get("hits") or []
            if not hits:
                return "", []
            prompt = rag.format_for_prompt(index_ns, query_text, hits)
            return prompt, hits
        except Exception:  # noqa: BLE001 - 记忆读写是尽力而为的旁路,任何失败都不能搞崩员工回复
            logger.debug("long-term recall skipped (ns=%s)", index_ns, exc_info=True)
            return "", []

    # ---- remember ----
    def remember(
        self,
        task: str,
        summary: str,
        *,
        user_id: Any = 0,
        session_id: str | None = None,
        success: bool = True,
    ) -> None:
        if self.scope.short_term_enabled:
            self._remember_short_term(task, summary, user_id=user_id, session_id=session_id)
        if self.scope.long_term_enabled:
            self._remember_long_term(task, summary, user_id=user_id, success=success)

    def _remember_short_term(
        self, task: str, summary: str, *, user_id: Any, session_id: str | None
    ) -> None:
        sid = str(session_id or "").strip()
        if not sid:
            return
        meta = json.dumps({"employee_id": self.scope.employee_id}, ensure_ascii=False)
        uid = str(user_id if user_id is not None else "")
        try:
            from app.services.conversation_service import ConversationService

            svc = ConversationService()
            if task:
                svc.save_message(
                    sid, uid, "user", str(task)[:4000], intent=self.scope.employee_id, metadata=meta
                )
            if summary:
                svc.save_message(
                    sid,
                    uid,
                    "assistant",
                    str(summary)[:4000],
                    intent=self.scope.employee_id,
                    metadata=meta,
                )
        except Exception:  # noqa: BLE001 - 记忆读写是尽力而为的旁路,任何失败都不能搞崩员工回复
            logger.debug("short-term remember skipped (session=%s)", sid, exc_info=True)

    def _remember_long_term(self, task: str, summary: str, *, user_id: Any, success: bool) -> None:
        index_ns = self.scope.long_term_index(user_id)
        content = (
            f"[employee_task] employee={self.scope.employee_id}; success={success}; "
            f"task={str(task or '').strip()[:200]}; outcome={str(summary or '').strip()[:400]}"
        )
        try:
            from app.application.user_memory_vector_app_service import (
                UserMemoryVectorChunk,
                get_user_memory_vector_ingest_app_service,
            )

            chunk = UserMemoryVectorChunk(
                chunk_id=uuid.uuid4().hex,
                content=content,
                metadata={
                    "source": "employee_task",
                    "employee_id": self.scope.employee_id,
                    "success": success,
                    "task_preview": str(task or "").strip()[:200],
                    "ts": datetime.now().isoformat(),
                },
            )
            get_user_memory_vector_ingest_app_service().ingest_chunks(index_ns, [chunk])
        except Exception:  # noqa: BLE001 - 记忆读写是尽力而为的旁路,任何失败都不能搞崩员工回复
            logger.debug("long-term remember skipped (ns=%s)", index_ns, exc_info=True)


__all__ = ["EmployeeMemoryManager", "MemoryContext"]
