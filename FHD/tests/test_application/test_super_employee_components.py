"""Regressions for super-employee component boundaries and process ownership."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import httpx
import pytest

from app.application.execution_scope import CONTEXT_TOKEN_KEY
from app.application.message_repository import MessageRepository
from app.application.super_employee import cli as cli_module
from app.application.super_employee.cli import CliExecutor
from app.application.super_employee.devices import DeviceSelection
from app.application.super_employee.messages import MessageSynchronizer
from app.application.super_employee.protocols import CliPorts, MessageSyncPorts
from app.application.super_employee.profiles import CODEX_PROFILE
from app.application.super_employee_service import CLAUDE_PROFILE, SuperEmployeeService


def test_message_repository_encrypts_new_rows_and_reads_legacy_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-only-super-employee-storage-key")
    repository = MessageRepository(tmp_path, "messages")
    legacy = {"user_id": 7, "role": "user", "body": "legacy fixture"}
    repository.messages_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    assert repository.read_all_message_rows() == [legacy]
    assert json.loads(repository.messages_path.read_text(encoding="utf-8")) == legacy

    private_row = {"user_id": 7, "role": "user", "body": "private fixture"}
    repository.append_messages([private_row])
    stored = repository.messages_path.read_text(encoding="utf-8")
    assert "private fixture" not in stored
    assert "enc:v1:" in stored
    assert repository.read_all_message_rows() == [legacy, private_row]


def test_invoke_preserves_the_callers_context(tmp_path: Path) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    context = {"mode": "chat", CONTEXT_TOKEN_KEY: "invalid-test-token"}

    service.invoke(user_id=1, message="你好", context=context)

    assert context == {"mode": "chat", CONTEXT_TOKEN_KEY: "invalid-test-token"}
    assert "invalid-test-token" not in service._messages_path.read_text(encoding="utf-8")


def test_stream_preserves_the_callers_context(tmp_path: Path) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    context = {"mode": "chat", CONTEXT_TOKEN_KEY: "invalid-test-token"}

    async def consume() -> list[dict]:
        return [
            event
            async for event in service.invoke_stream(user_id=1, message="你好", context=context)
        ]

    assert asyncio.run(consume())[-1]["type"] == "done"
    assert context == {"mode": "chat", CONTEXT_TOKEN_KEY: "invalid-test-token"}


def test_para_polling_tolerates_a_rejected_task_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_TOKEN", "test-token")
    monkeypatch.setenv("XCMAX_CLAUDE_SUPER_EMPLOYEE_PARA_API_URL", "https://para.test")
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "offline"}))
    service = SuperEmployeeService(
        CLAUDE_PROFILE,
        storage_root=tmp_path,
        http_client_factory=lambda: httpx.Client(transport=transport),
    )

    assert service._fetch_para_task("existing-task") is None


class _StreamingProcess:
    def __init__(self, *, blocked_by_stderr: bool = False) -> None:
        self.returncode: int | None = None
        self.killed = False
        self.waited = False
        self._read = False
        self._drained = asyncio.Event()
        self._blocked_by_stderr = blocked_by_stderr
        self.stdout = self
        self.stderr = _Stderr(self._drained)

    async def readline(self) -> bytes:
        if self._blocked_by_stderr:
            await self._drained.wait()
        if self._read:
            self.returncode = 0
            return b""
        self._read = True
        return b'{"type":"content_block_delta","delta":{"text":"hello"}}\n'

    async def wait(self) -> int:
        self.waited = True
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.killed = True


class _Stderr:
    def __init__(self, drained: asyncio.Event) -> None:
        self._drained = drained

    async def read(self, size: int = -1) -> bytes:
        self._drained.set()
        return b""


def test_stream_drains_stderr_while_reading_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)

    async def consume() -> tuple[list[dict], _StreamingProcess]:
        process = _StreamingProcess(blocked_by_stderr=True)

        async def launch(*args: object, **kwargs: object) -> _StreamingProcess:
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        events = await asyncio.wait_for(
            _collect(service._run_cli_streaming("fake-cli", "prompt", str(tmp_path))), timeout=0.5
        )
        return events, process

    events, process = asyncio.run(consume())
    assert events[-1] == {"type": "done", "text": "hello"}
    assert process.waited


def test_closing_a_stream_kills_and_reaps_the_owned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)

    async def close_after_one_token() -> _StreamingProcess:
        process = _StreamingProcess()

        async def launch(*args: object, **kwargs: object) -> _StreamingProcess:
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        stream = service._run_cli_streaming("fake-cli", "prompt", str(tmp_path))
        assert await anext(stream) == {"type": "token", "text": "hello"}
        await stream.aclose()
        return process

    process = asyncio.run(close_after_one_token())
    assert process.killed
    assert process.waited


async def _collect(stream: AsyncIterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event async for event in stream]


def test_cli_component_runs_with_only_its_process_ports(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert kwargs["cwd"] == str(tmp_path)
        return subprocess.CompletedProcess(cmd, 0, '{"type":"result","result":"done"}', "")

    executor = CliExecutor(
        CLAUDE_PROFILE,
        CliPorts(
            runner=lambda: run,
            apply_scope=lambda cmd: [*cmd[:-1], "--fixture-scope", cmd[-1]],
            environment=lambda: {},
            idle_timeout=lambda: 15.0,
            hard_cap=lambda: 60.0,
            run_idle=_unexpected,
        ),
    )

    assert executor.run_cli_once("fake-cli", "task", str(tmp_path)) == "done"
    assert calls[0][-2:] == ["--fixture-scope", "task"]


def test_device_selection_needs_no_http_or_service_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCMAX_CODEX_SUPER_EMPLOYEE_PARA_FORCE_TIER", raising=False)
    monkeypatch.delenv("MODSTORE_PARA_FORCE_TIER", raising=False)
    selection = DeviceSelection(CODEX_PROFILE)
    devices = [
        {
            "id": "primary",
            "isPrimary": True,
            "status": "online",
            "capabilities": {"codex_cli": True},
        },
        {"id": "worker", "status": "online", "capabilities": {"codex_cli": True}},
        {"id": "offline", "status": "offline", "capabilities": {"codex_cli": True}},
    ]

    tier, selected = selection.select_devices_by_tier(devices, {"raw_context": {"para_tier": 2}})

    assert tier == 2
    assert [device["id"] for device in selected] == ["worker"]
    assert len(devices) == 3


def test_result_projection_uses_repository_without_fetching_or_running_cli(tmp_path: Path) -> None:
    repository = MessageRepository(tmp_path, "messages")
    sync = MessageSynchronizer(
        CODEX_PROFILE,
        repository,
        MessageSyncPorts(
            fetch_task=_unexpected,
            direct_reply=_unexpected,
            should_reply=_unexpected,
            compose_reply=_unexpected,
            refresh=_unexpected,
            upsert_result=_unexpected,
            write_rows=_unexpected,
        ),
    )
    task = {
        "id": "task-1",
        "status": "completed",
        "subtasks": [{"id": "sub-1", "status": "completed", "logs": [{"content": "verified"}]}],
    }
    dispatch = {"dispatch_request_id": "request-1"}
    rows: list[dict[str, Any]] = []

    assert sync.upsert_result_messages(user_id=1, dispatch_row=dispatch, task=task, rows=rows)
    assert not sync.upsert_result_messages(user_id=1, dispatch_row=dispatch, task=task, rows=rows)
    assert len(rows) == 1
    assert rows[0]["body"] == "verified"
    assert rows[0]["kind"] == CODEX_PROFILE.result_kind


def test_stream_hard_cap_is_checked_even_when_stdout_does_not_stall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter((0.0, 0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr(cli_module, "time", SimpleNamespace(monotonic=lambda: next(ticks, 2.0)))
    executor = CliExecutor(
        CLAUDE_PROFILE,
        CliPorts(
            runner=lambda: subprocess.run,
            apply_scope=lambda cmd: cmd,
            environment=lambda: {},
            idle_timeout=lambda: 0.0,
            hard_cap=lambda: 1.0,
            run_idle=_unexpected,
        ),
    )

    async def consume() -> tuple[list[dict[str, Any]], _StreamingProcess]:
        process = _StreamingProcess()

        async def launch(*args: object, **kwargs: object) -> _StreamingProcess:
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        return await _collect(
            executor.run_cli_streaming("fake-cli", "task", str(tmp_path))
        ), process

    events, process = asyncio.run(consume())
    assert events[0] == {"type": "token", "text": "hello"}
    assert events[-1]["type"] == "error"
    assert "运行超过" in events[-1]["message"]
    assert process.killed and process.waited


def test_closing_the_public_stream_propagates_cleanup_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fake-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))

    async def close() -> None:
        process = _StreamingProcess()

        async def launch(*args: object, **kwargs: object) -> _StreamingProcess:
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        stream = service.invoke_stream(user_id=1, message="explain tests", context={"mode": "chat"})
        assert (await anext(stream))["type"] == "status"
        assert (await anext(stream))["type"] == "token"
        await stream.aclose()
        assert process.killed and process.waited

    asyncio.run(close())


def _unexpected(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail("The component crossed an unrelated effect boundary")
