from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import get_agent_run_repository
from app.application.agent_orchestrator.approval_grant import (
    clear_consumed_approval_grants_for_tests,
)
from app.application.agent_orchestrator.run_control import clear_run_controls_for_tests
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.fastapi_routes.domains.agent.routes import router
from app.infrastructure.auth.agent_principal import AgentPrincipal, require_agent_principal


def _client(user_id: str | None = "u1") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if user_id is not None:
        app.dependency_overrides[require_agent_principal] = lambda: AgentPrincipal(user_id=user_id)
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


def test_record_observed_tool_run_is_owned_and_task_scoped() -> None:
    get_agent_run_repository().clear()
    response = _client("u1").post(
        "/api/agent/runs/observed-tool",
        json={
            "message": "查 5003 产品",
            "tool_id": "products",
            "action": "query",
            "params": {"keyword": "5003"},
            "output": {"success": True, "data": []},
            "response": "未找到",
            "runtime_context": {
                "task_id": "task-product-5003",
                "conversation_id": "conversation-product-5003",
            },
        },
    )
    assert response.status_code == 200
    reference = response.json()["data"]
    assert reference["status"] == "completed"
    assert reference["task_id"] == "task-product-5003"
    stored = get_agent_run_repository().get(reference["run_id"])
    assert stored is not None
    run = stored.to_dict()
    assert run["user_id"] == "u1"
    assert run["metadata"]["task_context"]["conversation_id"] == "conversation-product-5003"
    assert run["tool_calls"][0]["tool_id"] == "products"
    assert run["metadata"]["runtime_context"]["observation_trust"] == ("authenticated_client")
    assert run["metadata"]["non_retryable"] is True


def test_record_observed_tool_rejects_write_or_unknown_tools() -> None:
    response = _client("u1").post(
        "/api/agent/runs/observed-tool",
        json={
            "message": "伪造写入",
            "tool_id": "business_db_write",
            "action": "create",
            "params": {},
            "output": {"success": True},
        },
    )
    assert response.status_code == 400


def test_failed_observation_cannot_be_retried_as_an_execution_plan() -> None:
    get_agent_run_repository().clear()
    client = _client("u1")
    observed = client.post(
        "/api/agent/runs/observed-tool",
        json={
            "message": "查产品失败",
            "tool_id": "products",
            "action": "query",
            "params": {"keyword": "5003"},
            "output": {"success": False, "message": "network unavailable"},
        },
    )
    assert observed.status_code == 200
    reference = observed.json()["data"]
    assert reference["status"] == "failed"

    retry = client.post(f"/api/agent/runs/{reference['run_id']}/retry", json={})
    assert retry.status_code == 409
    assert "观察记录" in retry.json()["message"]


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
        response = owner.post("/api/agent/runs", json={"message": "请把客户 星光贸易 写入数据库"})
        run_id = response.json()["data"]["run_id"]
        grant = response.json()["approval"]["grant"]
        second_grant = owner.get(f"/api/agent/runs/{run_id}").json()["approval"]["grant"]

        missing_grant = owner.post(f"/api/agent/runs/{run_id}/continue", json={})
        assert missing_grant.status_code == 403
        assert missing_grant.json()["message"] == ("approval_grant 无效、过期或与当前步骤不匹配")
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


def test_agent_routes_do_not_expose_internal_exception_details() -> None:
    secret = "Traceback: database password=do-not-expose"
    repository = get_agent_run_repository()
    repository.clear()
    run = AgentRun(user_id="u1", message="执行任务", status="failed", error=secret)
    run.steps.append(
        AgentStep(
            node_id="n1",
            tool_id="products",
            action="query",
            status="failed",
            error=secret,
            output={"success": False, "error": secret},
        )
    )
    run.tool_calls.append(
        ToolCall(
            step_id=run.steps[0].step_id,
            node_id="n1",
            tool_id="products",
            action="query",
            status="failed",
            error=secret,
        )
    )
    run.add_event("run.failed", "Agent run 失败", {"error": secret})

    client = _client()
    with patch(
        "app.fastapi_routes.domains.agent.routes.AgentOrchestrator.start_run",
        return_value=run,
    ):
        response = client.post("/api/agent/runs", json={"message": "执行任务"})

    assert response.status_code == 200
    assert secret not in response.text
    payload = response.json()["data"]
    assert payload["error"] == "Agent 执行失败，详细信息已记录"
    assert payload["steps"][0]["output"]["error"] == "Agent 执行失败，详细信息已记录"
    assert payload["events"][0]["data"]["error"] == "Agent 执行失败，详细信息已记录"

    repository.save(run)
    list_response = client.get("/api/agent/runs")
    events_response = client.get(f"/api/agent/runs/{run.run_id}/events")
    assert secret not in list_response.text
    assert secret not in events_response.text


def test_agent_route_internal_failure_returns_stable_public_message() -> None:
    client = _client()
    with patch(
        "app.fastapi_routes.domains.agent.routes.AgentOrchestrator.start_run",
        side_effect=RuntimeError("Traceback: database password=do-not-expose"),
    ):
        response = client.post("/api/agent/runs", json={"message": "执行任务"})

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "message": "Agent 服务暂时不可用，请稍后重试",
    }


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
        cancelled = client.post(f"/api/agent/runs/{second['run_id']}/cancel").json()["data"]
        assert cancelled["status"] == "cancelled"
        assert cancelled["steps"][0]["status"] == "skipped"
        assert cancelled["final_output"]["cancelled"] is True


def test_retry_agent_run_preserves_task_identity_and_creates_new_attempt() -> None:
    repository = get_agent_run_repository()
    repository.clear()
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
        ),
    ):
        created = client.post(
            "/api/agent/runs",
            json={
                "message": "核对库存",
                "auto_execute": False,
                "runtime_context": {
                    "conversation_id": "conversation-42",
                    "task_id": "conversation-42",
                    "task_title": "库存核对任务",
                },
            },
        ).json()["data"]
        cancelled = client.post(f"/api/agent/runs/{created['run_id']}/cancel").json()["data"]
        assert cancelled["status"] == "cancelled"

        response = client.post(
            f"/api/agent/runs/{created['run_id']}/retry",
            json={"runtime_context": {"task_id": "other-task", "conversation_id": "other-chat"}},
        )
        replay = client.post(f"/api/agent/runs/{created['run_id']}/retry", json={})

    assert response.status_code == 200
    retried_reference = response.json()["data"]
    assert replay.status_code == 200
    assert replay.json()["data"]["run_id"] == retried_reference["run_id"]
    assert retried_reference["run_id"] != created["run_id"]
    retried_stored = repository.get(retried_reference["run_id"])
    assert retried_stored is not None
    retried = retried_stored.to_dict()
    assert retried["metadata"]["task_context"] == {
        "task_id": "conversation-42",
        "title": "库存核对任务",
        "conversation_id": "conversation-42",
        "root_run_id": created["run_id"],
        "parent_run_id": created["run_id"],
        "attempt": 2,
        "workspace_id": "",
        "workspace_path": "",
        "isolation": "business_workspace",
    }
    previous = repository.get(created["run_id"])
    assert previous is not None
    assert previous.events[-1].event_type == "run.retry_created"


def test_retry_agent_run_rejects_non_terminal_task() -> None:
    repository = get_agent_run_repository()
    repository.clear()
    run = AgentRun(user_id="owner", message="仍在运行", status="running")
    repository.save(run)

    response = _client("owner").post(f"/api/agent/runs/{run.run_id}/retry", json={})

    assert response.status_code == 409
    assert "可以重试" in response.json()["message"]


def test_get_agent_run_returns_404_for_missing_run() -> None:
    get_agent_run_repository().clear()
    client = _client()

    response = client.get("/api/agent/runs/run_missing")

    assert response.status_code == 404
    assert response.json()["success"] is False

    events_response = client.get("/api/agent/runs/run_missing/events")
    assert events_response.status_code == 404
    assert events_response.json()["success"] is False


def test_unified_task_requires_approval_and_deduplicates_execution() -> None:
    repository = get_agent_run_repository()
    repository.clear()
    clear_consumed_approval_grants_for_tests()
    client = _client("task-owner")
    body = {
        "task_id": "chat-shipment-001",
        "title": "生成客户甲发货单",
        "message": "给客户甲生成一张发货单",
        "tool_id": "shipment_orders",
        "action": "generate",
        "params": {
            "unit_name": "客户甲",
            "products": [{"model_number": "A-01", "quantity": 2}],
        },
        "runtime_context": {"conversation_id": "chat-001"},
    }

    with patch(
        "app.application.facades.tools_facade.execute_registered_workflow_tool",
        return_value={
            "success": True,
            "message": "发货单已生成",
            "order_id": 41,
            "file_path": "/tmp/shipment-41.docx",
        },
    ) as execute:
        created = client.post("/api/agent/tasks", json=body)
        assert created.status_code == 202
        created_payload = created.json()
        run = created_payload["data"]
        assert run["status"] == "waiting_user"
        assert run["steps"][0]["status"] == "waiting_user"
        assert created_payload["capabilities"]["approve"] is True
        assert created_payload["capabilities"]["pause"] is True
        assert created_payload["deduplicated"] is False
        execute.assert_not_called()

        paused = client.post(f"/api/agent/runs/{run['run_id']}/pause").json()
        assert paused["data"]["status"] == "paused"
        assert paused["capabilities"]["resume"] is True

        resumed = client.post(f"/api/agent/runs/{run['run_id']}/resume", json={}).json()
        assert resumed["data"]["status"] == "waiting_user"
        assert resumed["capabilities"]["approve"] is True
        execute.assert_not_called()

        approval_grant = resumed["approval"]["grant"]
        approved = client.post(
            f"/api/agent/runs/{run['run_id']}/continue",
            json={"approval_grant": approval_grant},
        )
        assert approved.status_code == 200
        completed = approved.json()["data"]
        assert completed["status"] == "completed"
        assert completed["tool_calls"][0]["status"] == "completed"
        assert completed["final_output"]["node_outputs"]
        assert "step.approved" in [event["event_type"] for event in completed["events"]]
        execute.assert_called_once()
        assert execute.call_args.args[:2] == ("shipment_orders", "generate")
        assert execute.call_args.args[2]["unit_name"] == "客户甲"
        assert execute.call_args.args[2]["products"] == [{"model_number": "A-01", "quantity": 2}]
        assert isinstance(execute.call_args.args[2]["_runtime_context"], dict)

        duplicate = client.post("/api/agent/tasks", json=body)
        assert duplicate.status_code == 200
        assert duplicate.json()["deduplicated"] is True
        assert duplicate.json()["data"]["run_id"] == run["run_id"]
        execute.assert_called_once()

    mismatched = client.post(
        "/api/agent/tasks",
        json={**body, "params": {"unit_name": "客户乙", "products": [{"quantity": 1}]}},
    )
    assert mismatched.status_code == 409


def test_unified_low_risk_task_cancel_and_retry_preserve_exact_approval() -> None:
    repository = get_agent_run_repository()
    repository.clear()
    client = _client("task-owner")
    body = {
        "task_id": "chat-shipment-retry",
        "title": "可恢复客户查询任务",
        "tool_id": "customers",
        "action": "query",
        "params": {"keyword": "客户乙"},
    }
    created = client.post("/api/agent/tasks", json=body).json()["data"]
    cancelled = client.post(f"/api/agent/runs/{created['run_id']}/cancel").json()["data"]
    assert cancelled["status"] == "cancelled"

    with patch("app.application.facades.tools_facade.execute_registered_workflow_tool") as execute:
        retried = client.post(f"/api/agent/runs/{created['run_id']}/retry", json={})

    assert retried.status_code == 200
    retried_run = repository.get(retried.json()["data"]["run_id"])
    assert retried_run is not None
    assert retried_run.status == "waiting_user"
    assert retried_run.steps[0].tool_id == "customers"
    assert retried_run.steps[0].action == "query"
    assert retried_run.steps[0].params == body["params"]
    assert retried_run.metadata["task_context"]["task_id"] == body["task_id"]
    assert retried_run.metadata["task_context"]["attempt"] == 2
    execute.assert_not_called()
