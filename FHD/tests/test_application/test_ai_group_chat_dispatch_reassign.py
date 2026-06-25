"""派工误判验收 + 改派 Claude 修复的单元测试。

Bug：Codex（只读沙箱）返回 success=True 却在正文说"不能执行命令/权限不足/仅提供方案"，
被 _execute_employee_work 当成验收通过（false acceptance）。
修复：在源头用拒绝短语表判真失败，并自动改派到真能执行的 Claude。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_group_chat_service import AiGroupChatService


def _svc(tmp_path: Path) -> AiGroupChatService:
    # 不传 employee_executor_fn → 走超级员工路径，改派逻辑生效。
    return AiGroupChatService(
        storage_root=tmp_path,
        department_loader=lambda: {},
        employee_loader=lambda: [],
    )


def _patch_invoke(svc: AiGroupChatService, replies: dict[str, dict]) -> None:
    def fake(*, employee_id: str, task: str, input_data: dict, user_id: int) -> dict:
        return dict(replies.get(employee_id, {"success": False, "summary": "未知员工"}))

    svc._invoke_super_employee_task = fake  # type: ignore[assignment]


async def _run(svc: AiGroupChatService, employee_id: str) -> dict:
    return await svc._execute_employee_work(
        group={"id": "g1", "name": "超级开发"},
        member={"employee_id": employee_id, "name": employee_id},
        task="修复登录 bug 并加测试",
        assigned_task="修复登录 bug 并加测试",
        assignment_focus="",
        work_order_id="wo-test",
        user_id=1,
        sender_name="我",
    )


@pytest.mark.asyncio
async def test_codex_cannot_execute_is_reassigned_to_claude(tmp_path: Path):
    svc = _svc(tmp_path)
    _patch_invoke(
        svc,
        {
            "codex-super-employee": {
                "success": True,  # Codex 谎报成功
                "status": "completed",
                "summary": "我只能给出执行方案，不能执行命令（只读沙箱）。",
            },
            "claude-super-employee": {
                "success": True,
                "status": "done",
                "summary": "已修改 auth.py，新增 2 个测试，pytest 全绿。",
            },
        },
    )
    report = await _run(svc, "codex-super-employee")
    assert report["success"] is True
    assert report["employee_id"] == "claude-super-employee"
    assert report["reassigned_from"] == "codex-super-employee"
    assert report["status"] == "done"


@pytest.mark.asyncio
async def test_codex_refusal_with_claude_also_failing_stays_failed(tmp_path: Path):
    svc = _svc(tmp_path)
    _patch_invoke(
        svc,
        {
            "codex-super-employee": {
                "success": True,
                "status": "completed",
                "summary": "权限不足，仅提供方案。",
            },
            "claude-super-employee": {
                "success": False,
                "status": "failed",
                "summary": "执行失败：合并有冲突。",
            },
        },
    )
    report = await _run(svc, "codex-super-employee")
    assert report["success"] is False
    assert report["status"] in {"failed", "blocked"}


@pytest.mark.asyncio
async def test_claude_refusal_marked_failed_without_self_reassign(tmp_path: Path):
    svc = _svc(tmp_path)
    _patch_invoke(
        svc,
        {
            "claude-super-employee": {
                "success": True,
                "status": "completed",
                "summary": "先不动代码，只给出执行方案。",
            }
        },
    )
    report = await _run(svc, "claude-super-employee")
    # Claude 自己拒绝 → 判失败，且不自我改派（避免死循环）。
    assert report["success"] is False
    assert "reassigned_from" not in report
