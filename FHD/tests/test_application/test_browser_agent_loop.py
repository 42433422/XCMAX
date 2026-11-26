"""Xiaox-selected browser actions keep SQL approval and original page receipts.

The page/transport is synthetic. No second model loop or deployed UI is claimed.
"""

from __future__ import annotations

import copy
import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_orchestrator.tool_spec import invalidate_tool_specs_cache
from app.application.tools.mcp import registry
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.mcp.client import McpToolInfo
from app.infrastructure.mcp.config import McpServerConfig
from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

GOAL = "使用浏览器点击保存，确认页面显示保存成功 #42"
TOOL = "mcp__browser_test"


@pytest.fixture
def harness(monkeypatch, tmp_path, trusted_actor):
    config = McpServerConfig(
        name="browser_test",
        command="controlled",
        browser=True,
        session_mode="persistent",
        session_start_tools=("browser_navigate", "browser_snapshot"),
        read_only_tools=("browser_snapshot", "browser_wait_for"),
    )
    infos = [
        McpToolInfo(
            "browser_snapshot",
            "Observe actual page",
            {"type": "object", "additionalProperties": False},
            True,
        ),
        McpToolInfo(
            "browser_click",
            "Click observed ref",
            {
                "type": "object",
                "properties": {"ref": {"type": "string"}},
                "required": ["ref"],
                "additionalProperties": False,
            },
            False,
        ),
        McpToolInfo(
            "browser_navigate",
            "Navigate URL",
            {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
            False,
        ),
    ]
    actions = {info.name: registry._action_spec(info, config) for info in infos}
    monkeypatch.setenv("XCAGI_MCP_ENABLED", "1")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setattr(
        registry, "_snapshot", lambda *a, **kw: ({TOOL: {"actions": actions}}, {TOOL: config})
    )
    invalidate_tool_specs_cache()
    actor = trusted_actor(permissions=[f"tool.{TOOL}.{action}" for action in actions])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    set_agent_run_repository_for_tests(repository)
    parent = AgentRun(str(actor.user_id), GOAL, status="running")
    parent.metadata.update(runtime_type="xiaox", runtime_context=actor.context)
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(parent)
    store = XiaoxBindingStore(repository)
    grant = store.create(parent.run_id)
    page = {
        "saved": False,
        "apply": True,
        "ref": "e1",
        "session": "generation-1",
        "url": "https://example.test/",
        "echo": False,
    }
    calls, probes = [], []

    def read_page():
        snapshot = f'- button "保存" [ref={page["ref"]}]\n- generic: 首页'
        if page["saved"]:
            snapshot += "\n- generic: 保存成功 #42"
        content = f"### Page\n- Page URL: {page['url']}\n### Snapshot\n```yaml\n{snapshot}\n```"
        if page["echo"]:
            content = '### Ran Playwright code\n```js\nawait page.getByText("保存成功 #42")\n```\n### Snapshot\n```yaml\n- generic: 首页\n```'
        return {
            "success": True,
            "content": content,
            "server": config.name,
            "session_id": page["session"],
            "observed_at": time.time(),
        }

    def call_tool(actual_config, action, params, **options):
        assert actual_config == config and "verification" not in params
        calls.append((action, copy.deepcopy(params), dict(options)))
        if options.get("expected_session_id", page["session"]) != page["session"]:
            return {
                "success": False,
                "outcome": "unknown",
                "error_code": "mcp_session_lost",
                "retryable": False,
            }
        if action == "browser_snapshot":
            return read_page()
        if action == "browser_click" and page["apply"]:
            page["saved"] = True
        if action == "browser_navigate":
            page["url"] = params["url"]
        return {
            "success": True,
            "content": "action acknowledged",
            "server": config.name,
            "session_id": page["session"],
        }

    def readback(run, step, call, context, actual_config):
        assert actual_config == config
        assert registry.mcp_session_scope(context) == registry.mcp_session_scope(
            {**actor.context, "run_id": parent.run_id}
        )
        probes.append((run.run_id, call.call_id, call.output.get("session_id")))
        return read_page()

    monkeypatch.setattr(registry, "call_tool", call_tool)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.browser_tool_process.read_browser_snapshot", readback
    )

    def orchestrator(repo):
        return AgentOrchestrator(
            repository=repo, tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute)
        )

    bridge = XiaoxToolBridge(store, orchestrator(repository))
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)

    def invoke(action, params=None, call_id="observe"):
        capability = bridge.invoke(
            grant.mcp_token, "capability_describe", {"tool_id": TOOL, "action": action}
        )["capability"]
        return bridge.invoke(
            grant.mcp_token,
            "execute_action",
            {
                "tool_id": TOOL,
                "action": action,
                "params": params or {},
                "call_id": call_id,
                "schema_digest": capability["schema_digest"],
            },
        )

    def approve(receipt):
        child = repository.get(receipt["run_id"])
        approval = issue_approval_grant(child, principal_id=str(actor.user_id))
        approve_and_enqueue(
            repository,
            queue,
            run_id=child.run_id,
            token=approval["grant"],
            principal_id=str(actor.user_id),
            runtime_context=actor.context,
            authenticated_actor_binding=actor.context["_actor_authorization"],
        )
        claimed = queue.claim("browser-worker", lease_seconds=30)
        assert claimed is not None
        AgentTaskDispatcher(
            execution_repository=queue, run_repository=repository, orchestrator_factory=orchestrator
        )._execute_claim(claimed, "browser-worker")
        return repository.get(child.run_id)

    try:
        yield SimpleNamespace(
            actor=actor,
            parent=parent,
            repo=repository,
            store=store,
            grant=grant,
            bridge=bridge,
            invoke=invoke,
            approve=approve,
            page=page,
            calls=calls,
            probes=probes,
            config=config,
        )
    finally:
        set_agent_run_repository_for_tests(None)
        invalidate_tool_specs_cache()


def click_params(observation="observe"):
    return {
        "ref": "e1",
        "verification": {
            "kind": "text",
            "expected": "保存成功 #42",
            "observation_call_id": observation,
        },
    }


def test_dynamic_browser_uses_exact_schema_original_approval_and_independent_page_read(harness):
    h = harness
    observed = h.invoke("browser_snapshot")
    assert observed["verified"] is True
    pending = h.invoke("browser_click", click_params(), "click")
    assert pending["pending_approval"] is True
    assert [call[0] for call in h.calls] == ["browser_snapshot"]
    child = h.approve(pending)
    receipt = h.store.receipt_snapshot(h.parent.run_id)[-1]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, (child.error, receipt)
    assert [call[0] for call in h.calls] == ["browser_snapshot", "browser_click"]
    assert len(h.probes) == 2 and h.probes[0][0] == observed["run_id"]
    assert h.probes[1][0] == child.run_id and h.calls[1][1] == {"ref": "e1"}
    assert h.calls[0][2]["session_scope"] == h.calls[1][2]["session_scope"]
    assert h.calls[1][2]["expected_session_id"] == "generation-1"
    proof = receipt["verification"]["steps"][0]["checks"][0]["evidence"]
    assert proof["business_effect_verified"] is False
    assert proof["verification_scope"] == "visible_page_assertion"
    replay = h.invoke("browser_click", click_params(), "retry")
    assert replay["run_id"] == child.run_id and len(h.calls) == 2
    assert all(not run.llm_calls for run in h.repo.list_recent())


@pytest.mark.parametrize(
    "condition", [None, {}, {"kind": "text", "expected": ""}, {"kind": "text", "expected": "saved"}]
)
def test_missing_or_incomplete_postcondition_never_publishes_input(harness, condition):
    params = {"ref": "e1"}
    if condition is not None:
        params["verification"] = condition
    receipt = harness.invoke("browser_click", params, "click")
    assert receipt["status"] == "not_started"
    assert not harness.calls and harness.store.get(harness.parent.run_id).metadata["calls"] == {}


@pytest.mark.parametrize(
    "change", ["preexisting", "stale_ref", "wrong_observation", "newer_observation", "generation"]
)
def test_write_fails_closed_when_original_page_evidence_no_longer_applies(harness, change):
    h = harness
    h.invoke("browser_snapshot")
    params = click_params()
    if change == "preexisting":
        h.page["saved"] = True
    if change == "stale_ref":
        h.page["ref"] = "e2"
    if change == "generation":
        h.page["session"] = "generation-2"
    if change == "wrong_observation":
        params["verification"]["observation_call_id"] = "foreign-call"
    if change == "newer_observation":
        h.invoke("browser_snapshot", {}, "latest-observation")
    pending = h.invoke("browser_click", params, "click")
    child = h.approve(pending)
    assert child.status != "completed"
    assert all(call[0] == "browser_snapshot" for call in h.calls)
    assert not any(call.output.get("success") is True for call in child.tool_calls)


@pytest.mark.parametrize("echo", [False, True])
def test_acknowledgement_or_echoed_code_never_proves_input_and_never_replays(
    harness, echo, monkeypatch
):
    h = harness
    h.invoke("browser_snapshot")
    pending = h.invoke("browser_click", click_params(), "click")
    h.page["apply"] = False
    original = registry.call_tool

    def echoed(*args, **kwargs):
        result = original(*args, **kwargs)
        h.page["echo"] = echo
        return result

    monkeypatch.setattr(registry, "call_tool", echoed)
    child = h.approve(pending)
    receipt = h.store.receipt_snapshot(h.parent.run_id)[-1]["receipt"]
    assert child.status != "completed" and receipt["status"] == "unknown"
    assert receipt["reconciliation_required"] is True
    with pytest.raises(XiaoxBindingError) as error:
        h.invoke("browser_click", click_params(), "retry")
    assert error.value.code == "reconciliation_required"
    assert [call[0] for call in h.calls] == ["browser_snapshot", "browser_click"]


def test_changed_pending_action_cannot_reuse_approval(harness):
    h = harness
    h.invoke("browser_snapshot")
    pending = h.invoke("browser_click", click_params(), "click")
    changed = click_params()
    changed["ref"] = "e2"
    with pytest.raises(XiaoxBindingError) as error:
        h.invoke("browser_click", changed, "click")
    assert error.value.code == "call_conflict"
    assert h.repo.get(pending["run_id"]).steps[0].params == click_params()
    assert len(h.calls) == 1


def test_revoked_original_owner_cannot_continue_input(harness):
    from app.db.models.user import Session

    h = harness
    h.invoke("browser_snapshot")
    with h.actor.factory.begin() as db:
        db.delete(db.get(Session, h.actor.session_row_id))
    with pytest.raises(XiaoxBindingError):
        h.invoke("browser_click", click_params(), "click")
    assert len(h.calls) == 1


def test_only_original_parent_releases_its_browser_session(harness, monkeypatch):
    h = harness
    observed = h.invoke("browser_snapshot")
    child = h.repo.get(observed["run_id"])
    context = {**child.metadata["runtime_context"], "run_id": child.run_id}
    parent_context = {**h.actor.context, "run_id": h.parent.run_id}
    scope = registry.mcp_session_scope(parent_context)
    assert registry.mcp_session_scope(context) == scope
    closed = []
    monkeypatch.setattr(
        "app.application.agent_orchestrator.browser_tool_process.close_browser_worker_scope",
        lambda value: closed.append(value) or 1,
    )
    monkeypatch.setattr("app.infrastructure.mcp.client.close_scope", lambda value: 0)
    assert registry.release_run_browser_sessions(context) == 0 and not closed
    assert registry.release_run_browser_sessions(parent_context) == 1 and closed == [scope]
    assert registry.mcp_session_scope({**context, "parent_run_id": "foreign-parent"}) == ""


@pytest.mark.parametrize(
    ("status", "failure", "close_fails"),
    [
        ("completed", "save", False),
        ("cancelled", "save", False),
        ("failed", "save", False),
        ("rejected", "save", False),
        ("completed", "save", True),
        ("completed", "", True),
        ("failed", "execute", True),
    ],
)
def test_terminal_browser_cleanup_survives_receipt_save_failure(
    harness, monkeypatch, status, failure, close_fails
):
    h = harness
    service = AgentOrchestrator(repository=h.repo)
    save, closed = h.repo.save, []
    primary_error, cleanup_error = OSError("original failure"), RuntimeError("close")

    def save_run(run):
        if failure == "save" and (run.metadata.get("execution") or {}).get("state") == "idle":
            raise primary_error
        return save(run)

    def finish_run(run, **kwargs):
        run.status = status
        if failure == "execute":
            raise primary_error

    def close_scope(scope):
        closed.append(scope)
        if close_fails:
            raise cleanup_error
        return 1

    monkeypatch.setattr(h.repo, "save", save_run)
    monkeypatch.setattr(service, "_execute_ready_steps", finish_run)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.browser_tool_process.close_browser_worker_scope",
        close_scope,
    )
    monkeypatch.setattr("app.infrastructure.mcp.client.close_scope", lambda scope: 0)
    try:
        raise LookupError("already handled by the caller")
    except LookupError:
        with pytest.raises(OSError if failure else RuntimeError) as error:
            service._execute_with_durable_lease(h.parent, runtime_context=h.actor.context)
    assert error.value is (primary_error if failure else cleanup_error)
    assert closed == [registry.mcp_session_scope({**h.actor.context, "run_id": h.parent.run_id})]
    stored = h.repo.get(h.parent.run_id)
    assert stored.status == ("running" if failure == "save" else status)
    assert stored.metadata["execution"]["state"] == ("active" if failure == "save" else "idle")
    assert h.calls == []


def test_navigation_verifies_the_exact_requested_page_header(harness):
    h = harness
    params = {
        "url": "https://example.test/target",
        "verification": {"kind": "url", "expected": "https://example.test/target"},
    }
    pending = h.invoke("browser_navigate", params, "navigate")
    child = h.approve(pending)
    receipt = h.store.receipt_snapshot(h.parent.run_id)[-1]["receipt"]
    assert child.status == "completed" and receipt["verified"] is True, (child.error, receipt)
    assert len(h.probes) == 1 and h.calls[0][1] == {"url": params["url"]}
