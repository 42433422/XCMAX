from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(actor) -> TestClient:
    from app.fastapi_routes.excel_vector import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers=actor.headers, raise_server_exceptions=False)


def test_excel_vector_ingest_rejects_missing_approval_owner(
    tmp_path, monkeypatch, trusted_actor
) -> None:
    actor = trusted_actor(user_id=7, role="admin", tenant_id=None, tier="admin")
    ingest_service = Mock()
    with (
        tenant_scope(None),
        patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=ingest_service,
        ),
    ):
        response = _client(actor).post(
            "/api/excel/vector/ingest",
            json={"file_path": "/tmp/products.xlsx", "index_name": "products"},
            headers={"Idempotency-Key": "vector-ingest-1"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["error_code"] == "approval_scope_required"
    assert response.json()["execution_status"] == "not_started"
    assert ingest_service.mock_calls == []


def test_excel_vector_query_route_executes_through_agent_orchestrator(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    actor = trusted_actor(user_id=7, role="admin", tenant_id=None, tier="admin")
    repo = InMemoryAgentRunRepository()
    search_service = Mock()
    search_service.query.return_value = {
        "success": True,
        "index_id": "idx-agent",
        "query": "5003",
        "hits": [{"score": 0.91, "row": {"model_number": "5003"}}],
    }
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        tenant_scope(None),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=search_service,
        ),
    ):
        response = _client(actor).post(
            "/api/excel/vector/query",
            json={"index_id": "idx-agent", "query": "5003", "top_k": 3},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["hits"][0]["row"]["model_number"] == "5003"
    assert payload["agent_run_id"] == payload["run_id"]
    search_service.query.assert_called_once_with(index_id="idx-agent", query_text="5003", top_k=3)

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.tool_calls[0].tool_id == "excel_vector_index"
    assert run.tool_calls[0].action == "query"
    assert run.tool_calls[0].permission == "tool.excel_vector_index.query"
    assert run.tool_calls[0].cost_units == 1
