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

from app.application.message_repository import MessageRepository
from app.application.super_employee import cli as cli_module
from app.application.super_employee.cli import CliExecutionError, CliExecutor
from app.application.super_employee.devices import DeviceSelection
from app.application.super_employee.messages import MessageSynchronizer
from app.application.super_employee.profiles import CODEX_PROFILE
from app.application.super_employee.protocols import CliPorts, MessageSyncPorts
from app.application.super_employee_service import CLAUDE_PROFILE, SuperEmployeeService
from app.domain.app_pure.execution_scope import CONTEXT_TOKEN_KEY


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


@pytest.mark.parametrize("profile", [CODEX_PROFILE, CLAUDE_PROFILE])
def test_public_stream_rejects_nonzero_exit_even_with_final_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile
) -> None:
    service = SuperEmployeeService(profile, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))

    class FailedProcess(_StreamingProcess):
        async def wait(self) -> int:
            self.waited = True
            self.returncode = 23
            return 23

    async def consume() -> tuple[list[dict], FailedProcess]:
        process = FailedProcess()

        async def launch(*args, **kwargs):
            if "--output-last-message" in args:
                Path(args[args.index("--output-last-message") + 1]).write_text("partial file")
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        return await _collect(
            service.invoke_stream(user_id=1, message="描述当前任务", context={"mode": "chat"})
        ), process

    events, process = asyncio.run(consume())
    assert all(event["type"] != "done" for event in events)
    assert events[-1]["error_code"] == "cli_nonzero_exit"
    assert events[-1]["exit_code"] == 23
    assert events[-1]["partial_text"] == ("hello" if profile.cli_stream_json else "partial file")
    assert events[-1]["outcome"] == "unknown"
    assert events[-1]["retryable"] is False
    assert process.waited


def test_public_stream_requires_a_terminal_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))

    async def incomplete(*args):
        yield {"type": "token", "text": "unfinished output"}

    monkeypatch.setattr(service, "_run_cli_streaming", incomplete)
    events = asyncio.run(
        _collect(service.invoke_stream(user_id=1, message="描述当前任务", context={"mode": "chat"}))
    )
    assert events[-1]["type"] == "error"
    assert events[-1]["termination_reason"] == "exit_unknown"
    assert events[-1]["partial_text"] == "unfinished output"
    assert not any(event["type"] == "done" for event in events)


@pytest.mark.parametrize(
    "failure_stage",
    ["initial", "repair", "repair_launch", "verification", "publication", "success"],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_public_development_stages_preserve_failed_work_and_only_clean_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str, streaming: bool
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_dev_loop_enabled", lambda: True)
    monkeypatch.setattr(service, "_prepare_worktree", lambda *args: (str(tmp_path), "fixture"))
    calls, verifications, publications, cleanups = [], [], [], []
    monkeypatch.setenv("XCMAX_DEV_LOOP_MAX_FIX", "1")

    def execute(*args):
        calls.append(args)
        if failure_stage == "repair_launch" and len(calls) > 1:
            raise CliExecutionError("Codex", "launch_failed", started=False)
        if failure_stage == "initial" or (failure_stage == "repair" and len(calls) > 1):
            return (7, "partial work", "fixture failure", "")
        return (0, "generated output", "", "")

    def verify(*args):
        verifications.append(args)
        return (
            failure_stage not in {"repair", "repair_launch", "verification"},
            "verification fixture",
        )

    def publish(*args):
        publications.append(args)
        return (failure_stage != "publication", "publication fixture")

    monkeypatch.setattr(service, "_run_cli_idle", execute)
    monkeypatch.setattr(service, "_verify_workspace", verify)
    monkeypatch.setattr(service, "_commit_and_push", publish)
    monkeypatch.setattr(service, "_remove_worktree", lambda *args: cleanups.append(args))
    kwargs = {
        "user_id": 1,
        "message": "修复登录问题",
        "context": {"mode": "code", "force_cli_direct": True},
    }
    success = failure_stage == "success"
    if streaming:
        events = asyncio.run(_collect(service.invoke_stream(**kwargs)))
        assert events[-1]["type"] == ("done" if success else "error")
        assert any("开发任务完成" in event.get("text", "") for event in events) is success
        result = events[-1]
    else:
        result = service.invoke(**kwargs)
        assert result["assistant_message"]["status"] == ("completed" if success else "failed")
    if not success:
        assert result["error_code"] == (
            "cli_nonzero_exit"
            if failure_stage in {"initial", "repair"}
            else "cli_launch_failed"
            if failure_stage == "repair_launch"
            else f"development_{failure_stage}_failed"
        )
        assert result["partial_text"] == (
            "partial work" if failure_stage in {"initial", "repair"} else "generated output"
        )
        assert result["workspace"] == str(tmp_path)
        assert result["branch"] == "fixture"
        assert result["workspace_preserved"] is True
        assert result["outcome"] == "unknown"
        assert result["retryable"] is False
        assert result["execution_started"] is True
        if not streaming:
            assert result["dispatch"]["accepted"] is True
    assert len(calls) == (2 if failure_stage in {"repair", "repair_launch", "verification"} else 1)
    assert len(verifications) == {"initial": 0, "verification": 2}.get(failure_stage, 1)
    assert len(publications) == int(failure_stage in {"publication", "success"})
    assert len(cleanups) == int(success)


def test_public_conversation_failure_never_replays_or_changes_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_conversation_mode_enabled", lambda: True)
    monkeypatch.setattr(service, "_session_get", lambda key: {"session_id": "existing"})
    monkeypatch.setattr(service, "_session_set", _unexpected)
    calls = []

    def execute(*args):
        calls.append(args)
        return (23, '{"type":"result","result":"partial","session_id":"unconfirmed"}', "", "")

    monkeypatch.setattr(service, "_run_cli_idle", execute)
    result = service.invoke(user_id=1, message="描述当前任务", context={"mode": "chat"})
    assert result["assistant_message"]["status"] == "failed"
    assert result["partial_text"] == "partial"
    assert result["retryable"] is False
    assert len(calls) == 1


def test_public_stream_preserves_successful_stdout_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))

    class StdoutProcess(_StreamingProcess):
        async def readline(self) -> bytes:
            if self._read:
                return b""
            self._read = True
            return b"codex\nvalid final output\ntokens used\n42\n"

    async def launch(*args, **kwargs):
        return StdoutProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    events = asyncio.run(
        _collect(service.invoke_stream(user_id=1, message="描述当前任务", context={"mode": "chat"}))
    )
    assert events[-1]["type"] == "done"
    assert events[-1]["result"]["response"] == "valid final output"


def test_public_stream_io_failure_preserves_partial_text_and_unknown_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SuperEmployeeService(CLAUDE_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))

    class BrokenPipeProcess(_StreamingProcess):
        async def readline(self) -> bytes:
            if self._read:
                raise OSError("fixture read failure")
            return await super().readline()

    async def consume():
        process = BrokenPipeProcess()

        async def launch(*args, **kwargs):
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
        return await _collect(
            service.invoke_stream(user_id=1, message="描述当前任务", context={"mode": "chat"})
        ), process

    events, process = asyncio.run(consume())
    assert all(event["type"] != "done" for event in events)
    assert events[-1]["termination_reason"] == "process_error"
    assert events[-1]["execution_started"] is True
    assert events[-1]["partial_text"] == "hello"
    assert events[-1]["outcome"] == "unknown"
    assert events[-1]["retryable"] is False
    assert process.killed and process.waited


@pytest.mark.parametrize(("git_repo", "branch"), [(True, ""), (True, "feature/task"), (False, "")])
def test_public_development_isolation_failure_does_not_execute_in_git_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_repo: bool, branch: str
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_dev_loop_enabled", lambda: True)
    monkeypatch.setattr(service, "_prepare_worktree", lambda *args: None)
    monkeypatch.setattr(service, "_is_git_repo", lambda path: git_repo)
    exists = Path.exists
    # The test runner's temporary root may itself live inside a checkout.
    monkeypatch.setattr(
        Path, "exists", lambda path: git_repo if path.name == ".git" else exists(path)
    )
    calls = []

    def execute(*args):
        calls.append(args)
        return 0, "non-git task output", "", ""

    monkeypatch.setattr(service, "_run_cli_idle", execute)
    result = service.invoke(
        user_id=1,
        message="修复登录问题",
        context={
            "mode": "code",
            "force_cli_direct": True,
            "branch_context": branch,
        },
    )
    assert len(calls) == (0 if git_repo else 1)
    if git_repo:
        assert result["error_code"] == "development_workspace_unavailable"
        assert result["execution_state"] == "not_started"
        assert result["dispatch"]["accepted"] is False
        assert result["assistant_message"]["status"] == "failed"
    else:
        assert result["assistant_message"]["status"] == "completed"


@pytest.mark.parametrize("inspection_failed", [False, True])
def test_public_development_never_resets_persistent_unconfirmed_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inspection_failed: bool
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    wt = tmp_path / "retained-worktree"
    (wt / ".git").mkdir(parents=True)
    evidence = wt / "evidence.txt"
    evidence.write_text("unconfirmed changes")
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_dev_loop_enabled", lambda: True)
    monkeypatch.setattr(service, "_is_git_repo", lambda path: True)
    monkeypatch.setattr(service, "_relay_persistent_worktree_path", lambda: str(wt))
    monkeypatch.setattr(service, "_run_cli_idle", _unexpected)
    calls = []

    def git(cwd, *args, **kwargs):
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, "base-head", "")
        assert args == ("status", "--porcelain", "--untracked-files=all")
        return subprocess.CompletedProcess(
            args,
            1 if inspection_failed else 0,
            "" if inspection_failed else "?? evidence.txt\n",
            "inspection unavailable" if inspection_failed else "",
        )

    monkeypatch.setattr(service, "_git", git)
    result = service.invoke(
        user_id=1,
        message="修复登录问题",
        context={
            "mode": "code",
            "force_cli_direct": True,
        },
    )
    assert result["error_code"] == (
        "development_workspace_unavailable" if inspection_failed else "development_workspace_dirty"
    )
    assert result["execution_state"] == "not_started"
    assert result["workspace"] == str(wt)
    assert result["workspace_preserved"] is True
    assert result["reconciliation_required"] is True
    assert evidence.read_text() == "unconfirmed changes"
    assert len(calls) == 2


@pytest.mark.parametrize("stage", ["add", "status"])
def test_public_git_publication_stops_at_first_failed_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    calls = []

    def git(cwd, *args, **kwargs):
        calls.append(args[0])
        assert args[0] in {"add", "status"}
        return subprocess.CompletedProcess(
            args, 7 if args[0] == stage else 0, "", "fixture failure"
        )

    monkeypatch.setattr(service, "_git", git)
    ok, diagnostic = service._commit_and_push(str(tmp_path), "fixture", "task")
    assert ok is False
    assert "fixture failure" in diagnostic
    assert calls == (["add"] if stage == "add" else ["add", "status"])


@pytest.mark.parametrize("kind", [CODEX_PROFILE.direct_kind, CODEX_PROFILE.result_kind])
def test_explicit_reply_kinds_never_reenter_legacy_dispatcher_migration(
    tmp_path: Path, kind: str
) -> None:
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    row = {"role": "assistant", "kind": kind, "status": "failed", "body": "调用队列 partial"}
    assert not service._sync.upgrade_legacy_dispatcher_row(row)
    assert row["role"] == "assistant"
    assert row["kind"] == kind


@pytest.mark.parametrize("marker_type", ["directory", "file"])
def test_public_git_probe_failure_cannot_downgrade_a_repository_to_raw_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker_type: str
) -> None:
    root = tmp_path / "repository"
    cwd = root / "subdir"
    cwd.mkdir(parents=True)
    marker = root / ".git"
    if marker_type == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: /fixture/worktree-metadata")
    service = SuperEmployeeService(CODEX_PROFILE, storage_root=tmp_path)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-cli")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(cwd))
    monkeypatch.setattr(service, "_dev_loop_enabled", lambda: True)
    monkeypatch.setattr(
        service,
        "_git",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 128, "", "inspection unavailable"
        ),
    )
    monkeypatch.setattr(service, "_run_cli_idle", _unexpected)
    result = service.invoke(
        user_id=1,
        message="修复登录问题",
        context={
            "mode": "code",
            "force_cli_direct": True,
        },
    )
    assert result["error_code"] == "development_workspace_unavailable"
    assert result["execution_state"] == "not_started"
    assert result["dispatch"]["accepted"] is False
    assert result["workspace"] == str(cwd)
