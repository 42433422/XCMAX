from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import get_agent_run_repository
from app.application.agent_orchestrator.approval_grant import (
    clear_consumed_approval_grants_for_tests,
)
from app.application.agent_orchestrator.run_control import clear_run_controls_for_tests
from app.fastapi_routes.domains.agent.routes import router
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal


def _client(user_id: str | None = "u1") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if user_id is not None:
        app.dependency_overrides[require_agent_principal] = lambda: AgentPrincipal(
            user_id=user_id
        )
    return TestClient(app, raise_server_exceptions=False)


def _planner_fallback_patches():
    return (
        patch("app.application.workflow.planner.get_ai_conversation_service"),
        patch(
            "app.application.workflow.planner.LLMWorkflowPlanner._plan_with_react_multiagent",
            return_value=None,
        ),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="pro_default",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
    )


def test_create_get_and_list_agent_run() -> None:
    get_agent_run_repository().clear()
    clear_consumed_approval_grants_for_tests()
    client = _client()
    patches = _planner_fallback_patches()

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": [{"model_number": "XG-5003"}]},
        ),
    ):
        response = client.post(
            "/api/agent/runs",
            json={
                "message": "查数据库产品 XG-5003",
                "user_id": "forged-user",
                "runtime_context": {"source": "route-test"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    run = payload["data"]
    assert run["status"] == "completed"
    assert run["user_id"] == "u1"
    assert run["intent"] == "business_db_read"
    assert run["metadata"]["runtime_context"]["source"] == "route-test"
    assert "run.completed" in [event["event_type"] for event in run["events"]]

    get_response = client.get(f"/api/agent/runs/{run['run_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["run_id"] == run["run_id"]

    events_response = client.get(f"/api/agent/runs/{run['run_id']}/events")
    assert events_response.status_code == 200
    events_payload = events_response.json()
    assert events_payload["count"] == len(run["events"])
    assert events_payload["data"][-1]["event_type"] == "run.completed"

    first_event_id = events_payload["data"][0]["event_id"]
    tail_response = client.get(
        f"/api/agent/runs/{run['run_id']}/events",
        params={"after_event_id": first_event_id},
    )
    assert tail_response.status_code == 200
    assert tail_response.json()["count"] == len(run["events"]) - 1

    stream_response = client.get(f"/api/agent/runs/{run['run_id']}/events/stream")
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert "event: run.completed" in stream_response.text
    assert "event: stream.closed" in stream_response.text

    list_response = client.get("/api/agent/runs", params={"user_id": "u1"})
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert list_payload["data"][0]["run_id"] == run["run_id"]


def test_continue_waiting_agent_run() -> None:
    get_agent_run_repository().clear()
    clear_consumed_approval_grants_for_tests()
    client = _client()
    patches = _planner_fallback_patches()

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool"
        ) as mock_execute,
    ):
        create_response = client.post(
            "/api/agent/runs",
            json={
                "message": "请把客户 星光贸易 写入数据库",
                "user_id": "u1",
                "runtime_context": {"source": "route-continue-test"},
            },
        )
        assert create_response.status_code == 202
        waiting = create_response.json()["data"]
        approval_grant = create_response.json()["approval"]["grant"]
        assert waiting["status"] == "waiting_user"
        mock_execute.assert_not_called()

        mock_execute.return_value = {"success": True, "message": "客户已写入"}
        continue_response = client.post(
            f"/api/agent/runs/{waiting['run_id']}/continue",
            json={"approval_grant": approval_grant, "approved_by": "forged-approver"},
        )

    assert continue_response.status_code == 200
    payload = continue_response.json()
    assert payload["success"] is True
    completed = payload["data"]
    assert completed["status"] == "completed"
    assert completed["steps"][0]["status"] == "completed"
    event_types = [event["event_type"] for event in completed["events"]]
    assert "step.approved" in event_types
    assert "tool.completed" in event_types
    mock_execute.assert_called_once()


def test_agent_routes_require_authentication_and_enforce_ownership() -> None:
    get_agent_run_repository().clear()
    anonymous = _client(user_id=None)
    assert anonymous.get("/api/agent/runs").status_code == 401

    owner = _client("owner")
    patches = _planner_fallback_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": []},
        ),
    ):
        created = owner.post("/api/agent/runs", json={"message": "查产品"}).json()["data"]

    stranger = _client("stranger")
    assert stranger.get(f"/api/agent/runs/{created['run_id']}").status_code == 403
    assert stranger.get(f"/api/agent/runs/{created['run_id']}/events").status_code == 403
    assert stranger.get("/api/agent/runs").json()["count"] == 0


def test_continue_rejects_missing_mismatched_and_replayed_grants() -> None:
    get_agent_run_repository().clear()
    clear_consumed_approval_grants_for_tests()
    owner = _client("owner")
    patches = _planner_fallback_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True},
        ),
    ):
        response = owner.post(
            "/api/agent/runs", json={"message": "请把客户 星光贸易 写入数据库"}
        )
        run_id = response.json()["data"]["run_id"]
        grant = response.json()["approval"]["grant"]
        second_grant = owner.get(f"/api/agent/runs/{run_id}").json()["approval"]["grant"]

        assert owner.post(f"/api/agent/runs/{run_id}/continue", json={}).status_code == 403
        assert (
            _client("stranger")
            .post(f"/api/agent/runs/{run_id}/continue", json={"approval_grant": grant})
            .status_code
            == 403
        )
        assert (
            owner.post(
                f"/api/agent/runs/{run_id}/continue", json={"approval_grant": grant}
            ).status_code
            == 200
        )
        assert (
            owner.post(
                f"/api/agent/runs/{run_id}/continue", json={"approval_grant": second_grant}
            ).status_code
            == 403
        )


def test_create_agent_run_validates_request_body() -> None:
    get_agent_run_repository().clear()
    client = _client()

    missing_message = client.post("/api/agent/runs", json={"user_id": "u1"})
    assert missing_message.status_code == 400
    assert missing_message.json()["success"] is False

    bad_context = client.post(
        "/api/agent/runs",
        json={"message": "查库存", "runtime_context": ["bad"]},
    )
    assert bad_context.status_code == 400
    assert bad_context.json()["success"] is False


def test_pause_resume_and_cancel_agent_run() -> None:
    get_agent_run_repository().clear()
    clear_run_controls_for_tests()
    client = _client("owner")
    patches = _planner_fallback_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "data": []},
        ) as execute,
    ):
        created = client.post(
            "/api/agent/runs",
            json={"message": "查产品", "auto_execute": False},
        ).json()["data"]
        paused = client.post(f"/api/agent/runs/{created['run_id']}/pause").json()["data"]
        assert paused["status"] == "paused"
        execute.assert_not_called()

        resumed = client.post(
            f"/api/agent/runs/{created['run_id']}/resume",
            json={"runtime_context": {"source": "resume-test"}},
        ).json()["data"]
        assert resumed["status"] == "completed"
        execute.assert_called_once()

        second = client.post(
            "/api/agent/runs",
            json={"message": "查产品", "auto_execute": False},
        ).json()["data"]
        cancelled = client.post(
            f"/api/agent/runs/{second['run_id']}/cancel"
        ).json()["data"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["steps"][0]["status"] == "skipped"
        assert cancelled["final_output"]["cancelled"] is True


def test_get_agent_run_returns_404_for_missing_run() -> None:
    get_agent_run_repository().clear()
    client = _client()

    response = client.get("/api/agent/runs/run_missing")

    assert response.status_code == 404
    assert response.json()["success"] is False

    events_response = client.get("/api/agent/runs/run_missing/events")
    assert events_response.status_code == 404
    assert events_response.json()["success"] is False
