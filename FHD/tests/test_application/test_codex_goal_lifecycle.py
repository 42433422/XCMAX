"""Real SQL/goal/bridge lifecycle with an explicit fixture compiler and transport.

Business dispatch returns fixture data using the existing local_tools opt-in.
The real executor's permissions and receipts run in process for that fixture;
this is neither subprocess acceptance nor real-model deployment qualification.
"""

from __future__ import annotations

import asyncio
import copy
import json
import threading
import uuid
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import gateway, goal_admission
from app.application.agent_runtime.goal_admission import RuntimeGoal
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.infrastructure.codex import CodexTransportError
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore
from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    RuntimeSettings,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def goal_runtime(trusted_actor, tmp_path, monkeypatch):
    actor = trusted_actor(permissions=["product.view"])
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    route = ModelRoute(
        base_url="http://127.0.0.1:19180/v1",
        model="explicit-fixture-model",
        provider_id="goal-lifecycle-fixture",
        upstream_vendor="test-fixture",
        context_window=32000,
        max_output_tokens=4000,
    )
    qualification = tmp_path / "test-only-qualification.json"
    qualification.write_text(
        json.dumps(
            {
                "schema": "xcmax.runtime-qualification.v1",
                "route_identity": route.identity,
                "codex_version": CODEX_VERSION,
                "model_kind": "real",
                "evidence_refs": ["synthetic-lifecycle-fixture-only"],
                "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
            }
        )
    )
    state = SimpleNamespace(
        actor=actor,
        repository=repository,
        settings=RuntimeSettings(
            engine="codex",
            route=route,
            runtime_root=tmp_path / "runtime",
            qualification_file=qualification,
        ),
        compiler_calls=[],
        transports=[],
        dispatch_log=tmp_path / "fixture-dispatch.jsonl",
        receipts=[],
        rejections=[],
        compiler_mode="business",
        token="",
        bridge=None,
        lost_final=False,
        initial_turn="goal-fixture-" + uuid.uuid4().hex,
        compiler_entered=None,
        compiler_release=None,
    )

    class Server:
        url = "http://127.0.0.1:19181"

        def __init__(self, app):
            state.bridge = app.state.codex_tool_bridge

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    def compile_goal(binding, config):
        assert binding.metadata["runtime_config"]["route_identity"] == route.identity
        assert config.provider_token != config.mcp_token
        state.compiler_calls.append(copy.deepcopy(binding.run))
        if state.compiler_entered is not None:
            state.compiler_entered.set()
            assert state.compiler_release.wait(timeout=5), "Fixture compiler was not released"
        if state.compiler_mode == "reply":
            return RuntimeGoal(mode="reply", reply="库存表示可用产品的数量。")
        answers = [
            event for event in binding.run.events if event.event_type == "runtime.input_answered"
        ]
        if not answers:
            return RuntimeGoal(mode="business", question="请确认要查询的两个产品名称。")
        assert answers[-1].data["answer"] == "first 和 second"
        return RuntimeGoal(
            mode="business",
            plan=plan_to_dict(
                PlanGraph(
                    plan_id=f"plan_{binding.run_id}",
                    intent="products.query",
                    nodes=[
                        WorkflowNode(
                            node_id="first",
                            tool_id="products",
                            action="query",
                            params={"keyword": "first"},
                            risk="low",
                            idempotent=True,
                        ),
                        WorkflowNode(
                            node_id="second",
                            tool_id="products",
                            action="query",
                            params={"keyword": "second"},
                            depends_on=["first"],
                            risk="low",
                            idempotent=True,
                        ),
                    ],
                )
            ),
        )

    def dispatch(tool, action, params):
        # Observe dispatch separately from the execution ledger, so receipt
        # verification cannot silently execute the fixture business actions again.
        with state.dispatch_log.open("a", encoding="utf-8") as journal:
            journal.write(json.dumps([tool, action, params["keyword"]]) + "\n")
        return {"success": True, "data": [{"model_number": params["keyword"]}]}

    class Transport:
        def __init__(self, config):
            self.config = config
            state.transports.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, *, developer_instructions):
            self.instructions = developer_instructions
            return "thread-lifecycle-fixture"

        async def resume_thread(self, thread_id, *, developer_instructions):
            self.instructions = developer_instructions
            return thread_id

        async def interrupt(self):
            return None

        async def stream_turn(self, _text):
            def event(method, payload):
                return {
                    "method": method,
                    "payload": payload,
                    "thread_id": "thread-lifecycle-fixture",
                    "turn_id": "turn-fixture",
                }

            yield event("turn/started", {"turn": {"status": "inProgress"}})
            state.token = self.config.mcp_token
            binding = state.bridge.store.authenticate(state.token)
            if state.compiler_mode == "reply":
                try:
                    state.bridge.invoke(
                        state.token,
                        "execute_action",
                        {
                            "call_id": "unrequested-business-read",
                            "tool_id": "products",
                            "action": "query",
                            "params": {"keyword": "unexpected"},
                        },
                    )
                except CodexBindingError as exc:
                    state.rejections.append(exc.code)
                message = "库存表示可用产品的数量。"
            else:
                operation = binding.run.metadata["runtime_expected_operations"][0]
                state.receipts.append(
                    state.bridge.invoke(
                        state.token,
                        "execute_plan",
                        {
                            "call_id": "whole-workflow",
                            **operation["params"],
                        },
                    )
                )
                if state.lost_final:
                    raise CodexTransportError(
                        "fixture_connection_lost",
                        "fixture final response lost",
                        outcome_unknown=True,
                    )
                message = "已查询两个产品。"
            yield event(
                "item/completed",
                {
                    "item": {
                        "id": "message-fixture",
                        "type": "agentMessage",
                        "text": message,
                    }
                },
            )
            yield event("turn/completed", {"turn": {"status": "completed"}})

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setattr(gateway, "get_agent_run_repository", lambda: repository)
    monkeypatch.setattr(gateway, "LocalRuntimeServer", Server)
    monkeypatch.setattr(goal_admission, "compile_runtime_goal", compile_goal)
    monkeypatch.setattr("app.infrastructure.codex.CodexTransport", Transport)
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )

    async def invoke(**kwargs):
        return await gateway.run_runtime_task_async(
            **{
                "task": "依次查询两个产品",
                "system_prompt": "使用宿主冻结的任务和业务回执。",
                "runtime_context": {**actor.context, "turn_id": state.initial_turn},
                "completion_mode": "auto",
                "admit_goal": True,
                "settings": state.settings,
                **kwargs,
            }
        )

    state.invoke = invoke
    return state


def dispatches(state):
    if not state.dispatch_log.exists():
        return []
    return [tuple(json.loads(row)) for row in state.dispatch_log.read_text().splitlines()]


@pytest.mark.parametrize("lost_final", [False, True])
def test_auto_clarification_freezes_and_executes_one_graph_on_original_sql_parent(
    goal_runtime, lost_final, local_tools
):
    state = goal_runtime
    state.lost_final = lost_final
    waiting = asyncio.run(state.invoke())
    assert waiting["needs_user_input"] is True and waiting["business_completed"] is False
    assert dispatches(state) == [] and state.transports == []
    parent = state.repository.get(waiting["run_id"])
    assert (
        parent.status == "waiting_user" and parent.metadata["runtime_expected_operations"] is None
    )
    assert len(state.compiler_calls) == 1
    options = {
        "run_id": waiting["run_id"],
        "task": "first 和 second",
        "answer_to_waiting_input": True,
        "runtime_context": {**state.actor.context, "turn_id": "clarification-answer"},
    }
    completed = asyncio.run(state.invoke(**options))
    assert completed["business_completed"] is True, completed
    assert completed["runtime_completed"] is (not lost_final)
    assert completed["run_id"] == waiting["run_id"] and len(state.compiler_calls) == 2
    assert len(state.transports) == 1 and len(state.receipts) == 1
    assert state.receipts[0]["verified"] is True
    assert dispatches(state) == [("products", "query", "first"), ("products", "query", "second")]
    reopened = CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    binding = reopened.get(waiting["run_id"])
    assert binding.run.status == "completed"
    assert binding.run.metadata["runtime_goal_digest"] == binding.metadata["goal_digest"]
    assert len(binding.metadata["calls"]) == 1
    snapshot = reopened.receipt_snapshot(waiting["run_id"])
    assert snapshot[0]["receipt"]["verified"] is True
    assert len(dispatches(state)) == 2  # Verification replays only receipts, never business I/O.
    duplicate = asyncio.run(state.invoke(**options))
    assert duplicate["deduplicated"] is True and duplicate["business_completed"] is True
    assert len(state.compiler_calls) == 2 and len(state.transports) == 1
    with pytest.raises(CodexBindingError):
        reopened.authenticate(state.token)


def test_host_reply_admission_rejects_unrequested_business_tool_even_if_read_only(goal_runtime):
    state = goal_runtime
    state.compiler_mode = "reply"
    result = asyncio.run(state.invoke(task="库存是什么意思？"))
    assert result["reply_completed"] is True and result["business_completed"] is False
    assert state.rejections == ["goal_required"] and dispatches(state) == []
    parent = state.repository.get(result["run_id"])
    assert parent.metadata["runtime_goal_mode"] == "reply"
    assert parent.metadata["codex_runtime"]["calls"] == {}


@pytest.mark.parametrize("control", ["cancel", "pause", "revoke_actor", "expire_grant"])
def test_compiler_cannot_freeze_after_authority_changes_with_same_generation(goal_runtime, control):
    from app.db.models.user import User

    state = goal_runtime
    state.compiler_entered, state.compiler_release = threading.Event(), threading.Event()

    async def scenario():
        pending = asyncio.create_task(state.invoke())
        assert await asyncio.to_thread(state.compiler_entered.wait, 5)
        parent_id = state.compiler_calls[0].run_id
        store = CodexBindingStore(state.repository)
        generation = store.get(parent_id).metadata["generation"]
        try:
            if control in {"cancel", "pause"}:
                state.repository.request_task_control(
                    parent_id, control, requested_by=str(state.actor.user_id)
                )
            elif control == "revoke_actor":
                with state.actor.factory.begin() as db:
                    db.get(User, state.actor.user_id).is_active = False
            else:
                store.update(parent_id, lambda _run, metadata: metadata.update(expires_at=0))
        finally:
            state.compiler_release.set()
        return await asyncio.wait_for(pending, 5), parent_id, generation

    result, parent_id, generation = asyncio.run(scenario())
    assert result["ok"] is False and result["business_completed"] is False
    assert state.transports == [] and dispatches(state) == []
    parent = state.repository.get(parent_id)
    assert parent.metadata["codex_runtime"]["generation"] == generation
    assert parent.metadata["runtime_expected_operations"] is None
    assert parent.metadata["runtime_frozen_plan"] is None
    assert parent.metadata["runtime_goal_admitted"] is False
    assert "waiting_input" not in parent.metadata["codex_runtime"]
