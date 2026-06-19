from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.excel_vector import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_excel_vector_ingest_route_executes_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    from app.application.dataset_rag_app_service import reset_dataset_rag_app_service_for_tests

    repo = InMemoryAgentRunRepository()
    ingest_service = Mock()
    ingest_service.ingest_excel.return_value = {
        "success": True,
        "index_id": "idx-agent",
        "chunk_count": 2,
        "row_count": 8,
    }
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    reset_dataset_rag_app_service_for_tests()

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_ingest_app_service",
            return_value=ingest_service,
        ),
    ):
        response = _client().post(
            "/api/excel/vector/ingest",
            json={"file_path": "/tmp/products.xlsx", "index_name": "products"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["index_id"] == "idx-agent"
    assert payload["excel_vector_index_id"] == "idx-agent"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "excel_vector_execute"
    assert run.tool_calls[0].tool_id == "excel_vector_index"
    assert run.tool_calls[0].action == "execute"
    assert run.tool_calls[0].permission == "tool.excel_vector_index.execute"
    assert run.tool_calls[0].cost_units == 1


def test_excel_vector_query_route_executes_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
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
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.fastapi_routes.excel_vector.get_excel_vector_search_app_service",
            return_value=search_service,
        ),
    ):
        response = _client().post(
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
    assert run.intent == "excel_vector_query"
    assert run.tool_calls[0].tool_id == "excel_vector_index"
    assert run.tool_calls[0].action == "query"
    assert run.tool_calls[0].permission == "tool.excel_vector_index.query"
    assert run.tool_calls[0].cost_units == 1
