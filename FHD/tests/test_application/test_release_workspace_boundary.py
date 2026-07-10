"""Release-gate regression for the super-employee validation boundary."""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from app.application.super_employee_service import CODEX_PROFILE, SuperEmployeeService


def test_verify_workspace_rejects_unregistered_directory(tmp_path) -> None:
    trusted_storage = tmp_path / "state"
    trusted_storage.mkdir()
    unrelated = tmp_path / "customer-files"
    unrelated.mkdir()
    (unrelated / "secret.py").write_text("token = 'secret'\n", encoding="utf-8")
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=trusted_storage)

    ok, message = service._verify_workspace(str(unrelated))

    assert ok is False
    assert message == "拒绝验证未登记的工作区"


@pytest.mark.asyncio
async def test_invoke_stream_hides_dev_loop_exception(tmp_path) -> None:
    secret = "secret stack frame /private/customer.db"
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)

    with (
        patch.object(service, "_cli_path", return_value="/fake/codex"),
        patch.object(service, "_cli_workspace", return_value=str(tmp_path)),
        patch(
            "app.application.super_employee_service.asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError(secret)),
        ),
    ):
        events = [
            event
            async for event in service.invoke_stream(
                user_id=1,
                message="实现一个新功能",
                context={"mode": "code"},
            )
        ]

    assert events[-1] == {"type": "error", "message": "开发任务暂时执行失败，请稍后重试"}
    assert secret not in str(events)


@pytest.mark.asyncio
async def test_cli_start_failure_hides_exception_detail(tmp_path) -> None:
    secret = "secret executable path /private/bin"
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)

    with patch(
        "app.application.super_employee_service.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=OSError(secret)),
    ):
        events = [
            event
            async for event in service._run_cli_streaming("/fake/codex", "prompt", str(tmp_path))
        ]

    assert events == [
        {
            "type": "error",
            "message": "Codex CLI 启动失败，请检查安装与登录状态",
        }
    ]
    assert secret not in str(events)


def test_conversation_failure_hides_exception_detail(tmp_path) -> None:
    secret = "secret token from subprocess"
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    assert service._cli_runner is subprocess.run

    with patch.object(service, "_run_cli_idle", side_effect=OSError(secret)):
        reply = service._run_conversation_turn("/fake/codex", "分析问题", {})

    assert reply == "Codex CLI 暂时不可用，请稍后重试"
    assert secret not in reply
