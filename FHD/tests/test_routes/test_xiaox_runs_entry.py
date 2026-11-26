"""Natural-language HTTP tasks share the durable fixed-executor entry."""

from dataclasses import replace

import pytest

from app.application.agent_runtime import gateway
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


def test_create_get_and_list_xiaox_parent_with_host_goal_admission(runtime_entry):
    state = runtime_entry
    response = state.client.post(
        "/api/agent/runs",
        json={
            "message": "解释库存含义",
            "request_id": "explain-one",
            "user_id": "forged-user",
            "system_prompt": "untrusted instructions",
            "expected_operations": [{"tool_id": "forged"}],
            "runtime_context": {
                "user_id": "forged-user",
                "tenant_id": "forged-tenant",
                "_actor_authorization": {"proof": "forged"},
                "runtime_expected_operations": [{"tool_id": "forged"}],
                "source": "route-test",
            },
        },
    )
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["data"]["status"] == "queued"
    assert payload["execution"]["state"] == "queued"
    assert state.calls == state.servers == []
    parent = state.drain(payload["data"]["run_id"])
    assert parent.intent == "xiaox.runtime" and parent.status == "completed"
    assert parent.user_id == str(state.actor.user_id)
    context = parent.metadata["runtime_context"]
    assert context["tenant_id"] == str(state.actor.tenant_id)
    assert context["_actor_authorization"] == state.actor.context["_actor_authorization"]
    assert context["source"] == "xiaox_runtime"
    assert "runtime_expected_operations" not in parent.metadata
    assert "runtime_expected_operations" not in context
    assert "untrusted instructions" not in parent.metadata["_xiaox_system_prompt"]
    assert state.calls[0]["completion_mode"] == "auto"
    assert "admit_goal" not in state.calls[0]
    assert state.queue.get(parent.run_id).state == "succeeded"
    assert parent.steps == [] and parent.tool_calls == []
    assert "_actor_authorization" not in response.text
    assert (
        state.client.get(f"/api/agent/runs/{parent.run_id}").json()["data"]["run_id"]
        == parent.run_id
    )
    listing = state.client.get("/api/agent/runs").json()
    assert [run["run_id"] for run in listing["data"]] == [parent.run_id]


def test_auto_execute_false_persists_without_io_and_resumes_same_parent(runtime_entry):
    state = runtime_entry
    body = {"message": "解释库存含义", "auto_execute": False, "request_id": "stage-one"}
    response = state.client.post("/api/agent/runs", json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    run_id = payload["data"]["run_id"]
    assert payload["data"]["status"] == "paused"
    assert payload["runtime_result"]["resume_required"] is True
    assert payload["capabilities"]["resume"] is True
    parent = state.repository.get(run_id)
    assert parent.metadata["xiaox_runtime"]["generation"] == 0
    assert parent.metadata["xiaox_runtime"]["token_hashes"] == {}
    assert parent.metadata["xiaox_runtime"]["calls"] == {}
    assert state.calls == state.servers == []
    duplicate = state.client.post("/api/agent/runs", json=body)
    assert duplicate.json()["data"]["run_id"] == run_id
    assert duplicate.json()["runtime_result"]["deduplicated"] is True
    conflict = state.client.post("/api/agent/runs", json={**body, "auto_execute": True})
    assert conflict.status_code == 409
    assert state.calls == state.servers == []

    resumed = state.client.post(
        f"/api/agent/runs/{run_id}/resume", json={"request_id": "resume-one"}
    )
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["data"]["run_id"] == run_id
    assert resumed.json()["data"]["status"] == "queued"
    assert state.calls == state.servers == []
    assert state.drain(run_id).status == "completed"
    assert len(state.calls) == len(state.servers) == 1
    assert state.calls[0]["completion_mode"] == "auto" and "admit_goal" not in state.calls[0]
    assert state.repository.get(run_id).metadata["xiaox_runtime"]["generation"] == 1
    assert len(state.repository.list_recent()) == 1


def test_onboarding_conversation_reference_gets_host_revision(runtime_entry):
    state = runtime_entry
    response = state.client.post(
        "/api/agent/runs",
        json={
            "message": "解释库存含义",
            "runtime_context": {
                "conversation_id": "onboarding-conversation",
                "_conversation_revision": 999,
                "source": "product_onboarding_first_order",
            },
        },
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["data"]["run_id"]
    parent = state.repository.get(run_id)
    assert parent.metadata["runtime_context"]["_conversation_revision"] == 0
    assert state.calls == state.servers == []
    assert state.drain(run_id).status == "completed"


def test_run_cannot_bind_another_owners_conversation(runtime_entry, trusted_actor):
    from app.application.task_conversation_store import task_conversation_store

    state = runtime_entry
    other = trusted_actor(role="user")
    task_conversation_store.prepare_revision(session_id="private-history", user_id=other.user_id)
    response = state.client.post(
        "/api/agent/runs",
        json={"message": "解释库存含义", "runtime_context": {"conversation_id": "private-history"}},
    )
    assert response.status_code == 403, response.text
    assert state.repository.list_recent() == []
    assert state.calls == state.servers == []


def test_conversation_deleted_before_worker_blocks_queued_run(runtime_entry):
    from app.application.task_conversation_store import task_conversation_store

    state = runtime_entry
    response = state.client.post(
        "/api/agent/runs",
        json={"message": "解释库存含义", "runtime_context": {"conversation_id": "deleted-history"}},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["data"]["run_id"]
    assert task_conversation_store.delete_session(
        session_id="deleted-history", user_id=state.actor.user_id
    )
    blocked = state.drain(run_id)
    assert blocked.status in {"blocked", "failed"}
    assert state.calls == state.servers == []


def test_cancel_staged_parent_never_creates_runtime_authority(runtime_entry):
    state = runtime_entry
    created = state.client.post(
        "/api/agent/runs", json={"message": "解释库存含义", "auto_execute": False}
    ).json()["data"]
    run_id = created["run_id"]
    cancelled = state.client.post(f"/api/agent/runs/{run_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert state.client.post(f"/api/agent/runs/{run_id}/resume", json={}).status_code == 409
    assert state.repository.get(run_id).metadata["xiaox_runtime"]["generation"] == 0
    assert state.calls == state.servers == []


def test_unqualified_entry_queues_but_worker_blocks_without_a_native_fallback(runtime_entry):
    state = runtime_entry
    state.settings = replace(state.settings, qualification_file=None)
    response = state.client.post("/api/agent/runs", json={"message": "解释库存含义"})
    # HTTP only enqueues a durable parent; qualification is enforced by the worker.
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["data"]["status"] == "queued"
    assert payload["runtime_result"]["legacy_fallback_allowed"] is False
    assert state.calls == state.servers == []

    run_id = payload["data"]["run_id"]
    blocked = state.drain(run_id)
    result = blocked.final_output["xiaox_result"]
    assert result["run_id"] == run_id and result["ok"] is False
    assert result["error_code"] == "runtime_policy_blocked"
    assert result["legacy_fallback_allowed"] is False
    assert blocked.metadata["xiaox_runtime"]["generation"] == 0
    assert state.queue.get(run_id).last_error_code == "runtime_policy_blocked"
    assert state.repository.get(run_id).final_output["xiaox_result"]["run_id"] == run_id
    assert len(state.repository.list_recent()) == 1
    assert state.calls == state.servers == []


@pytest.mark.parametrize(
    "override",
    [
        {"auto_execute": "false"},
        {"auto_execute": 0},
        {"request_id": ""},
        {"request_id": []},
        {"runtime_context": None},
    ],
)
def test_invalid_admission_fields_do_not_create_a_task(runtime_entry, override):
    state = runtime_entry
    response = state.client.post("/api/agent/runs", json={"message": "解释库存含义", **override})
    assert response.status_code == 400
    assert state.repository.list_recent() == []
    assert state.calls == state.servers == []


def test_explicit_tool_task_keeps_controlled_graph_lane(runtime_entry, monkeypatch):
    state = runtime_entry
    monkeypatch.setattr(
        gateway, "run_runtime_task", lambda **kw: pytest.fail("explicit leaf recursed into Xiaox")
    )
    response = state.client.post(
        "/api/agent/tasks",
        json={
            "task_id": "explicit-query",
            "title": "查询产品",
            "tool_id": "products",
            "action": "query",
            "params": {"keyword": "XG-5003"},
        },
    )
    assert response.status_code == 202, response.text
    run = state.repository.get(response.json()["data"]["run_id"])
    assert run.metadata.get("runtime_type") != "xiaox"
    assert (run.steps[0].tool_id, run.steps[0].action) == ("products", "query")
    assert state.calls == state.servers == []
