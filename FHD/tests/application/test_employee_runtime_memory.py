"""EmployeeMemoryManager / MemoryContext 单元测试（I/O mock）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.application.employee_runtime.memory import EmployeeMemoryManager, MemoryContext
from app.domain.employee.memory_scope import MemoryScope


class TestMemoryContext:
    def test_has_content(self):
        empty = MemoryContext()
        assert empty.has_content is False
        filled = MemoryContext(short_term_messages=[{"role": "user", "content": "hi"}])
        assert filled.has_content is True

    def test_as_system_suffix(self):
        ctx = MemoryContext(
            short_term_messages=[{"role": "user", "content": "task"}],
            long_term_prompt="【长期记忆】foo",
        )
        suffix = ctx.as_system_suffix()
        assert "近期会话记忆" in suffix
        assert "长期记忆" in suffix


class TestEmployeeMemoryManager:
    def test_recall_short_term_filters_by_employee(self):
        scope = MemoryScope(employee_id="emp-x")
        mgr = EmployeeMemoryManager(scope)
        rows = [
            (1, "s", "u", "user", "hello", None, json.dumps({"employee_id": "emp-x"})),
            (2, "s", "u", "user", "skip", None, json.dumps({"employee_id": "other"})),
        ]
        with patch("app.services.conversation_service.ConversationService") as conv_cls:
            conv_cls.return_value.get_session_messages.return_value = rows
            ctx = mgr.recall("task", session_id="sid-1")
        assert len(ctx.short_term_messages) == 1
        assert ctx.short_term_messages[0]["content"] == "hello"

    def test_recall_long_term_mocked(self):
        scope = MemoryScope(employee_id="emp-y", long_term_enabled=True)
        mgr = EmployeeMemoryManager(scope)
        rag = MagicMock()
        rag.query.return_value = {"success": True, "hits": [{"text": "hit1"}]}
        rag.format_for_prompt.return_value = "prompt-block"
        with patch(
            "app.application.user_memory_vector_app_service.get_user_memory_rag_app_service",
            return_value=rag,
        ):
            ctx = mgr.recall("search task", user_id=1)
        assert ctx.long_term_prompt == "prompt-block"
        assert len(ctx.hits) == 1

    def test_remember_short_term_calls_conversation_service(self):
        scope = MemoryScope(employee_id="emp-z")
        mgr = EmployeeMemoryManager(scope)
        svc = MagicMock()
        with patch("app.services.conversation_service.ConversationService", return_value=svc):
            mgr.remember("do thing", "done", user_id=5, session_id="sess")
        assert svc.save_message.call_count == 2

    def test_recall_empty_session_skips_db(self):
        scope = MemoryScope(employee_id="e")
        mgr = EmployeeMemoryManager(scope)
        ctx = mgr.recall("t", session_id="")
        assert ctx.short_term_messages == []
