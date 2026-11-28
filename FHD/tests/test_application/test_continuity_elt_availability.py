"""Real subprocess and cross-process ledger regressions; no external services."""

import json
import multiprocessing
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import psutil
import pytest

from app.application.employee_runtime.continuity_tool_wait import (
    ProcessLimits,
    ProcessLimitsExceeded,
    run_process,
)
from app.application.employee_runtime.task_continuity import TaskContinuityRuntime, ledger_path

_REQUIRES_DARWIN = pytest.mark.skipif(sys.platform != "darwin", reason="macOS boundary required")


def runtime(root):
    return TaskContinuityRuntime(ledger_path(root), workspace=root)


def dispatch(root, op, task_id="", **extra):
    return runtime(root).dispatch(
        "clerk",
        "",
        {"op": op, "task_id": task_id, "tenant_id": "tenant", "user_id": "owner", **extra},
    )


def setup_hold(root):
    (root / "tools").mkdir()
    (root / "tools/elt_hold.py").write_text(
        "import pathlib,time,json\np=pathlib.Path('.')\n"
        "(p/'entered').write_text('started')\n"
        "while not (p/'release').exists(): time.sleep(.02)\n"
        "print(json.dumps({'ok':True,'value':1}))\n"
    )
    result = dispatch(root, "start", steps=[{"tool": "elt_hold", "step_id": "one"}])
    return result["task_id"]


def test_running_elt_does_not_block_cross_process_read_or_pause(tmp_path):
    task_id = setup_hold(tmp_path)
    process = multiprocessing.get_context("fork").Process(
        target=dispatch, args=(tmp_path, "run_tools", task_id)
    )
    process.start()
    deadline = time.monotonic() + 8
    while not (tmp_path / "entered").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert (tmp_path / "entered").exists()
    responsive = False
    with ThreadPoolExecutor() as pool:
        future = pool.submit(dispatch, tmp_path, "read", task_id)
        try:
            result = future.result(timeout=1)
            responsive = result["success"]
            assert dispatch(tmp_path, "pause", task_id)["success"]
        except TimeoutError:
            pass
        finally:
            (tmp_path / "release").write_text("finish")
            process.join(8)
            if process.is_alive():
                process.kill()
                process.join()
    assert responsive, "ELT subprocess monopolized the cross-process ledger lock"


def test_pause_late_receipt_no_replay_and_unrelated_owner_progress(tmp_path):
    task_id = setup_hold(tmp_path)
    (tmp_path / "tools/next.py").write_text(
        "import pathlib\npathlib.Path('next-effect').write_text('one')\nprint('{\"ok\":true}')"
    )
    # Add a second step before dispatch, under the real ledger lock.
    r = runtime(tmp_path)
    from app.application.employee_runtime.task_continuity import _step_from

    with r._exclusive():
        r._read()
        r.state["tasks"][task_id]["steps"].append(_step_from(task_id, {"tool": "next"}, 1))
        r._write()
    process = multiprocessing.get_context("fork").Process(
        target=dispatch, args=(tmp_path, "run_tools", task_id)
    )
    process.start()
    try:
        deadline = time.monotonic() + 8
        while not (tmp_path / "entered").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert (tmp_path / "entered").exists()
        denied = dispatch(tmp_path, "pause", task_id, user_id="intruder")
        assert denied["error_code"] == "unauthorized"
        assert dispatch(tmp_path, "run_tools", task_id)["error_code"] == "tool_in_progress"
        assert dispatch(tmp_path, "restart", task_id)["success"]
        assert dispatch(tmp_path, "pause", task_id)["success"]
        other = dispatch(
            tmp_path, "start", tenant_id="other", user_id="other", steps=[{"tool": "next"}]
        )
        assert dispatch(
            tmp_path, "run_tools", other["task_id"], tenant_id="other", user_id="other"
        )["business_success"]
    finally:
        (tmp_path / "release").write_text("finish")
        process.join(8)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
    task = dispatch(tmp_path, "read", task_id)["task"]
    assert task["status"] == "paused"
    assert [step["status"] for step in task["steps"]] == ["success", "pending"]
    assert dispatch(tmp_path, "resume", task_id, text="继续执行剩余任务")["business_success"]
    with r._exclusive():
        r._read()
    assert (
        sum(
            c["task_id"] == task_id and c["step_id"] == "one"
            for c in r.state["tool_calls"].values()
        )
        == 1
    )


def test_trusted_timeout_preserves_unknown_effect_and_blocks_retry(tmp_path):
    from app.application.tool_execution_deadline import invocation_deadline

    task_id = setup_hold(tmp_path)
    with invocation_deadline(time.monotonic() + 0.3):
        result = dispatch(tmp_path, "run_tools", task_id)
    assert result["task"]["status"] == "recovering"
    assert result["task"]["steps"][0]["error_code"] == "tool_timeout_unknown"
    assert (tmp_path / "entered").exists()
    assert (
        dispatch(tmp_path, "retry_step", task_id, step_id="one")["error_code"] == "retry_not_failed"
    )
    assert not dispatch(tmp_path, "run_tools", task_id)["business_success"]
    r = runtime(tmp_path)
    with r._exclusive():
        r._read()
    assert len(r.state["tool_calls"]) == 1


def test_timeout_reaps_descendants_even_after_parent_exits(tmp_path):
    child = "import time,pathlib;time.sleep(.5);pathlib.Path('escaped').write_text('bad')"
    script = f"import subprocess,sys;subprocess.Popen([sys.executable,'-c',{child!r}])"
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", script], input="", cwd=tmp_path, timeout=0.15)
    time.sleep(0.6)
    assert not (tmp_path / "escaped").exists()


def test_shared_instance_read_pause_keeps_request_descriptors_isolated(tmp_path):
    task_id = setup_hold(tmp_path)
    r = runtime(tmp_path)
    payload = {"task_id": task_id, "tenant_id": "tenant", "user_id": "owner"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(r.dispatch, "clerk", "", {**payload, "op": "run_tools"})
        try:
            deadline = time.monotonic() + 8
            while not (tmp_path / "entered").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "entered").exists()
            assert pool.submit(r.dispatch, "clerk", "", {**payload, "op": "read"}).result(1)[
                "success"
            ]
            assert pool.submit(r.dispatch, "clerk", "", {**payload, "op": "pause"}).result(1)[
                "success"
            ]
        finally:
            (tmp_path / "release").write_text("finish")
        assert running.result(5)["task"]["status"] == "paused"
    assert r._ledger_fd is None


def test_late_receipt_cannot_replace_changed_durable_claim(tmp_path):
    task_id = setup_hold(tmp_path)
    with ThreadPoolExecutor() as pool:
        running = pool.submit(dispatch, tmp_path, "run_tools", task_id)
        try:
            deadline = time.monotonic() + 8
            while not (tmp_path / "entered").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "entered").exists()
            r = runtime(tmp_path)
            with r._exclusive():
                r._read()
                r.state["tasks"][task_id]["steps"][0]["params"] = {"changed": True}
                r._write()
        finally:
            (tmp_path / "release").write_text("finish")
        assert running.result(5)["error_code"] == "tool_outcome_unknown"
    with r._exclusive():
        r._read()
    assert not r.state["side_effects"]
    assert r.state["tasks"][task_id]["steps"][0]["params"] == {"changed": True}


def test_running_claim_prevents_cross_task_idempotency_reuse(tmp_path):
    task_id = setup_hold(tmp_path)
    other_id = dispatch(
        tmp_path, "start", steps=[{"tool": "elt_hold", "idempotency_key": f"{task_id}:one"}]
    )["task_id"]
    with ThreadPoolExecutor() as pool:
        running = pool.submit(dispatch, tmp_path, "run_tools", task_id)
        try:
            deadline = time.monotonic() + 8
            while not (tmp_path / "entered").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "entered").exists()
            rejected = dispatch(tmp_path, "run_tools", other_id)
            assert rejected["task"]["steps"][0]["error_code"] == "idempotency_scope_conflict"
        finally:
            (tmp_path / "release").write_text("finish")
        assert running.result(5)["business_success"]


def test_expired_budget_never_spawns_and_is_distinct_from_unknown(tmp_path, monkeypatch):
    from app.application.employee_runtime import continuity_tool_wait
    from app.application.tool_execution_deadline import invocation_deadline

    task_id = setup_hold(tmp_path)

    def forbidden_spawn(*args, **kwargs):
        raise AssertionError("expired invocation must not spawn a worker")

    with monkeypatch.context() as patch:
        patch.setattr(continuity_tool_wait.subprocess, "Popen", forbidden_spawn)
        with invocation_deadline(time.monotonic() - 1):
            result = dispatch(tmp_path, "run_tools", task_id)
    step = result["task"]["steps"][0]
    assert step["status"] == "failed"
    assert step["error_code"] == "tool_budget_expired_before_start"
    assert step["result_payload"]["execution_status"] == "not_started"
    assert step["result_payload"]["outcome_unknown"] is False
    assert not (tmp_path / "entered").exists()
    r = runtime(tmp_path)
    with r._exclusive():
        r._read()
    call = next(iter(r.state["tool_calls"].values()))
    assert call["submitted"] is False
    assert call["execution_status"] == "not_started"
    # Explicit retry with a fresh budget is safe because nothing was submitted.
    (tmp_path / "release").write_text("finish")
    with invocation_deadline(time.monotonic() + 5):
        assert dispatch(tmp_path, "retry_step", task_id, step_id="one")["business_success"]
    assert (tmp_path / "entered").exists()


@_REQUIRES_DARWIN
def test_darwin_limits_enforce_cpu_files_and_preserve_stdin(tmp_path):
    import resource

    kinds = (resource.RLIMIT_CPU, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE)
    before = [resource.getrlimit(kind) for kind in kinds]
    output = tmp_path / "bounded output"
    script = """
import errno,json,os,resource,sys,time
time.sleep(0.2)
report = {'input': sys.stdin.read(), 'limits': [resource.getrlimit(k) for k in
    (resource.RLIMIT_CPU,resource.RLIMIT_FSIZE,resource.RLIMIT_NOFILE)]}
with open(sys.argv[1], 'wb', buffering=0) as f:
    try:
        f.write(b'x'*1024)
        f.write(b'x')
    except OSError as e:
        report['file_limited'] = e.errno == errno.EFBIG
print(json.dumps(report))
"""
    result = run_process(
        [sys.executable, "-c", script, str(output)],
        input="original input",
        cwd=tmp_path,
        timeout=5,
        limits=ProcessLimits(3, 128 * 1024**2, 1024, 64),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["input"] == "original input" and report["file_limited"]
    assert output.stat().st_size == 1024
    assert report["limits"] == [[3, 3], [1024, 1024], [64, 64]]
    cpu = run_process(
        [sys.executable, "-c", "while True: pass"],
        input=None,
        cwd=tmp_path,
        timeout=5,
        limits=ProcessLimits(1, 128 * 1024**2, 1024, 64),
    )
    assert cpu.returncode < 0
    assert [resource.getrlimit(kind) for kind in kinds] == before


@_REQUIRES_DARWIN
def test_darwin_memory_monitor_stops_real_allocation(tmp_path):
    pid = tmp_path / "engine.pid"
    script = (
        "import os,pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));"
        "allocation=bytearray(128*1024**2);time.sleep(5)"
    )
    with pytest.raises(ProcessLimitsExceeded, match="tool_memory_limit_exceeded"):
        run_process(
            [sys.executable, "-c", script, str(pid)],
            input=None,
            cwd=tmp_path,
            timeout=4,
            limits=ProcessLimits(3, 64 * 1024**2, 1024, 64),
        )
    assert pid.exists() and not psutil.pid_exists(int(pid.read_text()))


@_REQUIRES_DARWIN
def test_darwin_monitor_unavailable_never_executes_command(tmp_path, monkeypatch):
    from app.application.employee_runtime import continuity_tool_wait as boundary

    pids = []
    marker = tmp_path / "must-not-execute"

    def unavailable(pid, cap):
        pids.append(pid)
        raise boundary.ProcessLimitsUnavailable("monitor denied")

    monkeypatch.setattr(boundary, "_memory_check", unavailable)
    with pytest.raises(boundary.ProcessLimitsUnavailable, match="monitor denied"):
        boundary.run_process(
            [
                sys.executable,
                "-c",
                "import pathlib,sys;pathlib.Path(sys.argv[1]).touch()",
                str(marker),
            ],
            input=None,
            cwd=tmp_path,
            timeout=2,
            limits=boundary.ProcessLimits(1, 128 * 1024**2, 1024, 64),
        )
    assert not marker.exists() and pids and not psutil.pid_exists(pids[0])


@_REQUIRES_DARWIN
def test_darwin_deadline_reaps_real_engine_group(tmp_path):
    pid = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)']);"
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(10)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_process(
            [sys.executable, "-c", script, str(pid)],
            input=None,
            cwd=tmp_path,
            timeout=0.5,
            limits=ProcessLimits(3, 128 * 1024**2, 1024, 64),
        )
    child = int(pid.read_text())
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE
