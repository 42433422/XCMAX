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
        waiting_question=None,
        compiled_plan=None,
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
        if state.compiled_plan:
            from app.domain.task_lifecycle.agent_runtime_contract import (
                frozen_goal_digest,
                frozen_workflow_operation,
            )

            def compile_goal(parent, metadata):
                expected = [frozen_workflow_operation(state.compiled_plan)]
                digest = frozen_goal_digest(expected, state.compiled_plan)
                parent.metadata.update(
                    runtime_expected_operations=expected,
                    runtime_frozen_plan=copy.deepcopy(state.compiled_plan),
                    runtime_goal_digest=digest,
                )
                metadata["goal_digest"] = digest

            store.update(run_id, compile_goal)
        store.record_thread(
            run_id, "thread-fixture", generation=grant.binding.metadata["generation"]
        )
        if kwargs["answer_to_waiting_input"]:
            store.update(run_id, lambda _run, metadata: metadata.pop("waiting_input", None))
        elif state.waiting_question:
            store.update(
                run_id,
                lambda _run, metadata: metadata.update(
                    waiting_input={"question": state.waiting_question}
                ),
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


def test_staging_persists_paused_parent_without_grant_server_or_execution(setup_gateway):
    from app.infrastructure.codex.binding import CodexBindingStore

    state = setup_gateway
    options = {"start_paused": True, "completion_mode": "auto", "admit_goal": True}
    staged = asyncio.run(state.invoke(**options))
    duplicate = asyncio.run(state.invoke(**options))
    assert staged["execution_state"] == "paused" and staged["resume_required"] is True
    assert duplicate["deduplicated"] is True and duplicate["run_id"] == staged["run_id"]
    assert state.calls == [] and state.servers == []
    store = CodexBindingStore(state.repository)
    binding = store.get(staged["run_id"])
    assert binding.run.status == "paused" and binding.run.intent == "codex.runtime"
    assert binding.metadata["generation"] == 0 and binding.metadata["revoked"] is True
    assert binding.metadata["token_hashes"] == binding.metadata["calls"] == {}
    assert binding.run.metadata["runtime_goal_admission"] is True
    assert binding.run.final_output["codex_result"]["resume_required"] is True

    # The authenticated control route performs this state transition before
    # resuming the original parent; only that later invocation obtains a grant.
    command = state.repository.request_task_control(
        binding.run_id, "resume", requested_by=binding.run.user_id
    )
    state.repository.mark_task_control(command.command_id, "applied")
    store.update(binding.run_id, lambda parent, _meta: setattr(parent, "status", "running"))
    result = asyncio.run(
        state.invoke(
            run_id=binding.run_id,
            runtime_context={**state.context, "turn_id": "staged-resume"},
            completion_mode="auto",
            admit_goal=True,
        )
    )
    assert result["run_id"] == staged["run_id"] and len(state.calls) == 1
    assert store.get(binding.run_id).metadata["generation"] == 1


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


def frozen_plan(keyword="fixture"):
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

    return plan_to_dict(
        PlanGraph(
            plan_id="host-frozen-plan",
            intent="products.query",
            nodes=[
                WorkflowNode(
                    node_id="query",
                    tool_id="products",
                    action="query",
                    params={"keyword": keyword},
                )
            ],
        )
    )


def test_frozen_host_plan_is_bound_to_request_and_isolated_from_context_injection(setup_gateway):
    from app.domain.task_lifecycle.agent_runtime_contract import (
        frozen_goal_digest,
        frozen_workflow_operation,
    )

    state = setup_gateway
    plan = frozen_plan()
    state.context.update(frozen_plan=frozen_plan("forged"), runtime_goal_digest="forged")
    result = asyncio.run(state.invoke(frozen_plan=plan, completion_mode="business"))
    parent = state.repository.get(result["run_id"])
    expected = [frozen_workflow_operation(plan)]
    assert parent.metadata["runtime_expected_operations"] == expected
    assert parent.metadata["runtime_frozen_plan"] == plan
    assert parent.metadata["runtime_goal_digest"] == frozen_goal_digest(expected, plan)
    assert parent.metadata["codex_runtime"]["goal_digest"] == parent.metadata["runtime_goal_digest"]
    assert "frozen_plan" not in parent.metadata["runtime_context"]
    assert "runtime_goal_digest" not in parent.metadata["runtime_context"]
    assert "execute_plan" in state.calls[0]["system_prompt"]
    assert expected[0]["params"]["plan_digest"] in state.calls[0]["system_prompt"]
    changed = asyncio.run(
        state.invoke(
            run_id=parent.run_id,
            runtime_context={**state.context, "turn_id": "another-answer"},
            frozen_plan=frozen_plan("changed"),
            completion_mode="business",
        )
    )
    assert changed["error_code"] == "request_conflict" and len(state.calls) == 1


def test_host_goal_admission_is_explicit_and_pinned_across_resume(setup_gateway):
    state = setup_gateway
    state.context["admit_goal"] = True
    rejected = asyncio.run(state.invoke(completion_mode="auto"))
    assert rejected["error_code"] == "invalid_request" and state.calls == []
    result = asyncio.run(state.invoke(completion_mode="auto", admit_goal=True))
    parent = state.repository.get(result["run_id"])
    assert parent.metadata["runtime_goal_admission"] is True
    assert "admit_goal" not in parent.metadata["runtime_context"]
    assert state.calls[0]["admit_goal"] is True
    assert state.calls[0]["system_prompt"] == "可信服务器员工说明"
    changed = asyncio.run(
        state.invoke(
            run_id=result["run_id"],
            runtime_context={**state.context, "turn_id": "attempt-disable-admission"},
            completion_mode="auto",
            admit_goal=False,
        )
    )
    assert changed["error_code"] == "invalid_request" and len(state.calls) == 1


def test_duplicate_auto_answer_reuses_request_after_internal_host_goal_freezing(setup_gateway):
    state = setup_gateway
    state.waiting_question = "查询哪种产品？"
    first = asyncio.run(state.invoke(completion_mode="auto", admit_goal=True))
    state.compiled_plan = frozen_plan()
    options = {
        "run_id": first["run_id"],
        "runtime_context": {**state.context, "turn_id": "compiler-answer"},
        "task": "fixture 产品",
        "completion_mode": "auto",
        "admit_goal": True,
        "answer_to_waiting_input": True,
    }
    resumed = asyncio.run(state.invoke(**options))
    duplicate = asyncio.run(state.invoke(**options))
    assert resumed["run_id"] == first["run_id"] == duplicate["run_id"]
    assert duplicate["deduplicated"] is True and len(state.calls) == 2
    assert state.repository.get(first["run_id"]).metadata["runtime_frozen_plan"] == frozen_plan()


@pytest.mark.parametrize(
    "value",
    [
        [],
        [{"tool_id": "products", "action": "query", "params": {}}] * 2,
        [{"tool_id": "products", "action": "query", "params": {"value": float("nan")}}],
    ],
)
def test_malformed_or_duplicate_frozen_obligations_are_rejected_before_parent_creation(
    setup_gateway, value
):
    state = setup_gateway
    result = asyncio.run(state.invoke(expected_operations=value))
    assert result["error_code"] == "invalid_expected_operations"
    assert state.repository.list_recent() == [] and state.calls == []


def test_clarification_can_freeze_host_goal_once_on_the_original_parent(setup_gateway):
    state = setup_gateway
    state.waiting_question = "查询哪种产品？"
    first = asyncio.run(state.invoke(completion_mode="business"))
    before = state.repository.get(first["run_id"])
    assert before.metadata["runtime_expected_operations"] is None
    original_digest = before.metadata["runtime_goal_digest"]
    options = {
        "run_id": first["run_id"],
        "runtime_context": {**state.context, "turn_id": "clarification-answer"},
        "task": "fixture 产品",
        "completion_mode": "business",
        "answer_to_waiting_input": True,
        "frozen_plan": frozen_plan(),
    }
    resumed = asyncio.run(state.invoke(**options))
    duplicate = asyncio.run(state.invoke(**options))
    parent = state.repository.get(first["run_id"])
    assert resumed["run_id"] == duplicate["run_id"] == first["run_id"]
    assert duplicate["deduplicated"] is True and len(state.calls) == 2
    assert parent.metadata["runtime_frozen_plan"] == options["frozen_plan"]
    assert parent.metadata["runtime_goal_digest"] != original_digest
    assert parent.metadata["codex_runtime"]["goal_digest"] == parent.metadata["runtime_goal_digest"]
    assert len([e for e in parent.events if e.event_type == "runtime.goal_frozen"]) == 1
    changed = asyncio.run(
        state.invoke(
            **{
                **options,
                "runtime_context": {**state.context, "turn_id": "attempt-to-refreeze"},
                "frozen_plan": frozen_plan("other-product"),
            }
        )
    )
    assert changed["error_code"] == "request_conflict" and len(state.calls) == 2


@pytest.mark.parametrize(
    "pending",
    ["child", "model", "coordinator", "no_question", "reservation", "request", "live_grant"],
)
def test_clarification_does_not_freeze_over_active_or_uncertain_work(setup_gateway, pending):
    state = setup_gateway
    state.waiting_question = "查询哪种产品？"
    first = asyncio.run(state.invoke(completion_mode="business"))
    parent = state.repository.get(first["run_id"])
    metadata = parent.metadata["codex_runtime"]
    if pending == "child":
        metadata["calls"] = {"existing": {"state": "unknown"}}
    elif pending == "model":
        metadata["model_requests"] = {"existing": {"state": "unknown"}}
    elif pending == "coordinator":
        metadata["coordinator_active"] = True
    elif pending == "no_question":
        metadata.pop("waiting_input")
    elif pending == "reservation":
        parent.metadata["reserved_cost_units"] = 1
    elif pending == "request":
        parent.metadata["runtime_requests"]["other"] = {"state": "admitted"}
    else:
        metadata["revoked"] = False
    state.repository.save(parent)
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "clarification-answer"},
            answer_to_waiting_input=True,
            completion_mode="business",
            frozen_plan=frozen_plan(),
        )
    )
    assert result["error_code"] == "goal_freeze_blocked" and len(state.calls) == 1
    saved = state.repository.get(first["run_id"])
    assert saved.metadata["runtime_expected_operations"] is None
    assert saved.metadata["runtime_goal_digest"] == parent.metadata["runtime_goal_digest"]


def test_competing_clarification_goals_cannot_replace_the_first_admitted_goal(setup_gateway):
    state = setup_gateway
    state.waiting_question = "查询哪种产品？"
    first = asyncio.run(state.invoke(completion_mode="business"))

    async def scenario():
        state.entered, state.release = asyncio.Event(), asyncio.Event()
        options = {
            "run_id": first["run_id"],
            "completion_mode": "business",
            "answer_to_waiting_input": True,
        }
        accepted = asyncio.create_task(
            state.invoke(
                **options,
                runtime_context={**state.context, "turn_id": "first-answer"},
                frozen_plan=frozen_plan("first"),
            )
        )
        await state.entered.wait()
        conflict = await state.invoke(
            **options,
            runtime_context={**state.context, "turn_id": "competing-answer"},
            frozen_plan=frozen_plan("second"),
        )
        state.release.set()
        return await accepted, conflict

    resumed, conflict = asyncio.run(scenario())
    assert resumed["run_id"] == first["run_id"] and conflict["error_code"] == "request_conflict"
    assert len(state.calls) == 2
    assert state.repository.get(first["run_id"]).metadata["runtime_frozen_plan"] == frozen_plan(
        "first"
    )


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


def test_missing_deployment_config_preserves_original_run_pointer_without_replanning(setup_gateway):
    state = setup_gateway
    first = asyncio.run(state.invoke())
    result = asyncio.run(
        state.invoke(
            run_id=first["run_id"],
            runtime_context={**state.context, "turn_id": "answer-two"},
            settings=RuntimeSettings(),
        )
    )
    assert result["run_id"] == first["run_id"] and result["exit_status"] == "runtime_policy_blocked"
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
