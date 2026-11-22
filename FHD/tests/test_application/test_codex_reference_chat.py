"""Real HTTP chat answers keep the frozen child and its independent write approval."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_runtime import codex_runtime, gateway, goal_admission
from app.application.agent_runtime.goal_admission import RuntimeGoal
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def reference_chat(runtime_entry, monkeypatch):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.legacy.routes.conversation.compat_routes import router

    state = runtime_entry
    state.compiler_calls, state.transports, state.business_calls = [], [], []

    def compile_goal(binding, _config):
        state.compiler_calls.append(binding.run_id)
        return RuntimeGoal(
            mode="business",
            plan=plan_to_dict(
                PlanGraph(
                    plan_id=f"plan_{binding.run_id}",
                    intent="reference-answer-fixture",
                    nodes=[
                        WorkflowNode(
                            node_id="lookup",
                            tool_id="products",
                            action="query",
                            params={"keyword": "fixture"},
                            idempotent=True,
                        ),
                        WorkflowNode(
                            node_id="create",
                            tool_id="customers",
                            action="create",
                            params={"unit_name": "{{lookup.data[0].model_number}}"},
                            depends_on=["lookup"],
                            risk="high",
                        ),
                    ],
                )
            ),
        )

    def dispatch(tool, action, _params):
        state.business_calls.append((tool, action))
        assert (tool, action) == ("products", "query"), "selection must never approve the write"
        return {
            "success": True,
            "data": [{"id": 7, "model_number": "first"}, {"id": 8, "model_number": "second"}],
        }

    class Transport:
        def __init__(self, config):
            self.config = config
            state.transports.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, *, developer_instructions):
            return "reference-chat-fixture"

        async def interrupt(self):
            return None

        async def stream_turn(self, _text):
            bridge = state.servers[-1].state.codex_tool_bridge
            binding = bridge.store.authenticate(self.config.mcp_token)
            operation = binding.run.metadata["runtime_expected_operations"][0]
            bridge.invoke(
                self.config.mcp_token,
                "execute_plan",
                {"call_id": "reference-graph", **operation["params"]},
            )
            yield {
                "method": "turn/completed",
                "payload": {"turn": {"status": "completed"}},
                "thread_id": "reference-chat-fixture",
                "turn_id": "initial-turn",
            }

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setattr(goal_admission, "compile_runtime_goal", compile_goal)
    monkeypatch.setattr(gateway, "run_codex_agent", codex_runtime.run_codex_agent)
    monkeypatch.setattr("app.infrastructure.codex.CodexTransport", Transport)
    monkeypatch.setattr(
        "app.application.agent_runtime.chat.runtime_settings", lambda: state.settings
    )
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app, headers=state.actor.headers) as client:
        state.chat_client = client
        state.conversation = "reference-chat-" + uuid.uuid4().hex
        yield state


def test_real_chat_candidate_answer_queues_same_child_without_model_or_write_approval(
    reference_chat, local_tools
):
    state = reference_chat
    context = {"session_id": state.conversation, "turn_id": "initial-reference-turn"}
    response = state.chat_client.post(
        "/api/ai/chat", json={"message": "查询候选并以选中名称新增客户", "context": context}
    )
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["needs_user_input"] is True, first
    parent_id = first["run_id"]
    question = first["data"]["clarification"]
    child_id, step_id = question["run_id"], question["step_id"]
    assert child_id != parent_id
    frozen = state.repository.get(parent_id).metadata["runtime_frozen_plan"]
    context["agent_runtime_run_id"] = parent_id
    context["turn_id"] = "unclear-reference-answer"
    uncertain = state.chat_client.post(
        "/api/ai/chat", json={"message": "确认", "context": context}
    ).json()
    assert uncertain["needs_user_input"] is True, uncertain
    assert uncertain["requires_confirmation"] is False
    assert state.repository.get(child_id).status == "waiting_user"
    assert state.queue.get(child_id) is None

    context["turn_id"] = "selected-reference-answer"
    answer_payload = {"message": "第二个", "context": context}
    answered = state.chat_client.post("/api/ai/chat", json=answer_payload).json()
    assert answered["run_id"] == parent_id, answered
    assert answered["execution_state"] == "running", answered
    queued = state.repository.get(child_id)
    assert queued.status == "queued"
    proof = queued.metadata["reference_clarifications"][step_id]
    assert proof["answer"]["parameters"] == {"id": "8"}
    assert proof["answer"]["answered_by"] == str(state.actor.user_id)
    assert queued.metadata["dispatch"]["approved_step_id"] == ""
    assert state.queue.get(child_id).state == "queued"
    # HTTP request replay cannot re-answer a later question or enqueue a new child.
    repeated = state.chat_client.post("/api/ai/chat", json=answer_payload)
    assert repeated.status_code == 200, repeated.text
    assert (
        state.repository.get(child_id).metadata["reference_clarifications"]
        == queued.metadata["reference_clarifications"]
    )
    continued = state.drain(child_id)
    assert continued.status == "waiting_user", continued.to_dict()
    write = next(step for step in continued.steps if step.node_id == "create")
    assert write.status == "waiting_user" and write.params == {"unit_name": "second"}
    context["turn_id"] = "not-a-write-approval"
    pending = state.chat_client.post(
        "/api/ai/chat", json={"message": "确认", "context": context}
    ).json()
    assert pending["run_id"] == parent_id and pending["requires_confirmation"] is True, pending
    assert pending["data"]["data"]["approval_card"]["run_id"] == child_id
    assert state.business_calls == [("products", "query")]
    assert len(state.compiler_calls) == len(state.transports) == 1
    assert state.repository.get(parent_id).metadata["runtime_frozen_plan"] == frozen
