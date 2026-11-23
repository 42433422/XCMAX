"""Dynamic screen actions use real SQL approval and the original HTTP/screen hub.

The screen is synthetic. These tests do not claim deployed UI/customer acceptance.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.approval_grant import issue_approval_grant
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.aiopen import service
from app.domain.task_lifecycle.agent_runtime_contract import build_goal_contract
from app.infrastructure.auth.agent_mod_scope import bind_agent_actor_scope
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from app.infrastructure.codex.tools import CodexToolBridge
from tests.test_application.test_aiopen_agent_bridge import bridge as _screen_fixture
from tests.test_application.test_aiopen_agent_bridge import sessions as _sessions_fixture

screen_bridge = _screen_fixture
sessions = _sessions_fixture


@pytest.fixture
def dynamic_screen(screen_bridge, sessions, monkeypatch, tmp_path):
    screen = screen_bridge
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    context = {
        "user_id": "71",
        "actor_id": "71",
        "tenant_id": "7",
        "_actor_authorization": bind_agent_actor_scope(session_id="valid", user_id="71"),
    }
    parent = AgentRun("71", "在我的页面写入名称并核验", status="running")
    parent.metadata.update(runtime_type="codex", runtime_context=context)
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    screen.repository.save(parent)
    store = CodexBindingStore(screen.repository)
    grant = store.create(parent.run_id)

    def orchestrator(repository):
        return AgentOrchestrator(
            repository=repository,
            tool_executor=SimpleNamespace(execute=AgentToolExecutor().execute),
        )

    bridge = CodexToolBridge(store, orchestrator(screen.repository))
    page = {"value": "", "apply": True}

    async def receive(raw):
        message = json.loads(raw)
        screen.own.sent.append(message)
        action, params = message["action"], message["params"]
        assert "verification" not in params
        if action == "type" and page["apply"]:
            page["value"] = params["text"]
        result = {"success": True, "observed": action}
        if action == "verify":
            checks = [{"check": "元素存在", "ok": params.get("selector") == "#name"}]
            if "value" in params:
                checks.append({"check": "控件值", "ok": page["value"] == params["value"]})
            result = {"success": all(row["ok"] for row in checks), "checks": checks}
        service.aiopen_cursor_hub.handle_client_message(
            json.dumps({"id": message["id"], "result": result}), session_id="owned"
        )

    monkeypatch.setattr(screen.own, "send_text", receive)

    def invoke(action, params, call_id="screen-action"):
        spec = bridge.invoke(
            grant.mcp_token,
            "capability_describe",
            {
                "tool_id": "aiopen",
                "action": action,
            },
        )["capability"]
        return bridge.invoke(
            grant.mcp_token,
            "execute_action",
            {
                "tool_id": "aiopen",
                "action": action,
                "params": params,
                "schema_digest": spec["schema_digest"],
                "call_id": call_id,
            },
        )

    queue = SQLAlchemyTaskExecutionRepository(session_factory=sessions)

    def approve(receipt):
        child = screen.repository.get(receipt["run_id"])
        approval = issue_approval_grant(child, principal_id="71")
        approve_and_enqueue(
            screen.repository,
            queue,
            run_id=child.run_id,
            token=approval["grant"],
            principal_id="71",
            runtime_context=context,
            authenticated_actor_binding=context["_actor_authorization"],
        )
        claimed = queue.claim("screen-worker", lease_seconds=30)
        assert claimed is not None
        AgentTaskDispatcher(
            execution_repository=queue,
            run_repository=screen.repository,
            orchestrator_factory=orchestrator,
        )._execute_claim(claimed, "screen-worker")
        return screen.repository.get(child.run_id)

    return SimpleNamespace(
        screen=screen,
        bridge=bridge,
        store=store,
        grant=grant,
        invoke=invoke,
        approve=approve,
        page=page,
        parent=parent,
    )


def _type_params():
    return {
        "session_id": "owned",
        "selector": "#name",
        "text": "requested value",
        "verification": {"session_id": "owned", "selector": "#name", "value": "requested value"},
    }


def test_discovery_exposes_screen_actions_without_recursive_api_or_chat(dynamic_screen):
    state = dynamic_screen
    result = state.bridge.invoke(
        state.grant.mcp_token, "capability_search", {"query": "aiopen", "limit": 30}
    )
    actions = {row["action"] for row in result["capabilities"]}
    assert {"ui_snapshot", "ui_type", "ui_verify"} <= actions
    assert not actions.intersection({"chat", "api_call", "operation_call"})
    observation = state.invoke("ui_snapshot", {"session_id": "owned"}, "observe")
    assert observation["verified"] is True
    assert [row["action"] for row in state.screen.own.sent] == ["snapshot"]
    assert not state.screen.foreign.sent


@pytest.mark.parametrize("condition", [None, {}, {"session_id": "foreign", "text": "saved"}])
def test_write_without_same_session_frozen_condition_never_creates_task(dynamic_screen, condition):
    state = dynamic_screen
    params = _type_params()
    if condition is None:
        params.pop("verification")
    else:
        params["verification"] = condition
    result = state.invoke("ui_type", params)
    assert result["status"] == "not_started" and result["verified"] is False
    assert not state.store.get(state.parent.run_id).metadata["calls"]
    assert not state.screen.posts


@pytest.mark.parametrize("apply", [True, False])
def test_approved_single_action_independently_reads_the_original_screen(dynamic_screen, apply):
    state = dynamic_screen
    state.page["apply"] = apply
    pending = state.invoke("ui_type", _type_params())
    assert pending["pending_approval"] is True and not state.screen.posts
    original = state.screen.repository.get(pending["run_id"])
    assert len(original.steps) == 1
    assert original.steps[0].params == _type_params()
    done = state.approve(pending)
    assert [row["action"] for row in state.screen.own.sent] == ["type", "verify"]
    assert not state.screen.foreign.sent
    receipt = state.store.receipt_snapshot(state.parent.run_id)[0]["receipt"]
    if apply:
        assert done.status == "completed", done.error
        assert receipt["verified"] is True
        proof = receipt["verification"]["steps"][0]["checks"][0]["evidence"]
        assert proof["business_effect_verified"] is False
        assert proof["verification_scope"] == "visible_dom_assertions"
        replay = state.invoke("ui_type", _type_params(), "model-retry")
        assert replay["run_id"] == done.run_id and replay["verified"] is True
    else:
        assert done.status != "completed"
        assert receipt["verified"] is False and receipt["status"] == "unknown"
        with pytest.raises(CodexBindingError) as error:
            state.invoke("ui_type", _type_params(), "model-retry")
        assert error.value.code == "reconciliation_required"
    assert [row["action"] for row in state.screen.own.sent] == ["type", "verify"]


def test_model_cannot_change_a_pending_action_or_its_approved_condition(dynamic_screen):
    state = dynamic_screen
    pending = state.invoke("ui_type", _type_params())
    changed = _type_params()
    changed["verification"]["value"] = "different result"
    with pytest.raises(CodexBindingError) as error:
        state.invoke("ui_type", changed)
    assert error.value.code == "call_conflict"
    assert not state.screen.posts
    assert state.screen.repository.get(pending["run_id"]).steps[0].params == _type_params()
