"""超级员工隔离测试：员工间(storage_subdir) + 用户/会话级(session_key)。"""

from __future__ import annotations

from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.cursor_super_employee_service import CursorSuperEmployeeService
from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
)


def test_three_super_employees_have_distinct_storage(tmp_path) -> None:
    """三个超级员工各自独立 storage_subdir → 消息/会话/worktree 互不串。"""
    subdirs = {p.storage_subdir for p in (CLAUDE_PROFILE, CODEX_PROFILE, CURSOR_PROFILE)}
    assert len(subdirs) == 3
    ids = {p.employee_id for p in (CLAUDE_PROFILE, CODEX_PROFILE, CURSOR_PROFILE)}
    assert ids == {"claude-super-employee", "codex-super-employee", "cursor-super-employee"}


def test_session_key_isolates_by_user(tmp_path) -> None:
    svc = ClaudeSuperEmployeeService(storage_root=tmp_path)
    k1 = svc._session_key({"_scope_user_id": "1"})
    k2 = svc._session_key({"_scope_user_id": "2"})
    assert k1 != k2
    assert "u1" in k1 and "u2" in k2


def test_session_key_isolates_by_conversation(tmp_path) -> None:
    svc = ClaudeSuperEmployeeService(storage_root=tmp_path)
    a = svc._session_key({"_scope_user_id": "1", "conversation_id": "wo-A"})
    b = svc._session_key({"_scope_user_id": "1", "conversation_id": "wo-B"})
    assert a != b
    assert a.endswith("wo-A") and b.endswith("wo-B")


def test_session_key_backward_compat_without_scope(tmp_path) -> None:
    """无作用域信息时退回工具名（不破坏既有单会话）。"""
    svc = CursorSuperEmployeeService(storage_root=tmp_path)
    assert svc._session_key({}) == CURSOR_PROFILE.tool_name


def test_invoke_stamps_scope_user_id(tmp_path) -> None:
    """invoke 把发起用户写进 ctx → 会话键按用户隔离（用 CLI 直答路径捕获）。"""
    captured: dict = {}

    class _Svc(ClaudeSuperEmployeeService):
        def _should_reply_with_cli(self, text, context):  # noqa: ARG002
            captured.update(context)
            return True

        def _cli_reply_body(self, text, context):  # noqa: ARG002
            return "ok"

    svc = _Svc(storage_root=tmp_path)
    svc.invoke(user_id=42, message="你好")
    assert captured.get("_scope_user_id") == "42"
