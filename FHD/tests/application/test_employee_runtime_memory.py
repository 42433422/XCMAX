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
        scope = MemoryScope(employee_id="emp-x", tenant_id=1, long_term_enabled=False)
        mgr = EmployeeMemoryManager(scope)
        meta = {**mgr._metadata(7), "execution_status": "completed"}
        rows = [
            (1, "s", "7", "user", "hello", None, json.dumps(meta)),
            (2, "s", "7", "user", "skip", None, json.dumps({**meta, "employee_id": "other"})),
            (3, "s", "7", "user", "legacy", None, json.dumps({"employee_id": "emp-x"})),
            (4, "s", "8", "user", "foreign", None, json.dumps(meta)),
        ]
        with patch(
            "app.domain.shared_services.conversation_service.ConversationService"
        ) as conv_cls:
            conv_cls.return_value.get_session_messages.return_value = rows
            ctx = mgr.recall("task", session_id="sid-1", user_id=7)
            conv_cls.return_value.get_session_messages.assert_called_once_with(
                "sid-1", limit=50, user_id="7"
            )
        assert len(ctx.short_term_messages) == 1
        assert ctx.short_term_messages[0]["content"] == "hello"
        assert "provenance=unlinked" in ctx.as_system_suffix()

    def test_recall_long_term_mocked(self):
        scope = MemoryScope(employee_id="emp-y", long_term_enabled=True, tenant_id=1)
        mgr = EmployeeMemoryManager(scope)
        rag = MagicMock()
        rag.query.return_value = {"success": True, "hits": [{"text": "hit1"}]}
        rag.format_for_prompt.return_value = "prompt-block"
        with patch(
            "app.application.user_memory_vector_app_service.UserMemoryRagApplicationService",
            return_value=rag,
        ):
            ctx = mgr.recall("search task", user_id=1)
        assert "prompt-block" in ctx.long_term_prompt
        assert "不是已核实的业务结果" in ctx.long_term_prompt
        assert len(ctx.hits) == 1

    def test_remember_short_term_calls_conversation_service(self):
        scope = MemoryScope(employee_id="emp-z", tenant_id=1, long_term_enabled=False)
        mgr = EmployeeMemoryManager(scope)
        svc = MagicMock()
        with patch(
            "app.domain.shared_services.conversation_service.ConversationService", return_value=svc
        ):
            mgr.remember("do thing", "done", user_id=5, session_id="sess")
        assert svc.save_message.call_count == 2
        metadata = json.loads(svc.save_message.call_args.kwargs["metadata"])
        assert metadata["tenant_id"] == "1" and metadata["user_id"] == "5"
        assert metadata["source_component"] == "employee_runtime"
        assert metadata["verified_business_result"] is False
        assert metadata["provenance_status"] == "unlinked"
        assert "run_id" not in metadata

    def test_recall_empty_session_skips_db(self):
        scope = MemoryScope(employee_id="e")
        mgr = EmployeeMemoryManager(scope)
        ctx = mgr.recall("t", session_id="")
        assert ctx.short_term_messages == []
