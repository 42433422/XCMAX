"""Opt-in Playwright MCP regression through the production isolated executor.

Install the locked runtime and Chromium, then set XCAGI_BROWSER_MCP_LIVE=1.
XCAGI_BROWSER_EXECUTABLE_PATH may select an explicitly provisioned Chromium.
Once opted in, missing dependencies fail instead of silently skipping the gate.
Only the fixture website and its login accounts are synthetic. Discovery, actor
authorization, approval grants, worker deadlines, browser IO and receipts are real.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.result_verification import verify_step_result
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_background import task_execution_context
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_spec import invalidate_tool_specs_cache
from app.application.tools.mcp import registry
from app.db.models.user import Session as UserSession
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from app.infrastructure.mcp.config import McpServerConfig
from app.utils.time import utc_now_naive
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("XCAGI_BROWSER_MCP_LIVE") != "1",
        reason="Set XCAGI_BROWSER_MCP_LIVE=1 after installing the pinned browser runtime",
    ),
]
_RUNTIME = Path(__file__).resolve().parents[2] / "scripts/autonomy/runtime_tools/browser_mcp_deps"
_FORM = """<!doctype html><html lang="en"><title>XCMAX browser fixture</title>
<h1>Browser task fixture</h1><form method="post" action="/submit">
<label for="reference">Fixture reference</label><input id="reference" name="reference" required>
<button type="submit">Submit fixture</button></form></html>"""


@pytest.fixture
def fixture_site():
    submissions: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def reply(self, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(404)
                return
            self.reply(_FORM)

        def do_POST(self) -> None:
            if self.path != "/submit":
                self.send_error(404)
                return
            payload = self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8")
            reference = parse_qs(payload).get("reference", [""])[0]
            submissions.append(reference)
            self.reply(f"<html><h1>Submitted: {html.escape(reference)}</h1></html>")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", submissions
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@dataclass
class LiveRuntime:
    config: McpServerConfig
    repository: SQLAlchemyAgentRunRepository
    run_ids: tuple[str, str]
    actor: object
    store: XiaoxBindingStore
    bridge: XiaoxToolBridge
    tokens: tuple[str, str]
    queue: SQLAlchemyTaskExecutionRepository
    receipts: dict[int, dict] = field(default_factory=dict)

    def context(self, run_index: int) -> dict:
        run = self.repository.get(self.run_ids[run_index])
        assert run is not None
        return {**run.metadata["runtime_context"], "run_id": run.run_id}

    def close(self, run_index: int) -> int:
        return registry.release_run_browser_sessions(self.context(run_index))


@pytest.fixture
def browser_runtime(tmp_path, monkeypatch, trusted_actor):
    node = shutil.which("node")
    entry = _RUNTIME / "node_modules/@playwright/mcp/cli.js"
    assert node and entry.is_file(), "Run npm ci in scripts/autonomy/runtime_tools/browser_mcp_deps"
    executable = os.environ.get("XCAGI_BROWSER_EXECUTABLE_PATH")
    if not executable:
        executable = subprocess.check_output(
            [node, "-e", "process.stdout.write(require('playwright').chromium.executablePath())"],
            cwd=_RUNTIME,
            text=True,
            timeout=10,
        )
    assert Path(executable).is_file(), (
        "Run npm run install:browser or set XCAGI_BROWSER_EXECUTABLE_PATH"
    )
    config = McpServerConfig(
        name=f"browser-live-{uuid.uuid4().hex}",
        command=node,
        args=(
            str(entry),
            "--headless",
            "--isolated",
            "--executable-path",
            executable,
            "--output-dir",
            str(tmp_path),
            "--timeout-action",
            "2000",
            "--timeout-navigation",
            "10000",
        ),
        timeout_seconds=30,
        read_only_tools=("browser_snapshot", "browser_wait_for"),
        session_mode="persistent",
        session_start_tools=("browser_navigate",),
        browser=True,
    )
    config_file = tmp_path / "mcp-servers.json"
    config_file.write_text(json.dumps({"servers": {config.name: asdict(config)}}), encoding="utf-8")
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "1")
    monkeypatch.setenv("XCAGI_MCP_SERVERS_FILE", str(config_file))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("XCAGI_TOOL_SANDBOX", "1")
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    registry.reset_mcp_cache_for_tests()
    invalidate_tool_specs_cache()
    tool = registry.tool_id_for(config.name)
    actor = trusted_actor(
        user_id=71,
        permissions=[
            f"tool.{tool}.{action}"
            for action in (
                "browser_navigate",
                "browser_snapshot",
                "browser_type",
                "browser_click",
                "browser_wait_for",
            )
        ],
    )
    context = {**actor.context, "employee_tool_allowlist": [tool]}
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(repository)
    runs = tuple(
        AgentRun(user_id="71", message="Submit and verify the controlled fixture", status="running")
        for _ in range(2)
    )
    for run in runs:
        run.metadata.update(runtime_type="xiaox", runtime_context=context)
        contract = build_goal_contract(run)
        run.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
        repository.save(run)
    store = XiaoxBindingStore(repository)
    runtime = LiveRuntime(
        config,
        repository,
        (runs[0].run_id, runs[1].run_id),
        actor,
        store,
        XiaoxToolBridge(store, AgentOrchestrator(repository=repository)),
        (store.create(runs[0].run_id).mcp_token, store.create(runs[1].run_id).mcp_token),
        SQLAlchemyTaskExecutionRepository(session_factory=actor.factory),
    )
    try:
        yield runtime
    finally:
        for index in range(2):
            runtime.close(index)
        registry.reset_mcp_cache_for_tests()
        invalidate_tool_specs_cache()
        set_agent_run_repository_for_tests(None)


def _dispatch(
    runtime: LiveRuntime,
    run_index: int,
    action: str,
    arguments: dict,
    *,
    assertion="",
    before_worker=None,
) -> dict:
    # The model choice is synthetic; discovery, durable single-action submission,
    # original SQL approval, dispatcher and the pinned MCP browser are real.
    tool_id = registry.tool_id_for(runtime.config.name)
    token = runtime.tokens[run_index]
    capability = runtime.bridge.invoke(
        token,
        "capability_describe",
        {
            "tool_id": tool_id,
            "action": action,
        },
    )["capability"]
    arguments = dict(arguments)
    if action == "browser_navigate":
        arguments["verification"] = {"kind": "url", "expected": arguments["url"]}
    elif not capability["read_only"]:
        assert assertion, "Every browser input must declare its visible postcondition"
        previous = runtime.store.receipt_snapshot(runtime.run_ids[run_index])[-1]
        assert previous["action"] == "browser_snapshot" and previous["receipt"]["verified"]
        arguments["verification"] = {
            "kind": "text",
            "expected": assertion,
            "observation_call_id": previous["call_id"],
        }
    receipt = runtime.bridge.invoke(
        token,
        "execute_action",
        {
            "tool_id": tool_id,
            "action": action,
            "params": arguments,
            "schema_digest": capability["schema_digest"],
            "call_id": f"action-{uuid.uuid4().hex}",
        },
    )
    if receipt.get("pending_approval"):
        child = runtime.repository.get(receipt["run_id"])
        assert child is not None
        grant = issue_approval_grant(child, principal_id=child.user_id)
        assert grant is not None
        approve_and_enqueue(
            runtime.repository,
            runtime.queue,
            run_id=child.run_id,
            token=grant["grant"],
            principal_id=child.user_id,
            runtime_context=runtime.actor.context,
            authenticated_actor_binding=runtime.actor.context["_actor_authorization"],
        )
        if before_worker is not None:
            before_worker()
        claimed = runtime.queue.claim("live-browser-worker", lease_seconds=60)
        assert claimed is not None
        AgentTaskDispatcher(
            execution_repository=runtime.queue, run_repository=runtime.repository
        )._execute_claim(claimed, "live-browser-worker")
        receipt = runtime.store.receipt_snapshot(runtime.run_ids[run_index])[-1]["receipt"]
    runtime.receipts[run_index] = receipt
    child = runtime.repository.get(receipt["run_id"])
    assert child is not None and len(child.steps) == 1
    assert child.steps[0].output == (
        child.tool_calls[-1].output if child.tool_calls else child.steps[0].output
    )
    return child.steps[0].output


def _call(runtime, run_index, tool, arguments, session_id=None, *, assertion=""):
    result = _dispatch(runtime, run_index, tool, arguments, assertion=assertion)
    if result.get("success") is not True:
        evidence = result.get("reconciliation_evidence") or result
        pytest.fail(
            f"{tool} failed through the production isolated executor: "
            f"{result.get('error_code')}, cause={evidence.get('error_code')}\n"
            f"{evidence.get('message') or evidence.get('content') or evidence}"
        )
    assert runtime.receipts[run_index]["verified"] is True, runtime.receipts[run_index]
    assert result.get("session_id")
    if session_id:
        assert result["session_id"] == session_id
    return result


def _target(snapshot: str, role: str, name: str) -> str:
    match = re.search(rf'{role} "{re.escape(name)}"[^\n]*\[ref=([^\]]+)\]', snapshot)
    assert match, snapshot
    return match.group(1)


def test_live_scopes_preserve_state_and_submit_once(browser_runtime, fixture_site):
    runtime = browser_runtime
    url, submissions = fixture_site
    first = _call(runtime, 0, "browser_navigate", {"url": url})
    session_a = first["session_id"]
    assert first["content_blocks"][0]["type"] == "text"
    snapshot = _call(runtime, 0, "browser_snapshot", {}, session_a)["content"]
    reference = f"XCMA-{uuid.uuid4().hex}"
    _call(
        runtime,
        0,
        "browser_type",
        {
            "target": _target(snapshot, "textbox", "Fixture reference"),
            "text": reference,
        },
        session_a,
        assertion=reference,
    )
    snapshot = _call(runtime, 0, "browser_snapshot", {}, session_a)["content"]
    assert reference in snapshot

    second = _call(runtime, 1, "browser_navigate", {"url": url})
    session_b = second["session_id"]
    assert session_a != session_b
    assert reference not in second["content"]
    _call(
        runtime,
        0,
        "browser_click",
        {
            "target": _target(snapshot, "button", "Submit fixture"),
        },
        session_a,
        assertion=f"Submitted: {reference}",
    )
    _call(runtime, 0, "browser_wait_for", {"text": f"Submitted: {reference}", "time": 2}, session_a)
    receipt = _call(runtime, 0, "browser_snapshot", {}, session_a)["content"]
    assert f"Submitted: {reference}" in receipt
    assert submissions == [reference]
    assert runtime.close(0) >= 1
    untouched = _call(runtime, 1, "browser_snapshot", {}, session_b)["content"]
    assert "Fixture reference" in untouched and reference not in untouched


def test_live_missing_evidence_and_lost_generation_fail_closed(browser_runtime, fixture_site):
    runtime = browser_runtime
    url, submissions = fixture_site
    session_id = _call(runtime, 0, "browser_navigate", {"url": url})["session_id"]
    missing = _dispatch(
        runtime,
        0,
        "browser_wait_for",
        {"text": "Receipt that does not exist", "time": 0.1},
    )
    assert missing["success"] is False and missing["error_code"] == "mcp_tool_error"
    assert missing["session_id"] == session_id
    assert runtime.close(0) >= 1
    # A new action must not silently recreate the lost original generation.
    resumed = _dispatch(runtime, 0, "browser_navigate", {"url": url + "#resume"})
    assert resumed["success"] is False and resumed["error_code"] == "mcp_session_lost"
    assert resumed["session_id"] == session_id
    assert resumed["outcome"] == "unknown"
    assert "reconciliation_evidence" not in resumed
    assert resumed["reconciliation_required"] is True
    assert resumed["retryable"] is False
    assert submissions == []


def test_live_worker_rechecks_revoked_actor_before_next_browser_action(
    browser_runtime, fixture_site
):
    runtime = browser_runtime
    url, submissions = fixture_site
    session_id = _call(runtime, 0, "browser_navigate", {"url": url})["session_id"]
    snapshot = _call(runtime, 0, "browser_snapshot", {}, session_id)["content"]
    _call(
        runtime,
        0,
        "browser_type",
        {"target": _target(snapshot, "textbox", "Fixture reference"), "text": "REVOKED"},
        session_id,
        assertion="REVOKED",
    )
    snapshot = _call(runtime, 0, "browser_snapshot", {}, session_id)["content"]
    assert "REVOKED" in snapshot

    def revoke_after_approval():
        with runtime.actor.factory.begin() as db:
            session = db.get(UserSession, runtime.actor.session_row_id)
            assert session is not None
            session.expires_at = utc_now_naive() - timedelta(seconds=1)

    denied = _dispatch(
        runtime,
        0,
        "browser_click",
        {
            "target": _target(snapshot, "button", "Submit fixture"),
        },
        assertion="Submitted: REVOKED",
        before_worker=revoke_after_approval,
    )
    assert denied.get("success") is not True and runtime.receipts[0]["verified"] is False
    child = runtime.repository.get(runtime.receipts[0]["run_id"])
    assert child is not None and child.status != "completed"
    assert not any(call.output.get("success") for call in child.tool_calls)
    assert submissions == []


def test_live_host_verifier_reads_original_worker_without_resubmitting(
    browser_runtime, fixture_site
):
    runtime = browser_runtime
    url, submissions = fixture_site
    _call(runtime, 0, "browser_navigate", {"url": url})
    snapshot = _call(runtime, 0, "browser_snapshot", {})["content"]
    reference = f"VERIFY-{uuid.uuid4().hex}"
    _call(
        runtime,
        0,
        "browser_type",
        {"target": _target(snapshot, "textbox", "Fixture reference"), "text": reference},
        assertion=reference,
    )
    snapshot = _call(runtime, 0, "browser_snapshot", {})["content"]
    _call(
        runtime,
        0,
        "browser_click",
        {"target": _target(snapshot, "button", "Submit fixture")},
        assertion=f"Submitted: {reference}",
    )
    run = runtime.repository.get(runtime.receipts[0]["run_id"])
    assert run is not None
    step, call = run.steps[-1], run.tool_calls[-1]
    context = {
        **run.metadata["runtime_context"],
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
        "call_id": call.call_id,
        "input_sha256": call.metadata["verification_contract"]["input_sha256"],
        **task_execution_context(run, step),
    }
    for _ in range(2):
        report = verify_step_result(run=run, step=step, call=call, context=context)
        assert report["accepted"] is True, report
        assert report["checks"][0]["evidence"]["business_effect_verified"] is False
    assert submissions == [reference]
    assert runtime.close(0) >= 1
    report = verify_step_result(run=run, step=step, call=call, context=context)
    assert report["status"] == "inconclusive"
    assert call.output["success"] is True and submissions == [reference]
