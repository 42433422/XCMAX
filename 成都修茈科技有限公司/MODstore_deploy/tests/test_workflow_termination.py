"""F11 回归：图未到达 end 必须是失败终态，且不得发布成功事件。"""

from __future__ import annotations

import json
import types
from contextlib import contextmanager

from modstore_server.eventing.contracts import (
    WORKFLOW_EXECUTION_COMPLETED,
    WORKFLOW_EXECUTION_FAILED,
)


@contextmanager
def _as_user(user_id: int = 1):
    from modstore_server.api.deps import get_current_user
    from modstore_server.app import app

    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=user_id, username="pytest-f11", is_admin=True, email="f11@t.local"
    )
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _create_workflow(client, name: str) -> int:
    r = client.post("/api/workflow/", json={"name": name, "description": "f11"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _add_node(client, workflow_id: int, node_type: str, name: str) -> int:
    r = client.post(
        f"/api/workflow/{workflow_id}/nodes",
        json={
            "node_type": node_type,
            "name": name,
            "config": {},
            "position_x": 0,
            "position_y": 0,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _add_edge(client, workflow_id: int, source_id: int, target_id: int) -> None:
    r = client.post(
        f"/api/workflow/{workflow_id}/edges",
        json={
            "source_node_id": source_id,
            "target_node_id": target_id,
            "condition": "",
        },
    )
    assert r.status_code == 200, r.text


def _cycled_workflow(client, name: str) -> int:
    wid = _create_workflow(client, name)
    start_id = _add_node(client, wid, "start", "start")
    _add_node(client, wid, "end", "end")
    _add_edge(client, wid, start_id, start_id)
    return wid


def _linear_workflow(client, name: str) -> int:
    wid = _create_workflow(client, name)
    start_id = _add_node(client, wid, "start", "start")
    end_id = _add_node(client, wid, "end", "end")
    _add_edge(client, wid, start_id, end_id)
    return wid


def _last_execution(workflow_id: int):
    from modstore_server.models import WorkflowExecution, get_session_factory

    with get_session_factory()() as db:
        return (
            db.query(WorkflowExecution)
            .filter(WorkflowExecution.workflow_id == workflow_id)
            .order_by(WorkflowExecution.id.desc())
            .first()
        )


def test_sandbox_cycle_graph_is_failed_not_ok(client):
    with _as_user(1):
        wid = _cycled_workflow(client, "f11-cycle-sandbox")
        r = client.post(
            f"/api/workflow/{wid}/sandbox-run",
            json={"input_data": {}, "mock_employees": True, "validate_only": False},
        )

    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["sandbox_status"]["status"] == "fail"
    assert detail["sandbox_status"]["sandbox_passed_for_current_graph"] is False
    termination = detail["termination"]
    assert termination["state"] == "failed"
    assert termination["reason"] == "cycle_detected"
    assert termination["end_reached"] is False
    assert termination["executed_node_ids"]
    assert termination["message"] in detail["warnings"]
    assert detail["warnings"].count(termination["message"]) == 1


def test_api_cycle_graph_records_failed_and_skips_completed_event(client, monkeypatch):
    from modstore_server.workflow_api import execution as execution_api

    monkeypatch.setattr(execution_api, "require_llm_credit", lambda *a, **k: "test")

    events: list[str] = []
    import modstore_server.webhook_dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "publish_event", lambda name, **kwargs: events.append(name))

    with _as_user(2):
        wid = _cycled_workflow(client, "f11-cycle-api")
        r = client.post(f"/api/workflow/{wid}/execute", json={"input_data": {}})

    assert r.status_code == 500, r.text
    assert "死循环" in r.json()["detail"]

    row = _last_execution(wid)
    assert row is not None
    assert row.status == "failed"
    assert row.completed_at is not None
    assert "死循环" in (row.error_message or "")
    payload = json.loads(row.output_data or "{}")
    assert payload["termination"]["reason"] == "cycle_detected"
    assert payload["termination"]["end_reached"] is False
    assert payload["output"]["nodes"]

    assert WORKFLOW_EXECUTION_COMPLETED not in events
    assert WORKFLOW_EXECUTION_FAILED in events


def test_api_graph_reaching_end_still_completes(client, monkeypatch):
    from modstore_server.workflow_api import execution as execution_api

    monkeypatch.setattr(execution_api, "require_llm_credit", lambda *a, **k: "test")

    events: list[str] = []
    import modstore_server.webhook_dispatcher as dispatcher

    monkeypatch.setattr(dispatcher, "publish_event", lambda name, **kwargs: events.append(name))

    with _as_user(3):
        wid = _linear_workflow(client, "f11-linear-api")
        r = client.post(f"/api/workflow/{wid}/execute", json={"input_data": {"k": "v"}})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["completed_at"]

    row = _last_execution(wid)
    assert row.status == "completed"
    assert events == [WORKFLOW_EXECUTION_COMPLETED]
