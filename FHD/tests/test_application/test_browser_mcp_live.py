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
from dataclasses import asdict, dataclass
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from app.application.agent_orchestrator.approval_grant import (
    consume_approval_grant,
    issue_approval_grant,
)
from app.application.agent_orchestrator.result_verification import (
    bind_execution_receipt,
    freeze_verification_contract,
    verify_step_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_background import (
    apply_approved_step,
    task_execution_context,
)
from app.application.agent_orchestrator.tool_executor import (
    AgentToolExecutor,
    execute_with_tool_deadline,
)
from app.application.agent_orchestrator.tool_spec import (
    get_tool_action_spec,
    invalidate_tool_specs_cache,
)
from app.application.tools.mcp import registry
from app.db import HostSessionLocal, get_host_engine
from app.db.db_base import Base
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
from app.infrastructure.mcp.config import McpServerConfig
from app.utils.time import utc_now_naive

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
    actor_session_row_id: int

    def context(self, run_index: int) -> dict:
        run = self.repository.get(self.run_ids[run_index])
        assert run is not None
        return {**run.metadata["runtime_context"], "run_id": run.run_id}

    def close(self, run_index: int) -> int:
        return registry.release_run_browser_sessions(self.context(run_index))


@pytest.fixture
def browser_runtime(tmp_path, monkeypatch):
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
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'host.sqlite'}")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "idempotency.sqlite"))
    monkeypatch.setenv("XCAGI_TOOL_SANDBOX", "1")
    monkeypatch.setenv("XCAGI_AGENT_TOOL_HARD_TIMEOUT_REQUIRED", "1")
    registry.reset_mcp_cache_for_tests()
    invalidate_tool_specs_cache()
    engine = get_host_engine()
    Base.metadata.create_all(engine)
    session_token = uuid.uuid4().hex
    with HostSessionLocal() as db:
        db.add(
            User(
                id=71,
                username="browser-fixture-actor",
                password="unused",
                role="admin",
                tenant_id=7,
            )
        )
        db.flush()
        row = UserSession(
            session_id=session_token,
            user_id=71,
            expires_at=utc_now_naive() + timedelta(hours=1),
        )
        db.add(row)
        db.flush()
        session_row_id = row.id
        db.commit()
    context = {
        "tenant_id": "7",
        "user_id": "71",
        "actor_id": "71",
        "_actor_authorization": bind_agent_actor_scope(session_id=session_token, user_id="71"),
        "employee_tool_allowlist": [registry.tool_id_for(config.name)],
    }
    repository = SQLAlchemyAgentRunRepository(session_factory=HostSessionLocal)
    runs = tuple(
        AgentRun(user_id="71", message="Submit and verify the controlled fixture", status="running")
        for _ in range(2)
    )
    for run in runs:
        run.metadata["runtime_context"] = context
        repository.save(run)
    runtime = LiveRuntime(config, repository, (runs[0].run_id, runs[1].run_id), session_row_id)
    try:
        yield runtime
    finally:
        for index in range(2):
            runtime.close(index)
        registry.reset_mcp_cache_for_tests()
        invalidate_tool_specs_cache()
        engine.dispose()


def _dispatch(
    runtime: LiveRuntime,
    run_index: int,
    action: str,
    arguments: dict,
    *,
    verify=False,
    assertion="",
) -> dict:
    # Reopen the persisted run for every step; do not pass a browser/client handle
    # between calls or replace the production facade, authorization or worker.
    run = runtime.repository.get(runtime.run_ids[run_index])
    assert run is not None
    tool_id = registry.tool_id_for(runtime.config.name)
    spec = get_tool_action_spec(tool_id, action)
    assert spec is not None, f"Official MCP tool discovery did not register {action}"
    step = AgentStep(
        node_id=f"browser_{len(run.steps) + 1}",
        tool_id=tool_id,
        action=action,
        params=arguments,
        risk=spec.risk,
        idempotent=spec.idempotent,
    )
    run.steps.append(step)
    if spec.risk == "high":
        # Fixture authorization is action-bound and durably consumed, using the
        # same server issuance functions as the approved AgentRun continuation.
        run.status, step.status = "waiting_user", "waiting_user"
        runtime.repository.save(run)
        grant = issue_approval_grant(run, principal_id=run.user_id)
        assert grant is not None
        consume_approval_grant(grant["grant"], run=run, principal_id=run.user_id)
        apply_approved_step(run, step, approved_by=run.user_id)
    run.status, step.status = "running", "running"
    context = {
        **run.metadata["runtime_context"],
        "run_id": run.run_id,
        "step_id": step.step_id,
        "node_id": step.node_id,
        "node_outputs": {prior.node_id: prior.output for prior in run.steps if prior.output},
        **task_execution_context(run, step),
    }
    call = None
    if verify:
        if assertion:
            before = next(
                item
                for item in reversed(run.steps)
                if item.action == "browser_snapshot" and item.status == "completed"
            )
            run.metadata.setdefault("browser_loop", {}).setdefault("postconditions", {})[
                step.node_id
            ] = {
                "kind": "text",
                "expected": assertion,
                "before_snapshot_node_id": before.node_id,
            }
        call = ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=tool_id,
            action=action,
            params=arguments,
            metadata={"idempotency_key": context["idempotency_key"]},
        )
        run.tool_calls.append(call)
        freeze_verification_contract(run, step, call, spec, context)
    runtime.repository.save(run)
    result = execute_with_tool_deadline(
        AgentToolExecutor(),
        step,
        runtime_context=context,
        timeout_seconds=30,
    )
    step.output = result
    step.status = "completed" if result.get("success") is True else "failed"
    if call is not None:
        call.output = result
        bind_execution_receipt(call)
    runtime.repository.save(run)
    if call is not None:
        report = verify_step_result(run=run, step=step, call=call, context=context)
        assert report["accepted"] is True, report
        runtime.repository.save(run)
    stored = runtime.repository.get(run.run_id)
    assert stored is not None and stored.steps[-1].output == result
    return stored.steps[-1].output


def _call(runtime, run_index, tool, arguments, session_id=None):
    result = _dispatch(runtime, run_index, tool, arguments)
    if result.get("success") is not True:
        evidence = result.get("reconciliation_evidence") or result
        pytest.fail(
            f"{tool} failed through the production isolated executor: "
            f"{result.get('error_code')}, cause={evidence.get('error_code')}\n"
            f"{evidence.get('message') or evidence.get('content') or evidence}"
        )
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
    resumed = _dispatch(runtime, 0, "browser_navigate", {"url": url})
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
    )
    snapshot = _call(runtime, 0, "browser_snapshot", {}, session_id)["content"]
    assert "REVOKED" in snapshot
    with HostSessionLocal() as db:
        session = db.get(UserSession, runtime.actor_session_row_id)
        assert session is not None
        session.expires_at = utc_now_naive() - timedelta(seconds=1)
        db.commit()
    denied = _dispatch(
        runtime,
        0,
        "browser_click",
        {
            "target": _target(snapshot, "button", "Submit fixture"),
        },
    )
    assert denied["success"] is False and denied["error_code"] == "tool_identity_required"
    assert submissions == []


def test_live_host_verifier_reads_original_worker_without_resubmitting(
    browser_runtime, fixture_site
):
    runtime = browser_runtime
    url, submissions = fixture_site
    _dispatch(runtime, 0, "browser_navigate", {"url": url}, verify=True)
    snapshot = _call(runtime, 0, "browser_snapshot", {})["content"]
    reference = f"VERIFY-{uuid.uuid4().hex}"
    _dispatch(
        runtime,
        0,
        "browser_type",
        {"target": _target(snapshot, "textbox", "Fixture reference"), "text": reference},
        verify=True,
        assertion=reference,
    )
    snapshot = _call(runtime, 0, "browser_snapshot", {})["content"]
    _dispatch(
        runtime,
        0,
        "browser_click",
        {"target": _target(snapshot, "button", "Submit fixture")},
        verify=True,
        assertion=f"Submitted: {reference}",
    )
    run = runtime.repository.get(runtime.run_ids[0])
    step, call = run.steps[-1], run.tool_calls[-1]
    context = {
        **run.metadata["runtime_context"],
        "run_id": run.run_id,
        "step_id": step.step_id,
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
