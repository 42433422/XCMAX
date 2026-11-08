"""Process inspection must describe the same PIDs that receive cleanup signals."""

import multiprocessing
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from app.application.agent_orchestrator import tool_process
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor


class CleanupFixtureExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        Path(step.params["effect"]).write_text("written", encoding="utf-8")
        return {"success": True}


@pytest.mark.parametrize(
    ("ids", "matches"),
    [("{pid}", True), ("777 {pid}", False), ("{pid} {pid}", False), ("777", False), ("", False)],
)
def test_procfs_must_describe_the_current_pid_namespace(tmp_path, monkeypatch, ids, matches):
    (tmp_path / "self").mkdir()
    (tmp_path / "self/status").write_text(f"Name:\tpython\nNSpid:\t{ids.format(pid=os.getpid())}\n")
    monkeypatch.setattr(psutil, "PROCFS_PATH", str(tmp_path), raising=False)
    assert tool_process._process_namespace_matches() is matches


@pytest.mark.parametrize("failure", ["missing", "denied", "no_namespace_metadata"])
def test_unreadable_namespace_is_not_assumed_safe(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(psutil, "PROCFS_PATH", str(tmp_path), raising=False)
    if failure == "denied":
        monkeypatch.setattr(Path, "read_text", Mock(side_effect=PermissionError))
    elif failure == "no_namespace_metadata":
        (tmp_path / "self").mkdir()
        (tmp_path / "self/status").write_text("Name:\tpython\n")
    assert tool_process._process_namespace_matches() is False


def test_non_procfs_platform_keeps_native_process_lookup(monkeypatch):
    monkeypatch.delattr(psutil, "PROCFS_PATH", raising=False)
    assert tool_process._process_namespace_matches() is True


def test_namespace_mismatch_rejects_before_creating_a_worker(monkeypatch):
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: False)
    monkeypatch.setattr(tool_process, "_caller_business_db_url", lambda: "")
    monkeypatch.setattr(multiprocessing, "get_context", Mock(side_effect=AssertionError("spawned")))
    result = tool_process.execute_isolated(
        SimpleNamespace(), AgentStep("read", "fixture", "read"), {}, time.monotonic() + 5
    )
    assert result == {
        "success": False,
        "error_code": "tool_process_namespace_unverified",
        "retryable": False,
    }


def test_namespace_mismatch_reaps_only_the_owned_real_child(monkeypatch):
    process = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(30,))
    process.start()
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: False)
    monkeypatch.setattr(psutil, "Process", Mock(side_effect=AssertionError("untrusted PID")))
    try:
        assert tool_process._reap(process) is False
        assert not process.is_alive() and process.exitcode is not None
        assert process not in multiprocessing.active_children()
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        process.close()


@pytest.mark.parametrize(
    "condition",
    [
        "clean",
        "root_missing",
        "collection_denied",
        "wait_denied",
        "status_denied",
        "live_child",
        "live_root",
    ],
)
def test_reap_requires_complete_tree_and_confirmed_shutdown(monkeypatch, condition):
    process = Mock(pid=22)
    process.is_alive.return_value = condition == "live_root"
    root, child = Mock(), Mock()
    root.children.return_value = [child]
    child.is_running.return_value = True
    child.status.return_value = psutil.STATUS_RUNNING
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: True)
    inspect = Mock(return_value=root)
    wait = Mock(return_value=([child], []))
    monkeypatch.setattr(psutil, "Process", inspect)
    monkeypatch.setattr(psutil, "wait_procs", wait)
    if condition == "root_missing":
        inspect.side_effect = psutil.NoSuchProcess(process.pid)
    elif condition == "collection_denied":
        root.children.side_effect = psutil.AccessDenied(process.pid)
    elif condition == "wait_denied":
        wait.side_effect = psutil.AccessDenied(23)
    elif condition in {"status_denied", "live_child"}:
        wait.return_value = ([], [child])
        if condition == "status_denied":
            child.status.side_effect = psutil.AccessDenied(23)
    assert tool_process._reap(process) is (condition == "clean")
    process.join.assert_called_once_with(timeout=1)
    if condition in {"root_missing", "collection_denied"}:
        process.kill.assert_called_once()
    if condition == "root_missing":
        root.children.assert_not_called()


@pytest.mark.parametrize("failure", ["namespace_loss", "kill_denied", "join_denied"])
def test_namespace_loss_after_real_effect_stays_unknown_and_blocks_reuse(
    tmp_path, monkeypatch, failure
):
    # Simulate inspection becoming invalid after spawn, without consulting the
    # mismatched procfs of the test host or changing the real worker adapter.
    matches = iter([True, False])
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: next(matches))
    monkeypatch.setattr(tool_process, "_caller_business_db_url", lambda: "")
    monkeypatch.setattr(psutil, "Process", Mock(side_effect=AssertionError("untrusted PID")))
    transport = tmp_path / "transport"
    transport.mkdir()
    monkeypatch.setattr(tool_process.tempfile, "mkdtemp", lambda **_: str(transport))
    ctx = multiprocessing.get_context("spawn")
    process_type = ctx.Process
    owned = []

    def spawn(*args, **kwargs):
        process = process_type(*args, **kwargs)
        owned.append((process, process.kill, process.join))
        return process

    reap = tool_process._reap

    def fail_cleanup(process):
        if failure == "kill_denied":
            process.kill = Mock(side_effect=PermissionError("cleanup denied"))
        elif failure == "join_denied":
            process.join = Mock(side_effect=OSError("wait unavailable"))
        return reap(process)

    monkeypatch.setattr(ctx, "Process", spawn)
    monkeypatch.setattr(tool_process, "_reap", fail_cleanup)
    executor = CleanupFixtureExecutor()
    effect = tmp_path / "effect"
    step = AgentStep("write", "fixture", "write", params={"effect": str(effect)})
    before = {child.pid for child in multiprocessing.active_children()}
    try:
        result = tool_process.execute_isolated(executor, step, {}, time.monotonic() + 15)
        assert effect.read_text(encoding="utf-8") == "written"
        assert result == {
            "outcome": "unknown",
            "error_code": "tool_cleanup_failed",
            "retryable": False,
        }
        assert executor._tool_cleanup_failed is True
        assert (transport / "result").is_file()  # Unknown retains the original transport evidence.
        again = tool_process.execute_isolated(executor, step, {}, time.monotonic() + 5)
        assert again["error_code"] == "tool_cleanup_unresolved"
    finally:
        for process, kill, join in owned:
            if process.is_alive():
                kill()
            if process.pid is not None:
                join(timeout=2)
            process.close()
    assert {child.pid for child in multiprocessing.active_children()} <= before
