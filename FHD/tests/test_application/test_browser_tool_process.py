"""Real AgentToolExecutor -> retained spawn worker -> official MCP stdio SDK."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from app.application.agent_orchestrator import browser_tool_process as workers
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import invalidate_tool_specs_cache
from app.application.tools.mcp import registry
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_infrastructure.test_mcp_persistent_sessions import _SERVER


@pytest.fixture
def browser(tmp_path, monkeypatch, trusted_actor):
    script = tmp_path / "server.py"
    script.write_text(
        _SERVER.replace(
            "server.run(transport=",
            """
@server.tool()
async def browser_wait_for(text: str) -> dict:
    with log.open("a") as stream:
        stream.write("hang-entered\\n")
    await asyncio.sleep(2)
    with log.open("a") as stream:
        stream.write("late-write\\n")
    return dict(state)

server.run(transport=""",
        ),
        encoding="utf-8",
    )
    log = tmp_path / "events.log"
    config_file = tmp_path / "servers.json"
    config_file.write_text(
        json.dumps(
            {
                "servers": {
                    "browser-contract": {
                        "command": sys.executable,
                        "args": [str(script), str(log)],
                        "session_mode": "persistent",
                        "session_start_tools": ["browser_navigate", "browser_snapshot"],
                        "browser": True,
                        "timeout_seconds": 10,
                        "max_sessions": 2,
                        "read_only_tools": ["browser_snapshot"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XCAGI_MCP_SERVERS_FILE", str(config_file))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_REQUIRE_REDIS_RATE_LIMIT", "0")
    monkeypatch.delenv("XCAGI_MCP_ENABLED", raising=False)
    registry.reset_mcp_cache_for_tests()
    invalidate_tool_specs_cache()
    tool = registry.tool_id_for("browser-contract")
    actions = ("browser_navigate", "browser_snapshot", "browser_click", "browser_wait_for")
    actor = trusted_actor(permissions=[f"tool.{tool}.{action}" for action in actions])
    context = {**actor.context, "run_id": "browser-worker-run", "node_outputs": {}}
    try:
        yield tool, context, log, actor
    finally:
        workers.close_all_browser_workers()
        registry.reset_mcp_cache_for_tests()
        invalidate_tool_specs_cache()


def call(browser, action, params=None, *, timeout=25, context=None):
    tool, ctx, _log, _actor = browser
    ctx = ctx if context is None else context
    node = f"step-{len(ctx['node_outputs'])}-{action}"
    output = AgentToolExecutor().execute_with_deadline(
        AgentStep(node_id=node, tool_id=tool, action=action, params=params or {}),
        runtime_context={**ctx, "idempotency_key": node},
        deadline_monotonic=time.monotonic() + timeout,
    )
    ctx["node_outputs"][node] = output
    return output


def state(result):
    assert result.get("success") is True, result
    return result.get("structured_content") or json.loads(result["content"])


def test_actual_executor_keeps_browser_across_steps_and_reaps_entire_tree(browser):
    first = call(browser, "browser_navigate", {"url": "https://example.test/original"})
    clicked = call(browser, "browser_click", {"ref": "e1"})
    current = call(browser, "browser_snapshot")
    assert state(current)["url"] == "https://example.test/original"
    assert state(current)["clicks"] == 1
    assert first["session_id"] == clicked["session_id"] == current["session_id"]
    pid = state(current)["pid"]
    assert pid != os.getpid() and psutil.pid_exists(pid)
    scope = registry.mcp_session_scope(browser[1])
    assert workers.close_browser_worker_scope(scope) == 1
    assert not psutil.pid_exists(pid)
    assert call(browser, "browser_snapshot")["error_code"] == "mcp_session_lost"


def test_actual_executor_rechecks_revoked_host_session_between_steps(browser):
    from app.db.models.user import Session

    first = call(browser, "browser_navigate", {"url": "https://example.test"})
    assert state(first)["clicks"] == 0
    actor = browser[3]
    with actor.factory.begin() as db:
        db.delete(db.get(Session, actor.session_row_id))
    denied = call(browser, "browser_click", {"ref": "e1"})
    assert denied["success"] is False and denied["error_code"] == "tool_identity_required"
    assert "clicked" not in browser[2].read_text()


def test_actual_worker_timeout_reaps_delayed_side_effect_and_never_replays(browser):
    assert state(call(browser, "browser_snapshot"))["clicks"] == 0
    failed = call(browser, "browser_wait_for", {"text": "result"}, timeout=0.5)
    assert failed["success"] is False and failed["retryable"] is False
    assert failed["outcome"] == "unknown"
    assert call(browser, "browser_snapshot")["error_code"] == "mcp_session_lost"
    time.sleep(2.1)
    assert "late-write" not in browser[2].read_text()


def test_real_worker_keeps_captured_model_credentials_off_disk(browser, monkeypatch):
    from app.infrastructure.llm.client import llm_client_scope

    first = call(browser, "browser_snapshot")
    state(first)
    worker = next(iter(workers._WORKERS.values()))
    process = psutil.Process(worker.process.pid)
    sent = threading.Event()
    frames = []
    send = worker.commands.send_bytes
    secret = f"fixture-credential-{time.monotonic_ns()}"

    def observe_send(payload):
        frames.append(payload)
        sent.set()
        return send(payload)

    monkeypatch.setattr(worker.commands, "send_bytes", observe_send)
    process.suspend()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with llm_client_scope(
            SimpleNamespace(api_key=secret, base_url="https://fixture.invalid"), "fixture"
        ):
            future = executor.submit(copy_context().run, call, browser, "browser_snapshot")
        try:
            assert sent.wait(timeout=5)
            folder = Path(worker.folder)
            assert not (folder / "request").exists()
            assert all(
                secret.encode() not in path.read_bytes()
                for path in folder.rglob("*")
                if path.is_file()
            )
            assert json.loads(frames[0])["llm_scope"]["api_key"] == secret
        finally:
            if process.is_running():
                process.resume()
        result = future.result(timeout=10)
    assert result["session_id"] == first["session_id"] and state(result)["clicks"] == 0


def test_backpressured_request_deadline_reaps_worker_and_sender_thread(browser, monkeypatch):
    first = call(browser, "browser_snapshot")
    browser_pid = state(first)["pid"]
    worker = next(iter(workers._WORKERS.values()))
    worker_pid = worker.process.pid
    sender_threads = []
    send = worker.commands.send_bytes

    def observe_send(payload):
        assert 64 * 1024 < len(payload) <= workers._PAYLOAD_LIMIT
        sender_threads.append(threading.current_thread())
        return send(payload)

    monkeypatch.setattr(worker.commands, "send_bytes", observe_send)
    context = deepcopy(browser[1])
    context["fixture_padding"] = "x" * (2 * 1024 * 1024)
    psutil.Process(worker_pid).suspend()
    began = time.monotonic()
    result = call(browser, "browser_snapshot", context=context, timeout=0.5)
    assert time.monotonic() - began < 5
    assert result["success"] is False and result["retryable"] is False
    assert result["outcome"] == "unknown"
    assert sender_threads and all(not thread.is_alive() for thread in sender_threads)
    assert not psutil.pid_exists(worker_pid) and not psutil.pid_exists(browser_pid)
    assert not Path(worker.folder).exists()
    assert call(browser, "browser_snapshot")["error_code"] == "mcp_session_lost"


def test_large_request_and_oversize_rejection_keep_worker_usable(browser, monkeypatch):
    first = call(browser, "browser_snapshot")
    state(first)
    worker = next(iter(workers._WORKERS.values()))
    sends = []
    send = worker.commands.send_bytes

    def observe_send(payload):
        sends.append((len(payload), threading.current_thread()))
        return send(payload)

    monkeypatch.setattr(worker.commands, "send_bytes", observe_send)
    context = deepcopy(browser[1])
    context["fixture_padding"] = "x" * (2 * 1024 * 1024)
    result = call(browser, "browser_snapshot", context=context)
    assert result["session_id"] == first["session_id"] and state(result)["clicks"] == 0
    assert len(sends) == 1 and 2 * 1024 * 1024 < sends[0][0] <= workers._PAYLOAD_LIMIT
    assert not sends[0][1].is_alive()
    context["fixture_padding"] = "x" * workers._PAYLOAD_LIMIT
    rejected = call(browser, "browser_snapshot", context=context)
    assert rejected["error_code"] == "tool_context_not_serializable"
    assert rejected["outcome"] == "not_started" and len(sends) == 1
    current = call(browser, "browser_snapshot")
    assert current["session_id"] == first["session_id"] and state(current)["clicks"] == 0


def test_actor_binding_change_cannot_reuse_previous_browser_process(browser):
    first = call(browser, "browser_snapshot")
    assert state(first)["clicks"] == 0
    changed = deepcopy(browser[1])
    changed["_actor_authorization"]["proof"] = "changed"
    denied = call(browser, "browser_snapshot", context=changed)
    assert denied["error_code"] == "mcp_session_lost"
    assert not psutil.pid_exists(state(first)["pid"])


def test_parked_browser_rss_watchdog_reaps_before_next_action(browser):
    first = call(browser, "browser_snapshot")
    pid = state(first)["pid"]
    worker = next(iter(workers._WORKERS.values()))
    # Lower the physical watchdog budget after the real worker is parked.
    worker.memory_limit = 1
    deadline = time.monotonic() + 4
    while not worker.lost and time.monotonic() < deadline:
        time.sleep(0.02)
    assert worker.lost
    result = call(browser, "browser_snapshot")
    assert result["error_code"] == "tool_browser_memory_exceeded"
    assert not psutil.pid_exists(pid)


def test_browser_address_limit_does_not_change_regular_tool_limits(monkeypatch):
    import resource

    applied = {}
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (-1, -1))
    monkeypatch.setattr(resource, "setrlimit", lambda kind, pair: applied.update({kind: pair}))
    monkeypatch.delenv("XCAGI_TOOL_SANDBOX", raising=False)
    monkeypatch.delenv("XCAGI_BROWSER_ADDRESS_MB", raising=False)
    monkeypatch.delenv("XCAGI_TOOL_MEMORY_MB", raising=False)
    workers.boundary._apply_resource_limits(browser=True)
    assert applied[resource.RLIMIT_AS][0] == 1572864 * 1024 * 1024
    assert applied[resource.RLIMIT_CPU][0] == 60
    assert applied[resource.RLIMIT_NOFILE][0] == 256
    workers.boundary._apply_resource_limits()
    assert applied[resource.RLIMIT_AS][0] == 2048 * 1024 * 1024
