from __future__ import annotations

import importlib.util
import os
from pathlib import Path


SCRIPT = Path(__file__).with_name("clean_agent_workspace.py")
SPEC = importlib.util.spec_from_file_location("clean_agent_workspace", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_runtime_cleanup_is_bounded_and_idempotent(tmp_path: Path) -> None:
    runtime = tmp_path / "para-main-agent"
    workspace = runtime / "workspace"
    logs = runtime / "logs"
    workspace.mkdir(parents=True)
    logs.mkdir()

    stale = workspace / "36f63923-2e02-4fdb-b760-4f3382bc05ce-task"
    recent = workspace / "49fafd35-3b5a-4681-8897-a24879f077a7-task"
    unrelated = workspace / "keep-me"
    for path in (stale, recent, unrelated):
        path.mkdir()
        (path / "payload").write_bytes(b"x")
    os.utime(stale, (1, 1))

    log = logs / "stdout.log"
    log.write_bytes(b"0123456789")
    for index in range(5):
        backup = runtime / f"e2e-agent.mjs.backup-2026080{index}T000000Z"
        backup.write_text(str(index), encoding="utf-8")
        os.utime(backup, (index + 1, index + 1))

    removed: list[str] = []
    errors: list[str] = []
    MODULE._clean_agent_runtime_workspaces(
        runtime, max_age=60, removed=removed, errors=errors
    )
    MODULE._trim_agent_runtime_logs(
        runtime, max_bytes=8, tail_bytes=4, removed=removed, errors=errors
    )
    MODULE._prune_agent_runtime_backups(runtime, keep=2, removed=removed, errors=errors)

    assert errors == []
    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists()
    assert log.read_bytes() == b"6789"
    assert len(list(runtime.glob("e2e-agent.mjs.backup-*"))) == 2

    second_removed: list[str] = []
    MODULE._clean_agent_runtime_workspaces(
        runtime, max_age=60, removed=second_removed, errors=errors
    )
    MODULE._trim_agent_runtime_logs(
        runtime, max_bytes=8, tail_bytes=4, removed=second_removed, errors=errors
    )
    MODULE._prune_agent_runtime_backups(
        runtime, keep=2, removed=second_removed, errors=errors
    )
    assert second_removed == []
    assert errors == []


def test_runtime_log_directory_is_bounded(tmp_path: Path) -> None:
    logs = tmp_path / "fhd-desktop" / "logs"
    logs.mkdir(parents=True)
    log = logs / "fhd.err.log"
    log.write_bytes(b"0123456789")

    removed: list[str] = []
    errors: list[str] = []
    MODULE._trim_runtime_logs(
        logs,
        max_bytes=8,
        tail_bytes=4,
        removed=removed,
        errors=errors,
    )

    assert log.read_bytes() == b"6789"
    assert removed == [f"trimmed:{log}"]
    assert errors == []
