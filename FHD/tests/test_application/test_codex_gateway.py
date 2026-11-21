"""Exercise real SQL request admission and authority with only runtime I/O replaced."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import gateway
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def setup_gateway(trusted_actor, tmp_path, monkeypatch):
    actor = trusted_actor()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    route = ModelRoute(
        base_url="http://127.0.0.1:19112/v1",
        model="test-fixture-model",
        provider_id="fixture",
        upstream_vendor="test-fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    qualification = tmp_path / "fixture-qualification.json"
    qualification.write_text(
        json.dumps(
            {
                "schema": "xcmax.runtime-qualification.v1",
                "route_identity": route.identity,
                "codex_version": CODEX_VERSION,
                "model_kind": "real",
                "evidence_refs": ["test-only-fixture"],
                "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
            }
        )
    )
    settings = RuntimeSettings(
        engine="codex",
        route=route,
        runtime_root=tmp_path / "runtime",
        qualification_file=qualification,
    )
    state = SimpleNamespace(
        actor=actor,
        repository=repository,
        settings=settings,
        calls=[],
        servers=[],
        next_status="waiting_user",
        entered=None,
        release=None,
        context={**actor.context, "turn_id": "request-one"},
    )

    class Server:
        url = "http://127.0.0.1:19113"

        def __init__(self, app):
            state.servers.append(app)

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    async def run(**kwargs):
        state.calls.append(kwargs)
        store, run_id = kwargs["binding_store"], kwargs["run_id"]
        grant = store.create(
            run_id,
            allowed_actions=kwargs["allowed_actions"],
            runtime_config=kwargs["runtime_config"],
        )
        store.record_thread(
            run_id, "thread-fixture", generation=grant.binding.metadata["generation"]
        )
        if state.entered is not None:
            state.entered.set()
            await state.release.wait()
        store.close(run_id, "waiting_user", generation=grant.binding.metadata["generation"])
        store.update(run_id, lambda parent, _metadata: setattr(parent, "status", state.next_status))
        if kwargs["on_event"]:
            kwargs["on_event"](
                {
                    "method": "fixture",
                    "payload": {"_actor_authorization": {"proof": "hidden"}, "text": "可见"},
                }
            )
        return {
            "handler": "agent",
            "runtime": "codex",
            "run_id": run_id,
            "ok": False,
            "business_completed": False,
            "verified_operations": False,
            "output": "等待补充",
            "execution_state": state.next_status,
            "exit_status": "waiting_user",
            "needs_user_input": True,
            "runtime_context": grant.binding.context,
            "nested": {
                "model_token": grant.model_token,
                "_codex_system_prompt": "hidden",
                "safe": "visible",
            },
        }

    monkeypatch.setattr(gateway, "get_agent_run_repository", lambda: repository)
    monkeypatch.setattr(gateway, "LocalRuntimeServer", Server)
    monkeypatch.setattr(gateway, "run_codex_agent", run)

    async def invoke(**kwargs):
        return await gateway.run_runtime_task_async(
            **{
                "task": "请解释库存含义",
                "system_prompt": "可信服务器员工说明",
                "runtime_context": state.context,
                "settings": state.settings,
                "completion_mode": "reply",
                **kwargs,
            }
        )

    state.invoke = invoke
    return state


def test_creates_independent_parent_with_private_resume_contract(setup_gateway):
    state = setup_gateway
    state.context.update(ai_cost_budget_units=120, expected_operations=[{"forged": True}])
    events = []
    result = asyncio.run(state.invoke(input_data={"file": "input.csv"}, on_event=events.append))
    parent = state.repository.get(result["run_id"])
    assert parent.intent == "codex.runtime" and parent.steps == []
    assert parent.metadata["runtime_expected_operations"] is None
    assert parent.metadata["_codex_system_prompt"] == "可信服务器员工说明"
    assert parent.metadata["_codex_input_data"] == {"file": "input.csv"}
    assert parent.metadata["ai_cost_budget_units"] == 120
    assert "expected_operations" not in parent.metadata["runtime_context"]
    assert (
        parent.metadata["runtime_context"]["_actor_authorization"]
        == state.actor.context["_actor_authorization"]
    )
    assert "runtime_context" not in result and result["nested"] == {"safe": "visible"}
    assert events == [{"method": "fixture", "payload": {"text": "可见"}}]
    config = state.calls[0]["config"]
    assert config.provider_url == "http://127.0.0.1:19113/api/agent-runtime/codex"
    assert config.mcp_url.endswith("/api/agent-runtime/codex/mcp")
    assert state.calls[0]["runtime_config"]["route_identity"] == state.settings.route.identity
    assert (
        str(state.servers[0].url_path_for("forward_responses"))
        == "/api/agent-runtime/codex/responses"
    )
    assert str(state.servers[0].url_path_for("codex_mcp")) == "/api/agent-runtime/codex/mcp"
    assert state.servers[0].state.codex_run_id == parent.run_id


def test_same_request_reuses_persisted_result_and_different_content_conflicts(setup_gateway):
    state = setup_gateway
    first = asyncio.run(state.invoke())
    duplicate = asyncio.run(state.invoke())
    assert duplicate["run_id"] == first["run_id"] and duplicate["deduplicated"] is True
    conflict = asyncio.run(state.invoke(task="改成新任务"))
    assert conflict["error_code"] == "request_conflict"
    assert len(state.calls) == 1


def test_concurrent_duplicate_cannot_start_another_turn(setup_gateway):
    state = setup_gateway

    async def scenario():
        state.entered, state.release = asyncio.Event(), asyncio.Event()
        first = asyncio.create_task(state.invoke())
        await state.entered.wait()
        duplicate = await state.invoke()
        state.release.set()
        return await first, duplicate

    first, duplicate = asyncio.run(scenario())
    assert duplicate["run_id"] == first["run_id"]
    assert duplicate["exit_status"] == "runtime_request_in_progress" and duplicate["deduplicated"]
    assert len(state.calls) == 1


def test_resume_retains_parent_and_deduplicates_new_answer(setup_gateway):
    state = setup_gateway
    first = asyncio.run(state.invoke(allowed_actions=["stock.query"]))
    context = {**state.context, "turn_id": "answer-two"}
    options = {
        "run_id": first["run_id"],
        "runtime_context": context,
        "answer_to_waiting_input": True,
        "task": "上个月",
    }
    resumed = asyncio.run(state.invoke(**options))
    duplicate = asyncio.run(state.invoke(**options))
    assert resumed["run_id"] == first["run_id"] == duplicate["run_id"]
    assert duplicate["deduplicated"] and len(state.calls) == 2
    assert state.calls[-1]["allowed_actions"] == ["stock.query"]
    assert state.calls[-1]["answer_to_waiting_input"] is True
    assert state.repository.get(first["run_id"]).metadata["_codex_input_data"] is None


@pytest.mark.parametrize(
    "change,code",
    [
        ({"system_prompt": "不同的服务器指令"}, "runtime_changed"),
        ({"completion_mode": "business"}, "runtime_changed"),
        ({"allowed_actions": ["stock.write"]}, "owner_changed"),
        (
            {"expected_operations": [{"tool_id": "stock", "action": "query", "params": {}}]},
            "request_conflict",
        ),
    ],
)
def test_resume_cannot_change_pinned_runtime_contract(setup_gateway, change, code):
    state = setup_gateway
    first = asyncio.run(state.invoke(allowed_actions=["stock.query"]))
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "answer-two"},
            **change,
        )
    )
    assert result["error_code"] == code and len(state.calls) == 1


def test_employee_gate_contract_cannot_disappear_on_resume(setup_gateway):
    state = setup_gateway
    gate = lambda *_args: {"ok": True}
    state.context.update(
        employee_id="stock-employee",
        _employee_gate_contract="original-hash",
        workspace_root="/workspace/employee",
    )
    first = asyncio.run(state.invoke(gate=gate))
    context = {**state.context, "turn_id": "answer-two"}
    result = asyncio.run(state.invoke(run_id=first["run_id"], runtime_context=context))
    assert result["error_code"] == "gate_required"
    context["_employee_gate_contract"] = "changed-hash"
    result = asyncio.run(state.invoke(run_id=first["run_id"], runtime_context=context, gate=gate))
    assert result["error_code"] == "owner_changed" and len(state.calls) == 1


def test_new_employee_parent_links_original_task_without_sharing_business_plan(setup_gateway):
    state = setup_gateway
    ancestor = AgentRun(user_id=str(state.actor.user_id), message="原业务计划")
    ancestor.metadata["runtime_context"] = copy.deepcopy(state.actor.context)
    state.repository.save(ancestor)
    state.context.update(
        parent_run_id=ancestor.run_id,
        employee_id="stock-employee",
        _employee_gate_contract="server-contract",
        workspace_root="/workspace/employee",
    )
    result = asyncio.run(state.invoke(gate=lambda *_args: {"ok": True}))
    parent = state.repository.get(result["run_id"])
    assert parent.steps == [] and "plan" not in parent.metadata
    assert parent.metadata["task_context"]["parent_run_id"] == ancestor.run_id
    assert parent.metadata["task_context"]["root_run_id"] == ancestor.run_id


def test_cleared_conversation_cannot_turn_repeated_request_into_new_run(setup_gateway):
    from app.db.models import AIConversationSession
    from app.domain.shared_services.conversation_service import lock_conversation_session

    state = setup_gateway
    with state.actor.factory.begin() as db:
        lock_conversation_session(
            db, session_id="chat-one", user_id=state.actor.user_id, create=True
        )
    state.context.update(
        conversation_id="chat-one", session_id="chat-one", _conversation_revision=0
    )
    first = asyncio.run(state.invoke())
    with state.actor.factory.begin() as db:
        db.query(AIConversationSession).filter_by(session_id="chat-one").update({"revision": 1})
    state.context["_conversation_revision"] = 1
    rejected = asyncio.run(state.invoke())
    assert rejected["run_id"] == first["run_id"] and rejected["error_code"] == "owner_changed"
    assert len(state.calls) == 1


def test_owner_or_authentication_cannot_be_borrowed_from_input(setup_gateway, trusted_actor):
    state = setup_gateway
    first = asyncio.run(state.invoke())
    other = trusted_actor()
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"], runtime_context={**other.context, "turn_id": "new-request"}
        )
    )
    assert result["error_code"] == "owner_changed"
    result = asyncio.run(
        state.invoke(runtime_context={"turn_id": "untrusted"}, input_data=state.context)
    )
    assert result["ok"] is False and len(state.calls) == 1


def test_unqualified_or_changed_route_never_starts_runtime(setup_gateway):
    state = setup_gateway
    rejected = asyncio.run(state.invoke(settings=replace(state.settings, qualification_file=None)))
    assert rejected["error_code"] == "runtime_policy_blocked" and state.calls == []
    first = asyncio.run(state.invoke())
    changed_route = replace(state.settings.route, model="other-model")
    receipt = json.loads(state.settings.qualification_file.read_text())
    receipt["route_identity"] = changed_route.identity
    state.settings.qualification_file.write_text(json.dumps(receipt))
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "answer-two"},
            settings=replace(state.settings, route=changed_route),
        )
    )
    assert result["error_code"] == "runtime_changed" and len(state.calls) == 1


def test_disabling_engine_preserves_original_run_pointer_without_replanning(setup_gateway):
    state = setup_gateway
    first = asyncio.run(state.invoke())
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "answer-two"},
            settings=RuntimeSettings(),
        )
    )
    assert result["run_id"] == first["run_id"] and result["exit_status"] == "runtime_not_selected"
    assert result["legacy_fallback_allowed"] is False and len(state.calls) == 1
    assert state.repository.get(first["run_id"]).status == "waiting_user"


def test_startup_failure_has_durable_blocked_parent_and_no_replay(setup_gateway, monkeypatch):
    state = setup_gateway

    def fail(_app):
        raise RuntimeError("private server failed with a secret")

    monkeypatch.setattr(gateway, "LocalRuntimeServer", fail)
    result = asyncio.run(state.invoke())
    assert result["error_code"] == "runtime_unavailable" and "secret" not in json.dumps(result)
    assert state.repository.get(result["run_id"]).status == "blocked"
    duplicate = asyncio.run(state.invoke())
    assert duplicate["deduplicated"] is True and state.calls == []


def test_sync_entry_preserves_request_inside_running_event_loop(setup_gateway):
    state = setup_gateway

    async def scenario():
        return gateway.run_runtime_task(
            task="解释库存",
            system_prompt="可信说明",
            runtime_context=state.context,
            settings=state.settings,
            completion_mode="reply",
        )

    result = asyncio.run(scenario())
    assert result["run_id"] and len(state.calls) == 1
