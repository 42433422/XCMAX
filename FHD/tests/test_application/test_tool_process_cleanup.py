"""Process inspection must describe the same PIDs that receive cleanup signals."""

import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from app.application.agent_orchestrator import tool_process
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.utils.operational_errors import BOUNDARY_ERRORS


class CleanupFixtureExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        Path(step.params["effect"]).write_text("written", encoding="utf-8")
        return {"success": True}


class ParentExitFixtureExecutor(AgentToolExecutor):
    def execute(self, step, *, runtime_context):
        root = Path(step.params["root"])
        # Match MCP's separate stdio session: killing just the worker's process
        # group cannot establish that its owned descendants have stopped.
        script = """
import json, subprocess, sys, time
from pathlib import Path
import psutil
root = Path(sys.argv[1])
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                         start_new_session=True)
root.joinpath('stdio.json').write_text(json.dumps({
    'pid': child.pid, 'created': psutil.Process(child.pid).create_time()}))
deadline = time.monotonic() + 25
while not root.joinpath('owner-exited').exists() and time.monotonic() < deadline:
    time.sleep(0.01)
time.sleep(2)
root.joinpath('late-stdio-effect').write_text('must not run after owner exit')
time.sleep(30)
"""
        subprocess.Popen(
            [sys.executable, "-c", script, str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        deadline = time.monotonic() + 20
        while not (root / "stdio.json").is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("stdio fixture did not start")
            time.sleep(0.01)
        (root / "entered").write_text(str(os.getpid()), encoding="utf-8")
        if step.params["phase"] == "worker_exit":
            while not (root / "exit-worker").is_file():
                if time.monotonic() >= deadline:
                    raise TimeoutError("observer did not record the owned tree")
                time.sleep(0.01)
            os._exit(23)
        if step.params["phase"] == "active":
            while not (root / "owner-exited").is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            time.sleep(2)
            (root / "late-worker-effect").write_text("must not run after owner exit")
        return {"success": True}


def _exit_tool_owner(root, browser, phase, report):
    """Crash only after the real adapter has admitted its controlled executor."""
    assert tool_process._process_namespace_matches(), "fixture owner has unverified process IDs"
    from app.application.agent_orchestrator.browser_tool_process import _BrowserWorker
    from app.application.tools.mcp.registry import mcp_session_scope
    from app.infrastructure.mcp.config import McpServerConfig

    root = Path(root)
    folder = ""
    try:
        context = {"tenant_id": "tenant", "user_id": "owner", "run_id": "parent-exit"}
        step = AgentStep(
            "fixture", "fixture", "fixture", params={"root": str(root), "phase": phase}
        )
        executor = ParentExitFixtureExecutor()
        results = []
        if browser:
            config = McpServerConfig(
                name="parent-exit-fixture",
                command="unused",
                browser=True,
                session_mode="persistent",
                session_start_tools=("fixture",),
                session_idle_seconds=1,
            )
            worker = _BrowserWorker(
                executor, config, mcp_session_scope(context), "fixture", "fixture"
            )
            folder = worker.folder

            def execute():
                results.append(worker.call(step, context, time.monotonic() + 25, ""))

        else:
            # This lifetime fixture does not open a customer or host database.
            tool_process._caller_business_db_url = lambda: ""
            folder = str(root / "transport")
            Path(folder).mkdir()
            original_mkdtemp = tool_process.tempfile.mkdtemp
            tool_process.tempfile.mkdtemp = lambda *args, **kwargs: (
                folder
                if kwargs.get("prefix") == "xcagi-tool-"
                else original_mkdtemp(*args, **kwargs)
            )

            def execute():
                results.append(
                    tool_process.execute_isolated(executor, step, context, time.monotonic() + 25)
                )

        thread = threading.Thread(target=execute, daemon=True)
        thread.start()
        deadline = time.monotonic() + 25
        while not (root / "entered").is_file():
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError(f"fixture executor did not enter: {results!r}")
            time.sleep(0.01)
        if phase == "idle":
            thread.join(timeout=max(0, deadline - time.monotonic()))
            assert not thread.is_alive() and results == [{"success": True}]
        assert tool_process._process_namespace_matches(), "fixture process namespace changed"
        owned = [
            {"pid": process.pid, "created": process.create_time()}
            for process in psutil.Process().children(recursive=True)
        ]
        report.send_bytes(json.dumps({"owned": owned, "folder": folder}).encode())
    except BOUNDARY_ERRORS as exc:
        report.send_bytes(json.dumps({"error": repr(exc)}).encode())
        raise
    # Reproduce the desktop backend's parent-loss path, bypassing atexit.
    os._exit(0)


def assert_owner_exit_reaps_workers(tmp_path, *, browser, phase):
    """The observer survives the owner and cleans only this fixture's identities."""
    assert tool_process._process_namespace_matches(), "fixture observer has unverified process IDs"
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    owner = ctx.Process(target=_exit_tool_owner, args=(str(tmp_path), browser, phase, sender))
    unrelated = ctx.Process(target=time.sleep, args=(120,))
    observed = []
    folder = ""
    try:
        unrelated.start()
        owner.start()
        sender.close()
        assert receiver.poll(35), "owner did not report its admitted worker"
        report = json.loads(receiver.recv_bytes())
        assert "error" not in report, report
        folder = report["folder"]
        assert len(report["owned"]) >= 3  # Actual worker, stdio child, and its child.
        stdio_child = json.loads((tmp_path / "stdio.json").read_text())
        assert stdio_child in report["owned"]
        assert int((tmp_path / "entered").read_text()) in {item["pid"] for item in report["owned"]}
        for item in report["owned"]:
            try:
                process = psutil.Process(item["pid"])
                assert process.create_time() == item["created"]
                observed.append(process)
            except psutil.NoSuchProcess:
                pass  # A functioning supervisor can finish before this observer.
        owner.join(timeout=5)
        assert owner.exitcode == 0
        (tmp_path / "owner-exited").touch()
        _, alive = psutil.wait_procs(observed, timeout=5)
        alive = [
            process
            for process in alive
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        ]
        assert not alive, {
            "alive": [process.pid for process in alive],
            "late_effects": [path.name for path in tmp_path.glob("late-*-effect")],
        }
        assert not list(tmp_path.glob("late-*-effect"))
        assert unrelated.is_alive(), "owned-tree cleanup reached an unrelated sibling process"
    finally:
        namespace_matches = tool_process._process_namespace_matches()
        if namespace_matches:
            if owner.pid is not None and owner.is_alive():
                observed.extend(psutil.Process(owner.pid).children(recursive=True))
            for process in reversed(observed):
                try:
                    process.kill()  # psutil fences recycled PIDs using create_time.
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(observed, timeout=2)
        if owner.pid is not None:
            if owner.is_alive():
                owner.kill()
            owner.join(timeout=2)
            owner.close()
        if unrelated.pid is not None:
            if unrelated.is_alive():
                unrelated.kill()
            unrelated.join(timeout=2)
            unrelated.close()
        receiver.close()
        sender.close()
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        assert namespace_matches, "fixture cleanup cannot inspect an unverified process namespace"


def test_active_tool_worker_and_stdio_tree_stop_when_owner_exits(tmp_path):
    assert_owner_exit_reaps_workers(tmp_path, browser=False, phase="active")


def _ownership_fault_supervisor(fault, marker, *args):
    """Inject the OS failure inside the real spawned supervisor, before admission."""
    if fault == "unsupported":

        def unsupported():
            Path(marker).write_text(fault)
            return False

        tool_process._enable_orphan_adoption = unsupported
    else:
        import ctypes

        def denied_prctl(*_args):
            Path(marker).write_text(fault)
            return -1

        def library(*_args, **_kwargs):
            if fault == "unavailable":
                Path(marker).write_text(fault)
                raise OSError("fixture ownership API unavailable")
            return SimpleNamespace(prctl=denied_prctl)

        ctypes.CDLL = library
    tool_process._supervise_worker(*args)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux prctl ownership admission contract")
@pytest.mark.parametrize("fault", ["denied", "unavailable"])
def test_ownership_api_failure_prevents_real_executor_admission(tmp_path, monkeypatch, fault):
    assert tool_process._process_namespace_matches(), "fixture has unverified process IDs"
    marker, effect = tmp_path / "ownership-api-called", tmp_path / "executor-admitted"
    monkeypatch.setattr(
        tool_process, "_supervise_worker", partial(_ownership_fault_supervisor, fault, str(marker))
    )
    monkeypatch.setattr(tool_process, "_caller_business_db_url", lambda: "")
    owned_type = tool_process._OwnedWorker
    observed = []

    def capture_boundary(*args, **kwargs):
        owned = owned_type(*args, **kwargs)
        observed.append(owned)
        return owned

    monkeypatch.setattr(tool_process, "_OwnedWorker", capture_boundary)
    before = {process.pid for process in multiprocessing.active_children()}
    try:
        result = tool_process.execute_isolated(
            CleanupFixtureExecutor(),
            AgentStep("write", "fixture", "write", params={"effect": str(effect)}),
            {},
            time.monotonic() + 15,
        )
        assert marker.read_text() == fault  # The real supervisor reached the injected OS API.
        assert len(observed) == 1 and observed[0].worker_pid is None
        assert result == {
            "success": False,
            "error_code": "tool_worker_not_started",
            "retryable": False,
        }
        assert not effect.exists()
        assert {process.pid for process in multiprocessing.active_children()} <= before
    finally:
        for owned in observed:
            owned.close()


@pytest.mark.parametrize("adoption", ["native", "unsupported"])
def test_worker_exit_cannot_certify_cleanup_while_detached_stdio_tree_survives(
    tmp_path, monkeypatch, adoption
):
    assert tool_process._process_namespace_matches(), "fixture has unverified process IDs"
    from multiprocessing.connection import wait

    marker = tmp_path / "ownership-api-called"
    if adoption == "unsupported":
        monkeypatch.setattr(
            tool_process,
            "_supervise_worker",
            partial(_ownership_fault_supervisor, adoption, str(marker)),
        )
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    start = ctx.Event()
    folder = tmp_path / "transport"
    folder.mkdir()
    step = AgentStep(
        "fixture", "fixture", "fixture", params={"root": str(tmp_path), "phase": "worker_exit"}
    )
    payload = json.dumps({"step": step.to_dict(), "context": {}, "business_db_url": ""})
    deadline = time.monotonic() + 25
    owned = tool_process._OwnedWorker(
        ctx,
        tool_process._worker,
        ParentExitFixtureExecutor,
        (payload, str(folder), sender, start, deadline),
        (sender,),
    )
    observed = []
    try:
        owned.start()
        sender.close()
        assert owned.wait_ready(deadline)
        assert tool_process._worker_acknowledged(receiver, owned, b"r", deadline) == (True, False)
        start.set()
        while not (tmp_path / "entered").is_file():
            assert time.monotonic() < deadline, "fixture executor did not enter"
            time.sleep(0.01)
        assert tool_process._process_namespace_matches(), "fixture process namespace changed"
        assert owned.worker_pid not in {None, os.getpid(), owned.process.pid}
        worker = psutil.Process(owned.worker_pid)
        assert worker.ppid() == owned.process.pid
        assert int((tmp_path / "entered").read_text()) == worker.pid
        observed = [worker, *worker.children(recursive=True)]
        assert len(observed) == 3  # Worker, independently sessioned stdio, and its child.
        identities = [
            {"pid": process.pid, "created": process.create_time()} for process in observed
        ]
        (tmp_path / "exit-worker").touch()
        assert wait((owned.sentinel,), timeout=5), "actual worker exit was not observed"
        assert owned.exited()
        clean = owned.close()
        assert owned.worker_exitcode == 23
        # Reuse the fixture's delayed-effect gate; this test's owner stays alive.
        (tmp_path / "owner-exited").touch()
        _, alive = psutil.wait_procs(observed, timeout=3)
        alive = [
            process.pid
            for process in alive
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        ]
        evidence = {
            "clean": clean,
            "worker_exitcode": owned.worker_exitcode,
            "identities": identities,
            "alive": alive,
            "late_effects": [path.name for path in tmp_path.glob("late-*-effect")],
        }
        (tmp_path / "worker-exit-observation.json").write_text(json.dumps(evidence))
        assert not (clean and alive), evidence
        if adoption == "unsupported" or sys.platform != "linux":
            # An unsupported adoption mechanism must never certify the escaped
            # tree. Only the independent test observer can clean its recorded PIDs.
            assert clean is False, evidence
            if adoption == "unsupported":
                assert marker.read_text() == adoption
        else:
            assert clean is True, evidence
            assert not alive, evidence
            assert not evidence["late_effects"], evidence
    finally:
        owned.close()
        namespace_matches = tool_process._process_namespace_matches()
        if namespace_matches:
            for process in reversed(observed):
                try:
                    process.kill()  # The captured Process object fences PID reuse.
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(observed, timeout=2)
        receiver.close()
        sender.close()
        assert namespace_matches, "fixture cleanup cannot inspect an unverified process namespace"


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
        "root_not_stopped",
        "root_already_exited",
    ],
)
def test_reap_requires_complete_tree_and_confirmed_shutdown(monkeypatch, condition):
    process = Mock(pid=22)
    process.is_alive.return_value = condition == "live_root"
    root, child = Mock(), Mock()
    root.children.return_value = [child]
    root.status.return_value = psutil.STATUS_STOPPED
    child.is_running.return_value = True
    child.status.return_value = psutil.STATUS_RUNNING
    monkeypatch.setattr(tool_process, "_process_namespace_matches", lambda: True)
    inspect = Mock(return_value=root)
    wait = Mock(return_value=([child], []))
    monkeypatch.setattr(psutil, "Process", inspect)
    monkeypatch.setattr(psutil, "wait_procs", wait)
    if condition == "root_missing":
        inspect.side_effect = psutil.NoSuchProcess(process.pid)
    elif condition == "root_not_stopped":
        root.status.return_value = psutil.STATUS_RUNNING
    elif condition == "root_already_exited":
        root.status.return_value = psutil.STATUS_ZOMBIE
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
    injected_faults = []

    def spawn(*args, **kwargs):
        process = process_type(*args, **kwargs)
        owned.append((process, process.kill, process.join))
        return process

    reap = tool_process._reap

    def fail_cleanup(process, **kwargs):
        if failure == "kill_denied":
            process.kill = Mock(side_effect=PermissionError("cleanup denied"))
            injected_faults.append(process.kill)
        elif failure == "join_denied":
            process.join = Mock(side_effect=OSError("wait unavailable"))
            injected_faults.append(process.join)
        return reap(process, **kwargs)

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
        if failure != "namespace_loss":
            assert len(injected_faults) == 1
            injected_faults[0].assert_called_once()
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
