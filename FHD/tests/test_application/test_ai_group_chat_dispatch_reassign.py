"""派工误判验收与防止未经核对的跨员工重复执行。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_group_chat_service import AiGroupChatService


def _svc(tmp_path: Path) -> AiGroupChatService:
    # 不传 employee_executor_fn，使用正式超级员工派工路径。
    return AiGroupChatService(
        storage_root=tmp_path,
        department_loader=lambda: {},
        employee_loader=lambda: [],
    )


def _patch_invoke(svc: AiGroupChatService, replies: dict[str, dict]) -> list[str]:
    calls: list[str] = []

    def fake(*, employee_id: str, task: str, input_data: dict, user_id: int) -> dict:
        calls.append(employee_id)
        return dict(replies.get(employee_id, {"success": False, "summary": "未知员工"}))

    svc._invoke_super_employee_task = fake
    return calls


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
async def test_codex_refusal_cannot_authorize_second_employee(tmp_path: Path):
    svc = _svc(tmp_path)
    calls = _patch_invoke(
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
    assert report["success"] is False
    assert report["employee_id"] == "codex-super-employee"
    assert "reassigned_from" not in report
    assert report["status"] in {"failed", "blocked"}
    assert calls == ["codex-super-employee"]


@pytest.mark.asyncio
async def test_codex_refusal_remains_failed_without_unverified_reassignment(tmp_path: Path):
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


@pytest.mark.asyncio
async def test_unknown_original_dispatch_cannot_start_replacement(tmp_path: Path):
    svc = _svc(tmp_path)
    calls = _patch_invoke(
        svc,
        {
            "codex-super-employee": {
                "success": False,
                "status": "failed",
                "summary": "不能执行命令",
                "reconciliation_required": True,
                "dispatch_request_id": "original",
            },
            "claude-super-employee": {"success": True, "status": "done"},
        },
    )
    report = await _run(svc, "codex-super-employee")
    assert calls == ["codex-super-employee"]
    assert report["status"] == "unknown"
    assert report["success"] is False
    assert report["reconciliation_required"] is True
    assert report["raw"]["dispatch_request_id"] == "original"
    assert report["raw"]["reconciliation_required"] is True


def test_uncertain_relay_create_never_falls_back(tmp_path: Path):
    svc = _svc(tmp_path)
    calls: list[str] = []

    class Relay:
        def list_desktops(self, *, user_id):
            return [{"relay_id": "r1", "status": "paired"}]

        def create_task(self, **kwargs):
            calls.append("create")
            raise OSError("acknowledgement lost")

    def forbidden(_employee_id):
        raise AssertionError("Uncertain dispatch must not start another executor")

    svc._mobile_relay_service = Relay
    svc._super_employee_service = forbidden
    result = svc._invoke_super_employee_task(
        employee_id="codex-super-employee",
        task="原工单",
        input_data={"work_order_id": "wo1"},
        user_id=1,
    )
    assert calls == ["create"]
    assert result["status"] == "unknown"
    assert result["reconciliation_required"] is True
