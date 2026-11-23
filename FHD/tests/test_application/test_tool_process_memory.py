"""Real process-tree budgets at the existing spawn, receipt and cleanup boundary."""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from app.application.agent_orchestrator import tool_process
from app.application.agent_orchestrator.run_models import AgentStep
from app.infrastructure.chat_stream_lifetime import (
    StreamLifetime,
    current_lifetime,
    publish_stream_note,
)

MIB = 1024 * 1024
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX resource and process-tree contract")

_ALLOCATOR = """
import sys, time
from pathlib import Path
folder, index, gated = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == '1'
while gated and not (folder / 'allocate').exists():
    time.sleep(0.01)
memory = bytearray(192 * 1024 * 1024)
for offset in range(0, len(memory), 4096):
    memory[offset] = 1
(folder / ('allocated' + index)).write_text('ready')
time.sleep(3)
(folder / ('late_effect' + index)).write_text('should have been reaped')
time.sleep(30)
"""


class MemoryFixtureExecutor:
    def execute(self, step, *, runtime_context):
        import resource

        folder = Path(step.params["folder"])
        (folder / "worker").write_text(str(os.getpid()))
        if step.action == "limits":
            return {
                "success": True,
                "as": resource.getrlimit(resource.RLIMIT_AS),
                "cpu": resource.getrlimit(resource.RLIMIT_CPU),
                "files": resource.getrlimit(resource.RLIMIT_NOFILE),
            }
        if step.action == "virtual":
            import mmap

            with mmap.mmap(-1, 8 * 1024 * MIB, prot=0):
                time.sleep(0.25)  # The parent must observe the reservation.
                info = psutil.Process().memory_info()
                return {"success": True, "rss": info.rss, "vms": info.vms}
        if step.action in {"allocate", "drain", "receipt"}:
            for index in range(2):
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        _ALLOCATOR,
                        str(folder),
                        str(index),
                        "0" if step.action == "allocate" else "1",
                    ]
                )
                (folder / f"child{index}").write_text(str(child.pid))
            if step.action == "drain":
                publish_stream_note("block the receipt observer")
            if step.action != "allocate":
                return {"success": True, "receipt_boundary": step.action == "receipt"}
        (folder / "entered").write_text("execution started")
        time.sleep(30)
        return {"success": True}


@pytest.fixture(autouse=True)
def supervised_browser(monkeypatch):
    monkeypatch.setattr(tool_process, "_caller_business_db_url", lambda: "")
    monkeypatch.setenv("XCAGI_TOOL_SANDBOX", "1")
    monkeypatch.setenv("XCAGI_TOOL_MEMORY_MB", "384")
    monkeypatch.setenv("XCAGI_TOOL_CPU_SECONDS", "60")
    monkeypatch.setenv("XCAGI_TOOL_MAX_FILES", "256")


def _execute(folder, action, *, tool="browser"):
    return tool_process.execute_isolated(
        MemoryFixtureExecutor(),
        AgentStep("memory", tool, action, params={"folder": str(folder), "monitored_memory": True}),
        {},
        time.monotonic() + 15,
    )


def _wait_for(predicate, seconds=5):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("process fixture did not reach its checkpoint")


def _not_live(pid):
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def _assert_reaped(folder, *, children=False):
    names = ["worker", "child0", "child1"] if children else ["worker"]
    for name in names:
        assert _not_live(int((folder / name).read_text())), name


@pytest.mark.parametrize("tool", ["fixture", "aiopen", "browser"])
def test_only_trusted_browser_selection_replaces_as_after_supervised_release(tmp_path, tool):
    import resource

    inherited_as = resource.getrlimit(resource.RLIMIT_AS)
    result = _execute(tmp_path, "limits", tool=tool)
    assert result.get("success") is True, result
    expected_as = inherited_as[0] if tool == "browser" else 384 * MIB
    assert result["as"][0] == expected_as
    assert result["as"][1] == inherited_as[1]
    assert result["cpu"][0] == 60 and result["files"][0] == 256
    _assert_reaped(tmp_path)


def test_large_virtual_reservation_does_not_consume_the_resident_budget(tmp_path):
    result = _execute(tmp_path, "virtual")
    assert result.get("success") is True, result
    assert result["rss"] < 384 * MIB and result["vms"] > 8 * 1024 * MIB
    _assert_reaped(tmp_path)


def _externally_limited_worker(control, start, deadline, result_file):
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (640 * MIB, 640 * MIB))
    if tool_process._worker_start(control, start, deadline, monitored_memory=True):
        Path(result_file).write_text(json.dumps(resource.getrlimit(resource.RLIMIT_AS)))
        control.send_bytes(b"d")
        start.clear()
        start.wait()


def test_supervised_release_preserves_external_address_space_hard_limit(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    start, deadline = ctx.Event(), time.monotonic() + 10
    output = tmp_path / "limits"
    process = ctx.Process(
        target=_externally_limited_worker, args=(sender, start, deadline, str(output))
    )
    supervisor = tool_process._WorkerProcessSupervisor(process, memory_limit_bytes=384 * MIB)
    try:
        with supervisor:
            sender.close()
            assert supervisor.wait_ack(receiver, b"r", deadline) == (True, False)
            if hasattr(psutil.Process, "rlimit"):
                assert psutil.Process(process.pid).rlimit(psutil.RLIMIT_AS) == (
                    384 * MIB,
                    640 * MIB,
                )
            supervisor.release(start)
            assert supervisor.wait_ack(receiver, b"d", deadline) == (True, False)
            assert json.loads(output.read_text()) == [640 * MIB, 640 * MIB]
            supervisor.check()
    finally:
        receiver.close()
        sender.close()
    assert supervisor.clean is True


@pytest.mark.parametrize("action", ["allocate", "drain", "receipt"])
def test_sum_of_descendants_is_enforced_during_execution_drain_and_final_receipt(
    tmp_path, monkeypatch, action
):
    lifetime = StreamLifetime() if action == "drain" else None
    entered, release = threading.Event(), threading.Event()
    checkpoints = []
    if lifetime is not None:

        def block(_note):
            entered.set()
            release.wait(20)

        lifetime.observe_notes(block)
        wait_event = tool_process._WorkerProcessSupervisor.wait_event

        def drain(self, event, deadline):
            assert entered.wait(3)
            checkpoints.append("drain")
            (tmp_path / "allocate").write_text("release allocators after done ack")
            return wait_event(self, event, deadline)

        monkeypatch.setattr(tool_process._WorkerProcessSupervisor, "wait_event", drain)
    if action == "receipt":
        decode = json.loads

        def result_boundary(value, *args, **kwargs):
            result = decode(value, *args, **kwargs)
            if isinstance(result, dict) and result.get("output", {}).get("receipt_boundary"):
                checkpoints.append("receipt")
                (tmp_path / "allocate").write_text("release after the completion check")
                _wait_for(lambda: all((tmp_path / f"allocated{i}").exists() for i in range(2)))
            return result

        monkeypatch.setattr(tool_process.json, "loads", result_boundary)
    token = current_lifetime.set(lifetime)
    try:
        result = _execute(tmp_path, action)
    finally:
        current_lifetime.reset(token)
        release.set()
    assert result.get("error_code") == "tool_memory_limit_exceeded", result
    assert result["observed_rss_bytes"] > result["memory_limit_bytes"] == 384 * MIB
    assert result["outcome"] == "unknown" and result["retryable"] is False
    assert result["success"] is False and result["reconciliation_required"] is True
    if action != "allocate":
        assert checkpoints == [action]
    _assert_reaped(tmp_path, children=True)
    # Child allocations are each below the shared limit; neither may continue to
    # its delayed external effect after the parent rejected the aggregate.
    assert not list(tmp_path.glob("late_effect*"))


@pytest.mark.parametrize("after_release", [False, True])
def test_live_process_inspection_denied_fails_closed_before_or_after_release(
    tmp_path, monkeypatch, after_release
):
    memory_info = psutil.Process.memory_info

    def denied(process):
        if not after_release or (tmp_path / "entered").exists():
            raise psutil.AccessDenied(process.pid)
        return memory_info(process)

    monkeypatch.setattr(psutil.Process, "memory_info", denied)
    result = _execute(tmp_path, "blocked")
    assert result.get("error_code") == "tool_memory_monitor_unavailable", result
    assert result["retryable"] is False and result["success"] is False
    assert result["outcome"] == ("unknown" if after_release else "not_started")
    assert result["reconciliation_required"] is after_release
    assert (tmp_path / "entered").exists() is after_release
    if after_release:
        _assert_reaped(tmp_path)


def _orphan_worker(control, start, deadline, folder):
    if not tool_process._worker_start(control, start, deadline, monitored_memory=True):
        return
    folder = Path(folder)
    intermediate = os.fork()
    if intermediate == 0:
        orphan = os.fork()
        if orphan == 0:
            memory = bytearray(48 * MIB)
            (folder / "orphan.pending").write_text(str(os.getpid()))
            (folder / "orphan.pending").replace(folder / "orphan")
            time.sleep(30)
            os._exit(0)
        (folder / "intermediate.pending").write_text(str(os.getpid()))
        (folder / "intermediate.pending").replace(folder / "intermediate")
        while not (folder / "reparent").exists():
            time.sleep(0.01)
        os._exit(0)
    time.sleep(30)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires a real reparented descendant")
def test_observed_orphan_is_still_counted_and_reaped_after_intermediate_exit(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    start, deadline = ctx.Event(), time.monotonic() + 15
    process = ctx.Process(target=_orphan_worker, args=(sender, start, deadline, str(tmp_path)))
    supervisor = tool_process._WorkerProcessSupervisor(process, memory_limit_bytes=384 * MIB)
    orphan = None
    try:
        supervisor.start()
        sender.close()
        assert supervisor.wait_ack(receiver, b"r", deadline) == (True, False)
        supervisor.release(start)
        # Published names become visible only after the complete PID has been written.
        _wait_for(lambda: (tmp_path / "orphan").exists() and (tmp_path / "intermediate").exists())
        orphan = psutil.Process(int((tmp_path / "orphan").read_text()))
        middle = int((tmp_path / "intermediate").read_text())
        supervisor.check()
        assert (orphan.pid, orphan.create_time()) in supervisor.memory_guard.processes
        (tmp_path / "reparent").write_text("exit the intermediate")
        _wait_for(lambda: orphan.ppid() != middle)
        assert orphan.pid not in {
            child.pid for child in psutil.Process(process.pid).children(recursive=True)
        }
        root_rss = psutil.Process(process.pid).memory_info().rss
        supervisor.memory_guard.limit_bytes = max(root_rss, orphan.memory_info().rss) + MIB
        with pytest.raises(tool_process._WorkerResourceError, match="tool_memory_limit_exceeded"):
            supervisor.check()
    finally:
        receiver.close()
        sender.close()
        supervisor.close()
    assert supervisor.clean is True
    assert orphan is not None and _not_live(orphan.pid)


def test_reused_pid_is_not_read_as_the_previously_observed_child(monkeypatch):
    root, child = Mock(pid=11), Mock(pid=22)
    root.create_time.return_value, child.create_time.return_value = 1.0, 2.0
    root.is_running.return_value = child.is_running.return_value = True
    root.children.return_value, child.children.return_value = [child], []
    root.memory_info.return_value = child.memory_info.return_value = SimpleNamespace(rss=10)
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: True)
    monkeypatch.setattr(psutil, "Process", lambda _pid: root)
    guard = tool_process._ProcessTreeMemoryGuard(root.pid, 100)
    guard.check()
    assert (22, 2.0) in guard.processes
    child.is_running.return_value = False  # psutil PID/create-time identity no longer matches.
    root.children.return_value = []
    child.memory_info.reset_mock()
    guard.check()
    child.memory_info.assert_not_called()
    assert guard.descendants == ()


def test_short_lived_child_does_not_skip_remaining_siblings_during_reap(monkeypatch):
    process, root, vanished, sibling = Mock(pid=11), Mock(), Mock(), Mock()
    process.is_alive.return_value = False
    root.children.return_value = [vanished, sibling]
    vanished.suspend.side_effect = psutil.NoSuchProcess(12)
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: True)
    monkeypatch.setattr(psutil, "Process", lambda _pid: root)
    monkeypatch.setattr(psutil, "wait_procs", lambda *_args, **_kwargs: ([], []))
    assert tool_process._reap(process) is True
    assert sibling.suspend.call_count == 2
    sibling.kill.assert_called_once()
