from __future__ import annotations

import importlib
import json
import logging
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from app.utils.operational_errors import BOUNDARY_ERRORS


@pytest.fixture
def relay(monkeypatch, tmp_path):
    from app.services import mobile_relay_desktop_client as module

    monkeypatch.setattr(module, "_CONFIG_FILE", tmp_path / "binding.json")
    monkeypatch.setattr(module, "_LEGACY_CONFIG_FILE", tmp_path / "legacy.json")
    monkeypatch.setattr(module, "_LEGACY_MIGRATION_DONE", False)
    monkeypatch.setattr(module, "_INFLIGHT", set())
    monkeypatch.setattr(module, "_INFLIGHT_LOCK", threading.Lock())
    monkeypatch.setattr(module, "_STATE_LOCK", threading.Lock())
    monkeypatch.setattr(module, "_STOP_EVENT", threading.Event())
    monkeypatch.setattr(module, "_WORKER_THREAD", None)
    monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "1")
    module._write_config(
        {
            "relay_id": "old-relay",
            "desktop_token": "old-secret",
            "relay_base_url": "https://relay.invalid/",
        }
    )
    return module


def fake_transport(relay, monkeypatch, handler):
    clients = []

    def factory(timeout):
        client = httpx.Client(
            transport=httpx.MockTransport(handler), timeout=timeout, trust_env=False
        )
        clients.append(client)
        return client

    monkeypatch.setattr(relay, "_relay_http_client", factory)
    return clients


def fake_threads(relay, monkeypatch, *, fail=False):
    started = []

    class Worker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            if fail:
                raise RuntimeError("synthetic start failure")
            started.append(self.kwargs)

    monkeypatch.setattr(relay.threading, "Thread", Worker)
    return started


def test_poll_never_exceeds_available_capacity(relay, monkeypatch):
    started = fake_threads(relay, monkeypatch)
    clients = fake_transport(
        relay,
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"data": {"tasks": [{"task_id": "a"}, {"task_id": "b"}]}}
        ),
    )
    relay._poll_once()
    assert all(client.is_closed for client in clients)
    assert len(started) == 1
    assert len(relay._INFLIGHT) == 1


def test_failed_worker_start_releases_claim(relay, monkeypatch):
    fake_threads(relay, monkeypatch, fail=True)
    fake_transport(
        relay,
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": {"tasks": [{"task_id": "a"}]}}),
    )
    with pytest.raises(RuntimeError, match="synthetic start failure"):
        relay._poll_once()
    assert set() == relay._INFLIGHT


def test_completed_worker_cannot_release_a_replacement_claim(relay, monkeypatch):
    workers = fake_threads(relay, monkeypatch)
    real_complete = relay._complete_relay_task
    monkeypatch.setattr(relay, "_execute_task", lambda task: {"ok": True})

    def handler(request):
        tasks = [{"task_id": "same-task"}] if request.url.path.endswith("/poll") else []
        return httpx.Response(200, json={"data": {"tasks": tasks}})

    clients = fake_transport(relay, monkeypatch, handler)

    def complete_then_reclaim(task, relay_id, desktop_token, base_url):
        real_complete(task, relay_id, desktop_token, base_url)
        relay._poll_once()

    monkeypatch.setattr(relay, "_complete_relay_task", complete_then_reclaim)
    relay._poll_once()
    workers[0]["target"]()
    try:
        assert len(workers) == 2
        assert {"same-task"} == relay._INFLIGHT
        relay._poll_once()
        assert len(workers) == 2
        assert all(client.is_closed for client in clients)
    finally:
        relay._STOP_EVENT.set()
        workers[1]["target"]()
    assert set() == relay._INFLIGHT


def test_poll_response_cannot_overwrite_replacement_binding(relay, monkeypatch):
    replacement = {
        "relay_id": "new-relay",
        "desktop_token": "new-secret",
        "relay_base_url": "https://new.invalid/",
    }

    def handler(request):
        relay._write_config(replacement)
        return httpx.Response(200, json={"data": {"desktop": {"status": "paired"}, "tasks": []}})

    fake_transport(relay, monkeypatch, handler)
    relay._poll_once()
    assert relay._read_config() == replacement


def test_renew_response_cannot_overwrite_replacement_binding(relay, monkeypatch):
    replacement = {
        "relay_id": "new-relay",
        "desktop_token": "new-secret",
        "relay_base_url": "https://new.invalid/",
    }

    def handler(request):
        assert request.url.path.endswith("/renew")
        relay._write_config(replacement)
        return httpx.Response(
            200, json={"data": {"relay_id": "old-relay", "pairing_code": "123456"}}
        )

    fake_transport(relay, monkeypatch, handler)
    start = Mock(return_value=True)
    monkeypatch.setattr(relay, "start_desktop_relay_poller", start)
    result = relay.register_desktop_relay(host="127.0.0.1", port=17500)
    assert relay._read_config() == replacement
    assert result is None
    start.assert_not_called()


def test_stop_during_poll_does_not_start_returned_tasks(relay, monkeypatch):
    started = fake_threads(relay, monkeypatch)

    def handler(request):
        relay._STOP_EVENT.set()
        return httpx.Response(200, json={"data": {"tasks": [{"task_id": "a"}]}})

    fake_transport(relay, monkeypatch, handler)
    relay._poll_once()
    assert started == []
    assert set() == relay._INFLIGHT


def test_gc_rejects_symlinked_scratch_root(relay, monkeypatch, tmp_path):
    temp_root = tmp_path / "temp-root"
    temp_root.mkdir()
    external = tmp_path / "external"
    victim = external / "old-project"
    victim.mkdir(parents=True)
    (victim / "keep.txt").write_text("owned outside cleanup root")
    os.utime(victim, (0, 0))
    (temp_root / "xcmax_product_scratch").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(relay.tempfile, "gettempdir", lambda: str(temp_root))
    relay._gc_orphan_workspaces()
    assert (victim / "keep.txt").read_text() == "owned outside cleanup root"


def test_repeated_start_does_not_collect_active_workspaces(relay, monkeypatch):
    worker = Mock()
    worker.is_alive.return_value = True
    monkeypatch.setattr(relay, "_WORKER_THREAD", worker)
    collect = Mock(return_value=0)
    monkeypatch.setattr(relay, "_gc_orphan_workspaces", collect)
    assert relay.start_desktop_relay_poller() is True
    collect.assert_not_called()


def test_accepted_dispatch_without_ids_does_not_consume_unrelated_result(relay, monkeypatch):
    service = Mock()
    service.invoke.return_value = {"dispatch": {"status": "accepted", "accepted": True}}
    service.list_messages.return_value = [
        {
            "role": "assistant",
            "kind": "codex_result",
            "request_id": "another-request",
            "task_id": "another-task",
            "body": "hello from another request",
        }
    ]
    for name in ("Claude", "Codex", "Cursor", "Trae"):
        monkeypatch.setattr(relay, f"{name}SuperEmployeeService", lambda: service)
    result = relay._execute_task(
        {"kind": "codex.invoke", "created_by_user_id": 7, "payload": {"message": "hello"}}
    )
    assert result["_relay_status"] == "blocked"
    assert "assistant_message" not in result.get("codex", {})
    service.list_messages.assert_not_called()


@pytest.mark.parametrize("field", ["relay_id", "desktop_token", "relay_base_url"])
def test_poll_checks_every_binding_field_before_dispatch(relay, monkeypatch, field):
    replacement = {**relay._read_config(), field: "replacement"}
    started = fake_threads(relay, monkeypatch)

    def handler(request):
        relay._write_config(replacement)
        return httpx.Response(200, json={"data": {"tasks": [{"task_id": "old-task"}]}})

    clients = fake_transport(relay, monkeypatch, handler)
    relay._poll_once()
    assert relay._read_config() == replacement
    assert started == []
    assert all(client.is_closed for client in clients)


def test_poll_updates_preserve_new_qr_for_the_same_binding(relay, monkeypatch):
    def handler(request):
        relay._write_config({**relay._read_config(), "pairing_code": "654321"})
        return httpx.Response(200, json={"data": {"desktop": {"status": "paired"}, "tasks": []}})

    fake_transport(relay, monkeypatch, handler)
    relay._poll_once()
    config = relay._read_config()
    assert config["pairing_code"] == "654321"
    assert config["paired"] is True
    assert config["last_relay_sync_at"] > 0


def test_unsupported_renewal_reregister_cannot_replace_a_new_binding(relay, monkeypatch):
    replacement = {
        "relay_id": "new-relay",
        "desktop_token": "new-secret",
        "relay_base_url": "https://new.invalid/",
    }
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/renew"):
            return httpx.Response(405)
        relay._write_config(replacement)
        return httpx.Response(
            200,
            json={
                "data": {
                    "relay_id": "stale-reregister",
                    "desktop_token": "stale-secret",
                    "pairing_code": "123456",
                }
            },
        )

    clients = fake_transport(relay, monkeypatch, handler)
    start = Mock(return_value=True)
    monkeypatch.setattr(relay, "start_desktop_relay_poller", start)
    assert relay.register_desktop_relay(host="127.0.0.1", port=17500) is None
    assert relay._read_config() == replacement
    assert [path.rsplit("/", 1)[-1] for path in calls] == ["renew", "register"]
    assert all(client.is_closed for client in clients)
    start.assert_not_called()


def test_real_poll_thread_stops_after_http_closes_without_dispatch(relay, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    errors = []
    collect = Mock(return_value=0)
    execute = Mock(side_effect=AssertionError("stopped poll must not execute a task"))
    monkeypatch.setattr(relay, "_gc_orphan_workspaces", collect)
    monkeypatch.setattr(relay, "_execute_task", execute)
    monkeypatch.setenv("XCAGI_RELAY_POLL_TIMEOUT_SEC", "1")

    def handler(request):
        calls.append(request.url.path)
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, json={"data": {"tasks": [{"task_id": "late-task"}]}})

    def stop():
        try:
            relay.stop_desktop_relay_poller()
        except BOUNDARY_ERRORS as exc:
            errors.append(exc)

    clients = fake_transport(relay, monkeypatch, handler)
    stopper = threading.Thread(target=stop)
    worker = None
    try:
        assert relay.start_desktop_relay_poller() is True
        worker = relay._WORKER_THREAD
        assert worker is not None
        assert entered.wait(3)
        assert relay.start_desktop_relay_poller() is True
        collect.assert_called_once_with()
        assert relay._STATE_LOCK.acquire(blocking=False)
        relay._STATE_LOCK.release()
        relay._poll_once()
        assert len(calls) == 1
        stopper.start()
        assert relay._STOP_EVENT.wait(3)
        release.set()
        stopper.join(3)
        worker.join(3)
        assert not stopper.is_alive()
        assert not worker.is_alive()
        assert relay._WORKER_THREAD is None
        assert set() == relay._INFLIGHT
        assert all(client.is_closed for client in clients)
        assert errors == []
        execute.assert_not_called()
    finally:
        relay._STOP_EVENT.set()
        release.set()
        if stopper.ident is not None:
            stopper.join(3)
        if worker is not None:
            worker.join(3)


@pytest.mark.parametrize("complete_status", [200, 503])
def test_real_task_worker_deduplicates_and_releases_after_reporting(
    relay, monkeypatch, complete_status
):
    entered, release = threading.Event(), threading.Event()
    workers = []
    requests = []
    original_factory = relay._create_worker
    monkeypatch.setenv("XCAGI_RELAY_MAX_CONCURRENT", "2")

    def create_worker(callback, name):
        worker = original_factory(callback, name)
        workers.append(worker)
        return worker

    def execute(task):
        entered.set()
        assert release.wait(3)
        return {"ok": True, "_relay_status": "completed"}

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/poll"):
            return httpx.Response(200, json={"data": {"tasks": [{"task_id": "owned-task"}]}})
        return httpx.Response(complete_status, json={})

    monkeypatch.setattr(relay, "_create_worker", create_worker)
    monkeypatch.setattr(relay, "_execute_task", execute)
    clients = fake_transport(relay, monkeypatch, handler)
    try:
        relay._poll_once()
        assert entered.wait(3)
        assert {"owned-task"} == relay._INFLIGHT
        relay._poll_once()
        assert len(workers) == 1
        release.set()
        workers[0].join(3)
        assert not workers[0].is_alive()
        assert set() == relay._INFLIGHT
        assert len(requests) == 3
        payload = json.loads(requests[-1].content)
        assert payload["status"] == "completed"
        assert payload["relay_id"] == "old-relay"
        assert payload["result"]["elapsed_seconds"] >= 0
        assert all(client.is_closed for client in clients)
    finally:
        release.set()
        for worker in workers:
            worker.join(3)


def test_stop_during_startup_waits_without_holding_state_lock(relay, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    results, errors = [], []
    poll = Mock()
    monkeypatch.setenv("XCAGI_RELAY_POLL_TIMEOUT_SEC", "1")
    monkeypatch.setattr(relay, "_poll_loop", poll)

    def collect():
        entered.set()
        assert release.wait(3)
        return 0

    def start():
        try:
            results.append(relay.start_desktop_relay_poller())
        except BOUNDARY_ERRORS as exc:
            errors.append(exc)

    monkeypatch.setattr(relay, "_gc_orphan_workspaces", collect)
    starter = threading.Thread(target=start)
    stopper = threading.Thread(target=relay.stop_desktop_relay_poller)
    try:
        starter.start()
        assert entered.wait(3)
        assert relay._STATE_LOCK.acquire(blocking=False)
        relay._STATE_LOCK.release()
        stopper.start()
        assert relay._STOP_EVENT.wait(3)
        release.set()
        starter.join(3)
        stopper.join(3)
        assert not starter.is_alive() and not stopper.is_alive()
        assert results == [False]
        assert errors == []
        assert relay._WORKER_THREAD is None
        poll.assert_not_called()
    finally:
        release.set()
        relay._STOP_EVENT.set()
        starter.join(3)
        if stopper.ident is not None:
            stopper.join(3)


def test_failed_poller_start_clears_reference_and_allows_retry(relay, monkeypatch):
    worker = Mock()
    worker.start.side_effect = RuntimeError("synthetic poller start failure")
    worker.is_alive.return_value = False
    monkeypatch.setattr(relay, "_create_worker", lambda callback, name: worker)
    monkeypatch.setattr(relay, "_gc_orphan_workspaces", lambda: 0)
    with pytest.raises(RuntimeError, match="synthetic poller start failure"):
        relay.start_desktop_relay_poller()
    assert relay._WORKER_THREAD is None
    worker.start.side_effect = None
    assert relay.start_desktop_relay_poller() is True
    relay.stop_desktop_relay_poller()
    assert relay._WORKER_THREAD is None


def test_poller_can_request_its_own_stop(relay, monkeypatch):
    called = threading.Event()
    errors = []

    def loop():
        try:
            relay.stop_desktop_relay_poller()
            called.set()
        except BOUNDARY_ERRORS as exc:
            errors.append(exc)

    monkeypatch.setattr(relay, "_poll_loop", loop)
    monkeypatch.setattr(relay, "_gc_orphan_workspaces", lambda: 0)
    assert relay.start_desktop_relay_poller() is True
    worker = relay._WORKER_THREAD
    assert worker is not None
    try:
        assert called.wait(3)
        worker.join(3)
        assert not worker.is_alive()
        assert errors == []
        relay.stop_desktop_relay_poller()
        assert relay._WORKER_THREAD is None
    finally:
        relay._STOP_EVENT.set()
        worker.join(3)


def test_poll_loop_backoff_recovers_without_real_wait(relay, monkeypatch):
    waits = []

    class Stop:
        def is_set(self):
            return len(waits) == 4

        def wait(self, seconds):
            waits.append(seconds)

    poll = Mock(
        side_effect=[
            httpx.ConnectError("synthetic"),
            RuntimeError("synthetic"),
            httpx.ConnectError("synthetic"),
            None,
        ]
    )
    monkeypatch.setattr(relay, "_STOP_EVENT", Stop())
    monkeypatch.setattr(relay, "_poll_once", poll)
    monkeypatch.setenv("XCAGI_RELAY_POLL_INTERVAL_SEC", "4")
    monkeypatch.setenv("XCAGI_RELAY_POLL_MAX_BACKOFF_SEC", "20")
    relay._poll_loop()
    assert waits == [4, 8, 16, 4]
    assert poll.call_count == 4


@pytest.mark.parametrize("relative", ["xcagi-wt-link", "xcmax_product_scratch/link"])
def test_gc_leaves_symlink_entries_and_targets_intact(relay, monkeypatch, tmp_path, relative):
    root = tmp_path / "gc-root"
    root.mkdir()
    target = tmp_path / "preserved"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    os.utime(target, (0, 0))
    link = root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(relay.tempfile, "gettempdir", lambda: str(root))
    assert relay._gc_orphan_workspaces() == 0
    assert link.is_symlink()
    assert (target / "keep.txt").read_text() == "keep"


def test_config_component_atomic_failure_preserves_private_binding(monkeypatch, tmp_path):
    from app.application.desktop_relay import configuration
    from app.application.desktop_relay.configuration import ConfigurationPorts, RelayConfigStore

    path = tmp_path / "private.json"
    store: RelayConfigStore
    store = RelayConfigStore(
        ConfigurationPorts(
            path=lambda: path,
            legacy_path=lambda: tmp_path / "legacy.json",
            migration_done=lambda: False,
            mark_migrated=lambda: None,
            read_config=lambda: store.read(),
            write_config=lambda data: store.write(data),
            base_url=lambda: "https://relay.invalid/",
        ),
        logging.getLogger("relay-test-config"),
    )
    original = {"relay_id": "r", "desktop_token": "private"}
    store.write(original)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    monkeypatch.setattr(
        configuration.os, "replace", Mock(side_effect=OSError("synthetic replace failure"))
    )
    with pytest.raises(OSError, match="synthetic replace failure"):
        store.write({"relay_id": "new"})
    assert store.read() == original
    assert list(tmp_path.glob(".mobile_relay_*")) == []


def test_independent_executor_waits_for_correlated_result_with_fake_clock():
    from app.application.desktop_relay import messages
    from app.application.desktop_relay.execution import ExecutionPorts, RelayTaskExecutor
    from app.application.desktop_relay.ports import JsonObject

    class Clock:
        now = 0.0

        def __init__(self):
            self.sleeps = []

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    class Service:
        reads = 0

        def invoke(self, *, user_id: int, message: str, context: JsonObject) -> JsonObject:
            assert user_id == 7
            assert context["force_cli_direct"] is True
            return {"dispatch": {"accepted": True, "request_id": "req-now", "task_id": "task-now"}}

        def list_messages(self, *, user_id: int, limit: int) -> list[JsonObject]:
            self.reads += 1
            return [
                {
                    "role": "assistant",
                    "kind": "codex_result",
                    "request_id": "other" if self.reads == 1 else "req-now",
                    "task_id": "task-now",
                    "body": "修改了 app/example.py；测试通过",
                }
            ]

    clock, service = Clock(), Service()
    factory = lambda: service
    executor = RelayTaskExecutor(
        ExecutionPorts(
            ensure_services=lambda: None,
            claude_factory=lambda: factory,
            codex_factory=lambda: factory,
            cursor_factory=lambda: factory,
            trae_factory=lambda: factory,
            git_op=Mock(side_effect=AssertionError("unexpected git operation")),
            git_message=messages._git_op_from_message,
            classify_result=messages._classify_terminal_result,
            terminal_message=messages._terminal_codex_message,
            tool_calls=messages._extract_tool_calls,
            environment=lambda: {
                "XCAGI_RELAY_CODEX_WAIT_INTERVAL_SEC": "0.25",
                "XCAGI_RELAY_CODEX_WAIT_TIMEOUT_SEC": "2",
            },
            monotonic=lambda: clock.now,
            sleep=clock.sleep,
        ),
        logging.getLogger("relay-test-executor"),
    )
    result = executor.execute(
        {"kind": "codex.invoke", "created_by_user_id": 7, "payload": {"message": "修复 example.py"}}
    )
    assert result["_relay_status"] == "completed"
    assert result["codex"]["assistant_message"]["request_id"] == "req-now"
    assert service.reads == 2
    assert clock.sleeps == [0.25]


def test_components_import_without_the_composition_root():
    script = """
import importlib
import importlib.abc
import sys

class DenyRoot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('app.services.mobile_relay_desktop_client'):
            raise AssertionError('component imported its composition root')

sys.meta_path.insert(0, DenyRoot())
for name in ('ports', 'configuration', 'registration', 'lifecycle', 'polling', 'execution', 'messages', 'cleanup'):
    importlib.import_module('app.application.desktop_relay.' + name)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_lifespan_resumes_through_existing_late_callbacks(relay, monkeypatch):
    from fastapi import FastAPI

    lifespan = importlib.import_module("app.fastapi_app.lifespan")

    migrate = Mock()
    start = Mock(return_value=True)
    monkeypatch.setattr(lifespan, "passive_node_enabled", lambda: False)
    monkeypatch.setattr(relay, "_migrate_legacy_config_once", migrate)
    monkeypatch.setattr(relay, "start_desktop_relay_poller", start)
    app = FastAPI()
    await lifespan._init_mobile_relay_desktop_async(app)
    migrate.assert_called_once_with()
    start.assert_called_once_with()
    assert app.state.mobile_relay_desktop_running is True


def test_application_facade_keeps_keyword_forwarding_and_fallback(relay, monkeypatch):
    from app.application.facades import mobile_relay_facade

    register = Mock(return_value=None)
    cached = Mock(return_value={"relay_id": "visible"})
    monkeypatch.setattr(relay, "register_desktop_relay", register)
    monkeypatch.setattr(relay, "cached_desktop_relay_payload", cached)
    result = mobile_relay_facade.register_desktop_relay(host="127.0.0.1", port=17500)
    assert result == {"success": False, "message": "桌面中继注册未返回结果"}
    register.assert_called_once_with(host="127.0.0.1", port=17500)
    assert mobile_relay_facade.cached_desktop_relay_payload() == {"relay_id": "visible"}
    cached.assert_called_once_with()


def test_desktop_components_round_trip_through_local_asgi_and_sqlite(relay, monkeypatch, tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.fastapi_routes import mobile_api_extensions as routes
    from app.services import mobile_relay_service as cloud

    engine = create_engine(f"sqlite:///{tmp_path / 'relay-components.db'}")
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def database():
        with sessions.begin() as session:
            yield session

    monkeypatch.setattr(cloud, "get_db", database)
    notify = Mock()
    monkeypatch.setattr(cloud.MobileRelayService, "_notify_task_creator", staticmethod(notify))
    monkeypatch.setattr(routes, "_pairing_rate_allowed", lambda *args: True)
    app = FastAPI()
    app.include_router(routes.extension_router, prefix="/api/mobile/v1")
    user = SimpleNamespace(
        id=7,
        username="fixture-admin",
        display_name="fixture",
        role="admin",
        is_active=True,
        account_id="a7",
        tenant_id="t7",
    )
    app.dependency_overrides[routes.get_mobile_user] = lambda: user
    monkeypatch.setattr(relay, "_relay_base_url", lambda: "https://relay.invalid/")
    start = Mock(return_value=True)
    monkeypatch.setattr(relay, "start_desktop_relay_poller", start)
    execute = Mock(
        return_value={"ok": True, "answer": "local result", "_relay_status": "completed"}
    )
    monkeypatch.setattr(relay, "_execute_task", execute)
    workers = []
    original_factory = relay._create_worker

    def create_worker(callback, name):
        worker = original_factory(callback, name)
        workers.append(worker)
        return worker

    monkeypatch.setattr(relay, "_create_worker", create_worker)
    try:
        with TestClient(app, client=("127.0.0.1", 50000)) as server:

            def bridge(request):
                response = server.request(
                    request.method,
                    request.url.path,
                    content=request.content,
                    headers={"Content-Type": "application/json"},
                )
                return httpx.Response(
                    response.status_code,
                    content=response.content,
                    headers={"Content-Type": "application/json"},
                )

            clients = fake_transport(relay, monkeypatch, bridge)
            registered = relay.register_desktop_relay(host="127.0.0.1", port=17500, force_new=True)
            assert registered is not None
            start.assert_called_once_with()
            bound = server.post(
                "/api/mobile/v1/relay/mobile/bind-account",
                json={"pairing_code": registered["pairing_code"]},
            )
            assert bound.status_code == 200
            created = server.post(
                "/api/mobile/v1/relay/tasks",
                json={
                    "relay_id": registered["relay_id"],
                    "kind": "codex.invoke",
                    "payload": {"message": "hello"},
                },
            )
            assert created.status_code == 200
            task = created.json()["data"]["task"]
            relay._poll_once()
            assert len(workers) == 1
            workers[0].join(3)
            assert not workers[0].is_alive()
            status = server.get(f"/api/mobile/v1/relay/tasks/{task['task_id']}")
            assert status.status_code == 200
            final_task = status.json()["data"]["task"]
            assert final_task["status"] == "completed"
            assert final_task["result"]["answer"] == "local result"
            execute.assert_called_once()
            assert execute.call_args.args[0]["created_by_user_id"] == 7
            assert set() == relay._INFLIGHT
            cached = relay.cached_desktop_relay_payload()
            assert cached["paired"] is True
            assert cached["mobile_username"] == "fixture-admin"
            assert "desktop_token" not in cached
            assert all(client.is_closed for client in clients)
            notify.assert_called_once()
    finally:
        for worker in workers:
            worker.join(3)
        engine.dispose()
