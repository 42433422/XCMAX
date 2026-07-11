"""Release-gate regression for the super-employee validation boundary."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from app.application.super_employee_service import (
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    SuperEmployeeService,
)


class _AsyncBytesReader:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    async def read(self) -> bytes:
        return b""


class _CompletedAsyncProcess:
    def __init__(self, events: list[dict[str, object]], *, returncode: int = 0) -> None:
        self.stdout = _AsyncBytesReader(
            [(json.dumps(event) + "\n").encode("utf-8") for event in events]
        )
        self.stderr = _AsyncBytesReader([])
        self.returncode = returncode
        self.pid = 123

    async def wait(self) -> int:
        return self.returncode


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


@pytest.mark.asyncio
async def test_stream_json_drops_only_replayed_final_result(tmp_path) -> None:
    service = SuperEmployeeService(CURSOR_PROFILE, storage_root=tmp_path)
    process = _CompletedAsyncProcess(
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "OK"}]},
            },
            {"type": "result", "result": "OK"},
        ]
    )

    with patch(
        "app.application.super_employee_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        events = [
            event
            async for event in service._run_cli_streaming("/fake/cursor", "prompt", str(tmp_path))
        ]

    assert events == [
        {"type": "token", "text": "OK"},
        {"type": "done", "text": "OK"},
    ]


@pytest.mark.asyncio
async def test_stream_json_keeps_legitimate_identical_delta_tokens(tmp_path) -> None:
    service = SuperEmployeeService(CURSOR_PROFILE, storage_root=tmp_path)
    process = _CompletedAsyncProcess(
        [
            {"type": "content_block_delta", "delta": {"text": "哈"}},
            {"type": "content_block_delta", "delta": {"text": "哈"}},
            {"type": "result", "result": "哈哈"},
        ]
    )

    with patch(
        "app.application.super_employee_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        events = [
            event
            async for event in service._run_cli_streaming("/fake/cursor", "prompt", str(tmp_path))
        ]

    assert [event for event in events if event["type"] == "token"] == [
        {"type": "token", "text": "哈"},
        {"type": "token", "text": "哈"},
    ]
    assert events[-1] == {"type": "done", "text": "哈哈"}


@pytest.mark.asyncio
async def test_stream_json_keeps_distinct_assistant_and_result_text(tmp_path) -> None:
    service = SuperEmployeeService(CURSOR_PROFILE, storage_root=tmp_path)
    process = _CompletedAsyncProcess(
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello "}]},
            },
            {"type": "result", "result": "world"},
        ]
    )

    with patch(
        "app.application.super_employee_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        events = [
            event
            async for event in service._run_cli_streaming("/fake/cursor", "prompt", str(tmp_path))
        ]

    assert [event for event in events if event["type"] == "token"] == [
        {"type": "token", "text": "hello "},
        {"type": "token", "text": "world"},
    ]
    assert events[-1] == {"type": "done", "text": "hello world"}


@pytest.mark.asyncio
async def test_stream_json_turns_structured_subscription_failure_into_error(tmp_path) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    provider_error = (
        "Your organization has disabled Claude subscription access for Claude Code · "
        "Use an Anthropic API key instead, or ask your admin to enable access"
    )
    process = _CompletedAsyncProcess(
        [
            {
                "type": "assistant",
                "error": "oauth_org_not_allowed",
                "message": {"content": [{"type": "text", "text": provider_error}]},
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "api_error_status": 403,
                "result": provider_error,
            },
        ],
        returncode=1,
    )

    with patch(
        "app.application.super_employee_service.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        events = [
            event
            async for event in service._run_cli_streaming("/fake/claude", "prompt", str(tmp_path))
        ]

    assert events == [
        {
            "type": "error",
            "message": "Claude 的组织已禁用 CLI 订阅访问，请让组织管理员启用，或在电脑端配置 API Key 后重试。",
            "error_code": "organization_access_disabled",
        }
    ]


def test_zero_exit_stream_failure_is_failed_in_non_stream_path(tmp_path) -> None:
    provider_error = (
        "Your organization has disabled Claude subscription access for Claude Code · "
        "Use an Anthropic API key instead"
    )
    stdout = json.dumps({"type": "result", "result": provider_error})

    def runner(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path, cli_runner=runner)

    reply = service._run_cli_once("/fake/claude", "prompt", str(tmp_path))

    assert "组织已禁用" in reply
    assert service._last_cli_failure["error_code"] == "organization_access_disabled"


def test_failed_conversation_does_not_replace_last_good_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.application.super_employee_service.get_app_data_dir",
        lambda: str(tmp_path),
    )
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    context = {
        "persistent_conversation": True,
        "conversation_id": "thread-1",
        "thread_id": "thread-1",
    }
    key = service._session_key(context)
    service._session_set(key, {"session_id": "good-session"})
    provider_error = (
        "Your organization has disabled Claude subscription access for Claude Code · "
        "Use an Anthropic API key instead, or ask your admin to enable access"
    )
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "error": "oauth_org_not_allowed",
                    "session_id": "failed-session",
                    "message": {"content": [{"type": "text", "text": provider_error}]},
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": True,
                    "api_error_status": 403,
                    "session_id": "failed-session",
                    "result": provider_error,
                }
            ),
        ]
    )

    with (
        patch.object(service, "_cli_workspace", return_value=str(tmp_path)),
        patch.object(
            service,
            "_ensure_session_workspace",
            return_value=(str(tmp_path), "super-employee/claude/thread-1"),
        ),
        patch.object(service, "_run_cli_idle", return_value=(1, stdout, "", "")),
    ):
        reply = service._run_conversation_turn("/fake/claude", "继续", context)

    assert "组织已禁用" in reply
    assert service._last_cli_failure["error_code"] == "organization_access_disabled"
    assert service._session_get(key)["session_id"] == "good-session"
    assert service._last_session_runtime == {}


@pytest.mark.asyncio
async def test_persistent_stream_emits_error_without_done(tmp_path) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    message = "Claude 的组织已禁用 CLI 订阅访问，请让组织管理员启用。"

    def fail_turn(*_args, **_kwargs):
        service._last_cli_failure = {
            "error_code": "organization_access_disabled",
            "message": message,
        }
        return message

    with (
        patch.object(service, "_cli_path", return_value="/fake/claude"),
        patch.object(service, "_run_conversation_turn", side_effect=fail_turn),
    ):
        events = [
            event
            async for event in service.invoke_stream(
                user_id=1,
                message="继续",
                context={"persistent_conversation": True, "conversation_id": "thread-1"},
            )
        ]

    assert events[-1] == {
        "type": "error",
        "message": message,
        "error_code": "organization_access_disabled",
    }
    assert all(event["type"] not in {"token", "done"} for event in events)


def test_conversation_failure_hides_exception_detail(tmp_path) -> None:
    secret = "secret token from subprocess"
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    assert service._cli_runner is subprocess.run

    with patch.object(service, "_run_cli_idle", side_effect=OSError(secret)):
        reply = service._run_conversation_turn("/fake/codex", "分析问题", {})

    assert reply == "Codex CLI 暂时不可用，请稍后重试"
    assert secret not in reply
