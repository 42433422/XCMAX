from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client() -> TestClient:
    from app.fastapi_routes.domains.system.system_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_mock_template_needs_readback(run, payload):
    # Fake archive results prove dispatch only; no template row was persisted.
    assert payload["agent_status"] == run.status == "blocked"
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_inconclusive"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert payload["verification_code"] == "result_template_receipt_unavailable"
    receipt = run.tool_calls[0].metadata["verification"]
    assert receipt["status"] == "inconclusive" and receipt["accepted"] is False
    assert receipt["code"] == "result_template_receipt_unavailable"
    assert receipt["checks"] and all(
        check["status"] == "unavailable" and not check["evidence"] for check in receipt["checks"]
    )
    assert run.tool_calls[0].output["success"] is True
    assert run.final_output.get("business_result", {}).get("success") is not True
    events = {event.event_type for event in run.events}
    assert {"tool.started", "verification.inconclusive"} <= events
    assert not {"tool.completed", "run.completed"} & events


def test_templates_create_route_executes_document_template_tool_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    actor = trusted_actor()
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.legacy.routes.document_templates_compat.run_archive_template_create",
            return_value=(
                {
                    "success": True,
                    "message": "模板创建成功",
                    "template": {"id": "db:1", "db_id": 1, "name": "发货模板"},
                },
                200,
            ),
        ) as create,
    ):
        response = _client().post(
            "/api/templates/create",
            json={"name": "发货模板", "template_type": "Excel"},
            headers={**actor.headers, "X-User-Id": "untrusted-client-actor"},
        )

    create.assert_called_once()
    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is False
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == "blocked"
    assert payload["template"]["id"] == "db:1"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == str(actor.user_id)
    _assert_mock_template_needs_readback(run, payload)
    assert run.intent == "document_template_create"
    assert run.steps[0].risk == "medium"
    assert run.steps[0].status == "completed"
    assert run.tool_calls[0].tool_id == "document_template"
    assert run.tool_calls[0].action == "create"
    assert run.tool_calls[0].permission == "tool.document_template.create"
    assert run.tool_calls[0].metadata["authorization_permission"] == "elt.template.manage"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= {
        event.event_type for event in run.events
    }


def test_templates_update_route_executes_document_template_tool_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    actor = trusted_actor()
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.legacy.routes.document_templates_compat.run_archive_template_update",
            return_value=(
                {
                    "success": True,
                    "message": "模板更新成功",
                    "template": {"id": "db:1", "db_id": 1, "name": "发货模板 v2"},
                },
                200,
            ),
        ) as update,
    ):
        response = _client().post(
            "/api/templates/update",
            json={"id": "db:1", "name": "发货模板 v2"},
            headers={**actor.headers, "X-User-Id": "untrusted-client-actor"},
        )

    update.assert_called_once()
    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is False
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == "blocked"
    assert payload["template"]["name"] == "发货模板 v2"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == str(actor.user_id)
    _assert_mock_template_needs_readback(run, payload)
    assert run.intent == "document_template_update"
    assert run.steps[0].risk == "medium"
    assert run.tool_calls[0].tool_id == "document_template"
    assert run.tool_calls[0].action == "update"
    assert run.tool_calls[0].permission == "tool.document_template.update"
    assert run.tool_calls[0].metadata["authorization_permission"] == "elt.template.manage"
    assert run.tool_calls[0].cost_units == 2


def test_templates_delete_route_executes_document_template_tool_through_agent(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    actor = trusted_actor()
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.legacy.routes.document_templates_compat.run_archive_template_delete",
            return_value=(
                {
                    "success": True,
                    "message": "模板删除成功",
                    "deleted": {"id": "db:1", "db_id": 1},
                },
                200,
            ),
        ) as delete,
    ):
        response = _client().request(
            "DELETE",
            "/api/templates/delete",
            json={"id": "db:1"},
            headers={**actor.headers, "X-User-Id": "untrusted-client-actor"},
        )

    delete.assert_called_once()
    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is False
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["agent_status"] == "blocked"
    assert payload["deleted"]["id"] == "db:1"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == str(actor.user_id)
    _assert_mock_template_needs_readback(run, payload)
    assert run.intent == "document_template_delete"
    assert run.steps[0].risk == "high"
    assert run.steps[0].status == "completed"
    assert run.tool_calls[0].tool_id == "document_template"
    assert run.tool_calls[0].action == "delete"
    assert run.tool_calls[0].permission == "tool.document_template.delete"
    assert run.tool_calls[0].metadata["authorization_permission"] == "elt.template.manage"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= {
        event.event_type for event in run.events
    }
