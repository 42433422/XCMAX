"""Candidate answers preserve the original goal and require independent write approval."""

from __future__ import annotations

import copy
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.task_lifecycle.agent_runtime_contract import goal_answers
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import (
    dynamic_chat_runtime as dynamic_chat_runtime,
)
from tests.fixtures.xiaox_http_runtime import finish_queued_chat
from tests.fixtures.xiaox_http_runtime import (
    runtime_entry as runtime_entry,
)


@pytest.fixture
def reference_chat(dynamic_chat_runtime, monkeypatch):
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.legacy.routes.conversation.compat_routes import router

    state = dynamic_chat_runtime
    state.business_calls = []

    def dispatch(tool, action, _params):
        state.business_calls.append((tool, action))
        assert (tool, action) == ("products", "query"), "selection must never approve the write"
        return {
            "success": True,
            "data": [{"id": 7, "model_number": "first"}, {"id": 8, "model_number": "second"}],
        }

    def script(binding, text):
        answers = goal_answers(binding.run)
        if not answers:
            receipt = state.execute("products", "query", {"keyword": "fixture"}, "candidates")
            assert receipt["status"] == "completed", receipt
        if not answers or answers[-1]["answer"] != "第二个":
            state.bridge.invoke(
                state.token, "request_input", {"question": "请选择客户名称：1. first；2. second。"}
            )
            return "请明确选择候选；选择不授予写入审批。"
        assert "查询候选并以选中名称新增客户" in text
        receipt = state.execute("customers", "create", {"unit_name": "second"}, "create-selected")
        assert receipt["pending_approval"] is True, receipt
        return "已选择 second，新增客户须审批。"

    state.script = script
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


def test_real_chat_candidate_answer_continues_same_goal_without_write_approval(
    reference_chat, local_tools
):
    state = reference_chat
    context = {"session_id": state.conversation, "turn_id": "initial-reference-turn"}

    def send(message):
        response = state.chat_client.post(
            "/api/ai/chat", json={"message": message, "context": context}
        )
        assert response.status_code == 200, response.text
        return response.json()

    initial = send("查询候选并以选中名称新增客户")
    assert initial["execution_state"] == "queued", initial
    first = finish_queued_chat(state, initial)
    assert first["needs_user_input"] is True, first
    parent_id = first["run_id"]
    original = state.repository.get(parent_id)
    contract = copy.deepcopy(original.metadata["runtime_goal_contract"])
    thread_id = original.metadata["xiaox_runtime"]["thread_id"]
    context["agent_runtime_run_id"] = parent_id
    context["turn_id"] = "unclear-reference-answer"
    uncertain = finish_queued_chat(state, send("确认"))
    assert uncertain["needs_user_input"] is True, uncertain
    assert uncertain["requires_confirmation"] is False
    assert state.business_calls == [("products", "query")]

    context["turn_id"] = "selected-reference-answer"
    answered = finish_queued_chat(state, send("第二个"))
    assert answered["run_id"] == parent_id, answered
    assert answered["requires_confirmation"] is True, answered
    child_id = answered["data"]["data"]["approval_card"]["run_id"]
    assert child_id != parent_id
    child = state.repository.get(child_id)
    assert child.status == "waiting_user"
    assert len(child.steps) == 1
    write = child.steps[0]
    assert write.status == "waiting_user" and write.params == {"unit_name": "second"}
    assert state.queue.get(child_id) is None

    assert send("第二个")["run_id"] == parent_id
    context["turn_id"] = "not-a-write-approval"
    pending = send("确认")
    assert pending["run_id"] == parent_id and pending["requires_confirmation"] is True, pending
    assert pending["data"]["data"]["approval_card"]["run_id"] == child_id
    assert state.repository.get(child_id).status == "waiting_user"
    assert state.business_calls == [("products", "query")]
    final = state.repository.get(parent_id)
    assert final.metadata["runtime_goal_contract"] == contract
    assert final.metadata["xiaox_runtime"]["thread_id"] == thread_id
    assert len(final.metadata["xiaox_runtime"]["calls"]) == 2
    assert [item["answer"] for item in goal_answers(final)] == ["确认", "第二个"]
    assert len(state.admissions) == 1 and len(state.transports) == 3
    assert state.model_requests == [], "pending approvals must not be audited as completion"
