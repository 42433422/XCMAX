"""Exercise collector failure boundaries with local HTTP and real owned processes.

These are regression tests, never Windows/macOS acceptance measurements.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import psutil
import pytest

SHA = "a" * 40
VERSION = "1.0.0.7"


@pytest.fixture
def runner(monkeypatch):
    directory = Path(__file__).resolve().parents[2] / "scripts/release"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "desktop_soak_under_test", directory / "desktop_soak.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def endpoint_server():
    runtime = {"status": "healthy", "blockers": [], "degraded_reasons": []}
    responses = {
        "/api/ping": (200, {"pong": True}),
        "/api/health": (
            200,
            {"status": "healthy", "git_sha": SHA, "runtime": runtime, "degradedReasons": []},
        ),
        "/api/desktop/status": (
            200,
            {
                "desktopMode": True,
                "readyForUi": True,
                "runtimeStatus": "healthy",
                "degraded": False,
                "degradedReasons": [],
                "runtimeIntegrity": runtime,
            },
        ),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, payload = responses[self.path]
            self.send_response(status)
            self.end_headers()
            self.wfile.write(
                payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            )

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{server.server_port}", timeout=1, trust_env=False
        ) as client:
            yield responses, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_probe_observes_all_healthy_endpoints(runner, endpoint_server):
    _, client = endpoint_server
    assert runner.probe(client, SHA) == dict.fromkeys(
        ("/api/ping", "/api/health", "/api/desktop/status"), True
    )


@pytest.mark.parametrize(
    "endpoint,status,changes",
    [
        ("/api/health", 503, {}),
        ("/api/health", 200, {"git_sha": "b" * 40}),
        ("/api/health", 200, {"runtime": None}),
        ("/api/health", 200, {"runtime": []}),
        ("/api/health", 200, {"runtime": {"status": "healthy", "blockers": ["runtime_blocked"]}}),
        ("/api/desktop/status", 200, {"readyForUi": False}),
        ("/api/desktop/status", 200, {"degraded": True}),
        ("/api/desktop/status", 200, {"runtimeIntegrity": None}),
        ("/api/desktop/status", 200, {"runtimeIntegrity": {}}),
        (
            "/api/desktop/status",
            200,
            {"runtimeIntegrity": {"status": "healthy", "blockers": ["runtime_blocked"]}},
        ),
    ],
)
def test_one_failed_endpoint_cannot_be_reset_by_the_next_success(
    runner, endpoint_server, endpoint, status, changes
):
    responses, client = endpoint_server
    responses[endpoint] = status, {**responses[endpoint][1], **changes}
    for _ in range(2):
        result = runner.probe(client, SHA)
        assert result[endpoint] is False
        assert all(value for path, value in result.items() if path != endpoint)


def test_http_success_with_malformed_json_is_not_readiness(runner, endpoint_server):
    responses, client = endpoint_server
    responses["/api/ping"] = 200, b"not-json"
    assert runner.probe(client, SHA)["/api/ping"] is False


@pytest.fixture
def spawn_owned():
    children = []

    def spawn(code):
        child = subprocess.Popen(
            [sys.executable, "-u", "-c", code], stdout=subprocess.PIPE, text=True
        )
        children.append(child)
        return child

    yield spawn
    for child in children:
        if child.poll() is None:
            try:
                descendants = psutil.Process(child.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            # Windows terminate() does not invoke the parent's Python SIGTERM
            # handler; explicitly reclaim this fixture's descendants on failures.
            for descendant in reversed(descendants):
                try:
                    descendant.kill()
                except psutil.NoSuchProcess:
                    pass
            child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        if child.stdout:
            child.stdout.close()


PARENT = """
import signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
def stop(*_args):
    child.terminate()
    child.wait(timeout=5)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
print(child.pid, flush=True)
time.sleep(120)
stop()
"""


def test_real_process_tree_metrics_and_cleanup_preserve_unrelated_process(runner, spawn_owned):
    parent = spawn_owned(PARENT)
    backend_pid = int(parent.stdout.readline())
    unrelated = spawn_owned("import time; time.sleep(120)")
    executable = Path(sys.executable).resolve()
    tree = runner.ProcessTree(parent.pid, executable, executable)
    sample = tree.sample()
    assert sample["root_pid"] == parent.pid and sample["backend_pid"] == backend_pid
    assert sample["process_count"] >= 2 and sample["rss_bytes"] > 0
    assert sample["handles"] > 0 and sample["root_create_time"] > 0
    assert tree.cleanup() == 0
    assert parent.poll() is not None
    assert unrelated.poll() is None
    assert tree.cleanup() == 0


def test_wrong_executable_or_missing_owned_backend_cannot_be_measured(
    runner, spawn_owned, tmp_path
):
    parent = spawn_owned("import time; time.sleep(120)")
    executable = Path(sys.executable).resolve()
    tree = runner.ProcessTree(parent.pid, executable, executable)
    with pytest.raises(ValueError, match="owned_backend_missing_or_ambiguous"):
        tree.sample()
    impostor = tmp_path / "different-executable"
    impostor.write_bytes(b"not the launched process")
    tree.binary = impostor
    with pytest.raises(ValueError, match="desktop_process_missing_or_replaced"):
        tree.sample()
    assert tree.cleanup() == 0


def test_child_disappearing_during_observation_does_not_abort_cleanup(
    runner, spawn_owned, monkeypatch
):
    parent = spawn_owned(PARENT)
    backend_pid = int(parent.stdout.readline())
    executable = Path(sys.executable).resolve()
    tree = runner.ProcessTree(parent.pid, executable, executable)
    observed = next(p for p in tree.living() if p.pid == backend_pid)
    monkeypatch.setattr(tree.root, "children", lambda recursive: [])

    def disappear():
        observed.kill()
        raise psutil.NoSuchProcess(backend_pid)

    monkeypatch.setattr(observed, "status", disappear)
    assert [p.pid for p in tree.living()] == [parent.pid]
    assert tree.cleanup() == 0


def arguments(tmp_path):
    return argparse.Namespace(
        binary=Path(sys.executable).resolve(),
        release_sha=SHA,
        product_version=VERSION,
        output=tmp_path / "native.json",
        duration_seconds=28800,
        interval_seconds=30,
    )


@pytest.fixture
def event_observer(runner, tmp_path):
    args = arguments(tmp_path)
    report = {"phase": "steady", "events": [], "blockers": [], "samples": []}
    desktop = runner.Desktop(args, None, tmp_path / "profile", args.binary, report)

    class Page:
        def __init__(self):
            self.listeners = {}

        def on(self, name, callback):
            self.listeners.setdefault(name, []).append(callback)

        def emit(self, name, *values):
            for callback in tuple(self.listeners.get(name, [])):
                callback(*values)

    page = Page()
    desktop.observe_page(page)
    try:
        yield desktop, report, page
    finally:
        desktop.client.close()


def test_crash_between_samples_is_immediately_persisted_and_blocks_acceptance(event_observer):
    desktop, report, page = event_observer
    report["samples"].append({"elapsed_seconds": 0, "gui": True})
    desktop.observe_page(page)  # Reattaching the same observer must not duplicate events.
    page.emit("crash", page)
    persisted = json.loads(desktop.args.output.read_text())
    assert persisted["samples"] == [{"elapsed_seconds": 0, "gui": True}]
    assert persisted["blockers"] == ["unexpected_renderer_event"]
    assert len(persisted["events"]) == 1
    assert persisted["events"][0]["kind"] == "renderer_crash"
    assert persisted["events"][0]["phase"] == "steady"


def test_page_error_is_redacted_and_is_not_allowed_during_injected_crash(event_observer):
    desktop, report, page = event_observer
    report["phase"] = "renderer_crash"
    message = "login failed: user=private-account password=private-credential"
    page.emit("pageerror", RuntimeError(message))
    evidence = desktop.args.output.read_text()
    persisted = json.loads(evidence)
    assert persisted["blockers"] == ["unexpected_renderer_event"]
    assert persisted["events"][0]["kind"] == "renderer_page_error"
    assert persisted["events"][0]["message_sha256"] == hashlib.sha256(message.encode()).hexdigest()
    assert "private-account" not in evidence and "private-credential" not in evidence


def test_renderer_event_overflow_stays_bounded_and_blocks_acceptance(event_observer):
    desktop, report, page = event_observer
    report["phase"] = "renderer_crash"
    for _ in range(100):
        page.emit("crash", page)
    assert report["blockers"] == []
    for _ in range(20):
        page.emit("crash", page)
    persisted = json.loads(desktop.args.output.read_text())
    assert len(report["events"]) == len(persisted["events"]) == 100
    assert report["blockers"] == persisted["blockers"] == ["renderer_event_limit_exceeded"]


def test_linux_writes_blocked_receipt_without_launching_or_leaking_credentials(
    runner, tmp_path, monkeypatch
):
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XCAGI_TEST_USER", "must-not-publish-user")
    monkeypatch.setenv("XCAGI_TEST_PASS", "must-not-publish-password")
    args = arguments(tmp_path)
    assert asyncio.run(runner.run(args)) == 1
    evidence = args.output.read_text()
    report = json.loads(evidence)
    assert report["status"] == "blocked" and report["platform"] == "unsupported"
    assert report["blockers"] == ["native_windows_or_macos_required"]
    assert report["samples"] == [] and report["finished_at"]
    assert "must-not-publish" not in evidence and not args.output.with_suffix(".tmp").exists()


def test_cancellation_cleans_owned_process_and_commits_failure_receipt(
    runner, tmp_path, monkeypatch, spawn_owned
):
    monkeypatch.setattr(runner.platform, "system", lambda: "Windows")
    monkeypatch.setenv("XCAGI_TEST_USER", "acceptance-fixture")
    monkeypatch.setenv("XCAGI_TEST_PASS", "private-fixture-password")
    args = arguments(tmp_path)
    monkeypatch.setattr(runner, "artifact_identity", lambda *_: ({}, args.binary))
    spawned = []

    class UnusedDriver:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *_args):
            return False

    # The failure occurs before GUI attachment; keep optional browser dependencies
    # outside core backend tests while exercising real cancellation and processes.
    monkeypatch.setitem(
        sys.modules,
        "playwright.async_api",
        SimpleNamespace(Error=RuntimeError, async_playwright=UnusedDriver),
    )

    async def exercise():
        started = asyncio.Event()

        async def interrupted_launch(desktop):
            desktop.child = spawn_owned("import time; time.sleep(120)")
            spawned.append(desktop.child)
            desktop.tree = runner.ProcessTree(desktop.child.pid, args.binary, args.binary)
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(runner.Desktop, "launch", interrupted_launch)
        task = asyncio.create_task(runner.run(args))
        await asyncio.wait_for(started.wait(), timeout=15)
        task.cancel()
        return await asyncio.wait_for(task, timeout=30)

    assert asyncio.run(exercise()) == 1
    report = json.loads(args.output.read_text())
    assert report["status"] == "blocked" and "CancelledError" in report["blockers"]
    assert report["samples"] == [] and spawned[0].poll() is not None
    assert "private-fixture-password" not in args.output.read_text()


def test_checkpoint_rejects_nonfinite_values_without_destroying_previous_evidence(runner, tmp_path):
    path = tmp_path / "checkpoint.json"
    runner.checkpoint(path, {"status": "running", "samples": [1]})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        runner.checkpoint(path, {"samples": [float("nan")]})
    assert path.read_bytes() == before
