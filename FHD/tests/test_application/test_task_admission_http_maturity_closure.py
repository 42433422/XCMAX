"""Capacity rejection is an atomic, retryable response on the real HTTP entry."""

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry


def test_http_capacity_is_retryable_and_rolls_back_the_original_parent(runtime_entry, monkeypatch):
    state = runtime_entry
    monkeypatch.setenv("XCAGI_AGENT_TASK_MAX_ADMITTED", "1")
    original = {"message": "解释库存含义", "request_id": "occupies-capacity"}
    first = state.client.post("/api/agent/runs", json=original)
    assert first.status_code == 202, first.text
    rejected = {"message": "解释库存含义", "request_id": "retry-same-request"}
    second = state.client.post("/api/agent/runs", json=rejected)
    assert second.status_code == 429, second.text
    assert second.headers["Retry-After"] == "1"
    result = second.json()
    assert result["error_code"] == "task_queue_capacity"
    assert result["retryable"] is True and result["outcome"] == "not_started"
    assert len(state.repository.list_recent()) == 1
    duplicate = state.client.post("/api/agent/runs", json=original)
    assert duplicate.status_code == 202 and duplicate.json()["runtime_result"]["deduplicated"]
    run_id = first.json()["data"]["run_id"]
    assert state.client.post(f"/api/agent/runs/{run_id}/cancel").status_code == 200
    retried = state.client.post("/api/agent/runs", json=rejected)
    assert retried.status_code == 202, retried.text
    assert len(state.repository.list_recent()) == 2 and state.calls == state.servers == []
