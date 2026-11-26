"""Real local CLI children verify exit/partial-output receipts without a model call."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.codex_super_employee_service import CodexSuperEmployeeService
from app.application.super_employee.cli import CliExecutionError, CliExecutor
from app.application.super_employee.development import DevelopmentWorkflow
from app.application.super_employee.profiles import CLAUDE_PROFILE, CODEX_PROFILE
from app.application.super_employee.protocols import (
    CliPorts,
    DevelopmentPorts,
    WorktreePorts,
)


@pytest.fixture
def child(tmp_path):
    script = tmp_path / "cli_child.py"
    script.write_text(
        """import json, sys, time
from pathlib import Path
mode, output, code = sys.argv[1:]
if mode in ('file', 'hang'):
    Path(output).write_text('partial reply', encoding='utf-8')
print(json.dumps({'type':'result','result':'partial reply'}) if mode == 'json' else 'partial reply', flush=True)
print('synthetic-stderr-secret', file=sys.stderr, flush=True)
if mode == 'hang':
    time.sleep(30)
sys.exit(int(code))
""",
        encoding="utf-8",
    )
    return script


def executor(child, mode, code, *, hard_cap=20):
    profile = replace(
        CLAUDE_PROFILE if mode == "json" else CODEX_PROFILE,
        cli_command_builder=lambda cli, prompt, output, cwd: [
            sys.executable,
            "-u",
            str(child),
            mode,
            str(output),
            str(code),
        ],
    )
    runtime = CliExecutor(
        profile,
        CliPorts(
            runner=lambda: subprocess.run,
            apply_scope=lambda cmd: cmd,
            environment=lambda: None,
            idle_timeout=lambda: 0,
            hard_cap=lambda: hard_cap,
            run_idle=lambda *args: runtime.run_cli_idle(*args),
        ),
    )
    return runtime


@pytest.mark.parametrize("mode", ["file", "stdout", "json"])
@pytest.mark.parametrize("code", [0, 7])
def test_sync_receipt_requires_zero_exit_even_with_partial_output(child, tmp_path, mode, code):
    runtime = executor(child, mode, code)
    if code == 0:
        assert runtime.run_cli_once(sys.executable, "task", str(tmp_path)) == "partial reply"
    else:
        with pytest.raises(CliExecutionError) as raised:
            runtime.run_cli_once(sys.executable, "task", str(tmp_path))
        error = raised.value
        assert error.receipt["exit_code"] == 7
        assert error.receipt["partial_text"] == "partial reply"
        assert error.receipt["success"] is False and error.receipt["retryable"] is False
        assert error.receipt["outcome"] == "unknown"
        assert "synthetic-stderr-secret" not in error.body
        assert "synthetic-stderr-secret" not in json.dumps(error.event())


@pytest.mark.parametrize("mode", ["file", "stdout", "json"])
@pytest.mark.parametrize("code", [0, 9])
def test_stream_receipt_uses_real_exit_and_never_promotes_partial_text(child, tmp_path, mode, code):
    runtime = executor(child, mode, code)

    async def collect():
        return [
            event
            async for event in runtime.run_cli_streaming(sys.executable, "task", str(tmp_path))
        ]

    events = asyncio.run(collect())
    assert "synthetic-stderr-secret" not in json.dumps(events)
    if code == 0:
        assert events[-1]["type"] == "done"
    else:
        assert all(event["type"] != "done" for event in events)
        assert events[-1]["type"] == "error" and events[-1]["exit_code"] == 9
        assert events[-1]["partial_text"].strip() == "partial reply"
        assert events[-1]["reconciliation_required"] is True


@pytest.mark.parametrize("streaming", [False, True])
def test_timeout_keeps_partial_output_and_cannot_complete(child, tmp_path, streaming):
    runtime = executor(child, "hang", 0, hard_cap=0.05)
    if streaming:

        async def collect():
            return [
                event
                async for event in runtime.run_cli_streaming(sys.executable, "task", str(tmp_path))
            ]

        events = asyncio.run(collect())
        assert events[-1]["type"] == "error" and not any(e["type"] == "done" for e in events)
        result = events[-1]
    else:
        with pytest.raises(CliExecutionError) as raised:
            runtime.run_cli_once(sys.executable, "task", str(tmp_path))
        result = raised.value.receipt
    assert result["partial_text"] == "partial reply"
    assert result["error_code"] == "cli_timeout"
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert "synthetic-stderr-secret" not in json.dumps(result)


def test_missing_exit_code_is_not_assumed_success(child, tmp_path):
    runtime = executor(child, "file", 0)
    runtime._ports = replace(
        runtime._ports,
        runner=lambda: lambda *args, **kwargs: SimpleNamespace(stdout="partial reply"),
    )
    with pytest.raises(CliExecutionError) as raised:
        runtime.run_cli_once(sys.executable, "task", str(tmp_path))
    assert raised.value.receipt["exit_code"] is None
    assert raised.value.receipt["termination_reason"] == "exit_unknown"
    assert raised.value.receipt["outcome"] == "unknown"


@pytest.fixture
def failed_service(child, tmp_path, monkeypatch):
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        output = cmd[cmd.index("--output-last-message") + 1]
        return subprocess.run(
            [sys.executable, str(child), "file", output, "7"],
            text=True,
            capture_output=True,
            cwd=kwargs["cwd"],
            check=False,
        )

    service = CodexSuperEmployeeService(storage_root=tmp_path / "messages", codex_cli_runner=run)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-xiaox")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_is_task_intent", lambda text, context: False)
    monkeypatch.setattr(service, "_should_reply_with_cli", lambda text, context: True)
    return service, calls


@pytest.mark.parametrize("fallback", [False, True])
def test_sync_service_and_persisted_messages_remain_failed(failed_service, monkeypatch, fallback):
    service, calls = failed_service
    if fallback:
        monkeypatch.setattr(service, "_should_reply_with_cli", lambda text, context: False)
        monkeypatch.setattr(
            service,
            "_dispatch",
            lambda request: {
                "accepted": False,
                "queued": False,
                "status": "dispatch_error",
                "safe_to_fallback": True,
            },
        )
    result = service.invoke(user_id=1, message="Explain sorting algorithms")
    assert result["dispatch"]["status"] == "failed"
    assert result["dispatch"]["success"] is False and result["dispatch"]["retryable"] is False
    assert result["assistant_message"]["status"] == "failed"
    assert "partial reply" in result["assistant_message"]["body"]
    assert "synthetic-stderr-secret" not in json.dumps(result)
    assert service.list_messages(user_id=1)[-1]["status"] == "failed" and len(calls) == 1


@pytest.mark.parametrize("status", ["failed", "dispatch_unknown"])
def test_reading_history_preserves_failed_receipts_without_running_cli(failed_service, status):
    service, calls = failed_service
    request_id, task_id = "original-cli-request", "original-cli-task"
    receipt = {
        "success": False,
        "status": status,
        "outcome": "unknown",
        "error_code": "cli_timeout",
        "request_id": request_id,
        "task_id": task_id,
        "partial_text": "partial reply",
        "retryable": False,
        "reconciliation_required": True,
    }
    rows = [
        service._message_row(
            user_id=1,
            role="user",
            body="Explain sorting algorithms",
            created_at="2026-11-21T00:00:00Z",
            request_id="pending-reply",
            status="sent",
        ),
        service._message_row(
            user_id=1,
            role="user",
            body="Explain sorting algorithms",
            created_at="2026-11-21T00:00:01Z",
            request_id=request_id,
            status="sent",
        ),
        service._message_row(
            user_id=1,
            role="assistant",
            body="任务效果未确认；partial reply",
            created_at="2026-11-21T00:00:02Z",
            request_id=request_id,
            status=status,
            extra={
                "kind": service._p.direct_kind,
                "task_id": task_id,
                "cli_execution": receipt,
                "reconciliation_required": True,
            },
        ),
    ]
    service._append_messages(rows)
    for _ in range(2):
        history = service.list_messages(user_id=1)
        assert len(history) == len(rows)
        original = history[-1]
        assert original["status"] == status
        assert original["dispatch_request_id"] == request_id and original["task_id"] == task_id
        assert original["body"] == rows[-1]["body"]
        assert service._messages.read_all_message_rows() == rows
        assert calls == []


def test_message_history_never_starts_a_cli_backfill(failed_service):
    service, calls = failed_service
    service._append_messages(
        [
            service._message_row(
                user_id=1,
                role="user",
                body="Explain sorting algorithms",
                created_at="2026-11-21T00:00:00Z",
                request_id="pending-reply",
                status="sent",
            )
        ]
    )
    first = service.list_messages(user_id=1)
    assert service.list_messages(user_id=1) == first
    assert len(first) == 1 and first[0]["status"] == "sent"
    assert first[0]["role"] == "user"
    assert calls == []


def test_failed_local_request_is_not_replayed_after_service_restart(failed_service, tmp_path):
    service, calls = failed_service
    context = {"request_id": "failed-local-request"}
    first = service.invoke(user_id=1, message="Explain sorting algorithms", context=context)
    resumed_service = CodexSuperEmployeeService(
        storage_root=tmp_path / "messages",
        codex_cli_runner=lambda *args, **kwargs: pytest.fail("failed request replayed the CLI"),
    )

    resumed = resumed_service.invoke(
        user_id=1, message="Explain sorting algorithms", context=context
    )

    assert len(calls) == 1
    assert first["dispatch"]["status"] == resumed["dispatch"]["status"] == "failed"
    assert resumed["dispatch"]["reconciliation_required"] is True
    assert "synthetic-stderr-secret" not in json.dumps(resumed)


@pytest.mark.parametrize(
    ("failure", "error_code", "exit_code"),
    [
        (OSError("synthetic-system-secret"), "cli_execution_failed", None),
        (
            subprocess.CalledProcessError(23, "fixture-cli", stderr="synthetic-system-secret"),
            "cli_nonzero_exit",
            23,
        ),
        (
            subprocess.TimeoutExpired("fixture-cli", 45, stderr="synthetic-system-secret"),
            "cli_timeout",
            None,
        ),
    ],
)
def test_service_stream_exception_keeps_receipt_without_raw_diagnostics(
    tmp_path, monkeypatch, failure, error_code, exit_code
):
    service = CodexSuperEmployeeService(storage_root=tmp_path / "messages")
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-codex")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_is_task_intent", lambda text, context: False)

    async def interrupted(*args):
        yield {"type": "token", "text": "partial reply"}
        raise failure

    monkeypatch.setattr(service, "_run_cli_streaming", interrupted)

    async def collect():
        return [
            event
            async for event in service.invoke_stream(
                user_id=1, message="Explain sorting algorithms"
            )
        ]

    events = asyncio.run(collect())
    assert events[-1]["error_code"] == error_code
    assert events[-1]["exit_code"] == exit_code
    assert events[-1]["partial_text"] == "partial reply"
    assert events[-1]["outcome"] == "unknown"
    assert events[-1]["reconciliation_required"] is True
    assert not any(event["type"] == "done" for event in events)
    assert "synthetic-system-secret" not in json.dumps(events)


@pytest.mark.parametrize("missing_receipt", [False, True])
def test_service_stream_requires_successful_terminal_receipt(
    child, tmp_path, monkeypatch, missing_receipt
):
    service = CodexSuperEmployeeService(storage_root=tmp_path / "messages")
    runtime = executor(child, "file", 7)
    monkeypatch.setattr(service, "_cli_path", lambda: "fixture-xiaox")
    monkeypatch.setattr(service, "_cli_workspace", lambda context: str(tmp_path))
    monkeypatch.setattr(service, "_is_task_intent", lambda text, context: False)

    async def tokens_only(*args):
        yield {"type": "token", "text": "partial reply"}

    monkeypatch.setattr(
        service,
        "_run_cli_streaming",
        tokens_only if missing_receipt else runtime.run_cli_streaming,
    )

    async def collect():
        return [
            event
            async for event in service.invoke_stream(
                user_id=1, message="Explain sorting algorithms"
            )
        ]

    events = asyncio.run(collect())
    assert events[-1]["type"] == "error" and all(e["type"] != "done" for e in events)
    assert events[-1]["partial_text"] == "partial reply"
    assert events[-1]["outcome"] == "unknown"
    assert events[-1]["retryable"] is False
    assert "synthetic-stderr-secret" not in json.dumps(events)


def test_failed_coding_does_not_verify_retry_or_publish(child, tmp_path):
    effects = []
    runtime = executor(child, "file", 7)
    workflow = DevelopmentWorkflow(
        CODEX_PROFILE,
        WorktreePorts(
            git=lambda *a, **k: None,
            is_git_repo=lambda path: True,
            resolve_branch=lambda *a: "",
            persistent_path=lambda: "",
        ),
        DevelopmentPorts(
            prepare=lambda *args: (str(tmp_path), "fixture-branch"),
            verify=lambda path: effects.append("verify"),
            commit=lambda *args: effects.append("publish"),
            remove=lambda *args: effects.append("cleanup"),
            run_once=runtime.run_cli_once,
            work_prompt=lambda *args: "task",
            fix_prompt=lambda *args: "repair",
            hard_cap=lambda: 20,
        ),
    )
    with pytest.raises(CliExecutionError) as raised:
        workflow.run_dev_task_loop(sys.executable, "task", str(tmp_path))
    assert effects == []
    assert raised.value.receipt["exit_code"] == 7
    assert raised.value.receipt["workspace"] == str(tmp_path)
    assert raised.value.receipt["workspace_preserved"] is True
