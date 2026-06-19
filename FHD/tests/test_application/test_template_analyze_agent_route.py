from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.domains.system.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_templates_analyze_route_executes_template_extract_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.services.document_templates_service._extract_structured_excel_preview",
            return_value={
                "fields": [{"label": "客户", "type": "dynamic"}],
                "sample_rows": [{"客户": "ACME Trading"}],
            },
        ),
        patch(
            "app.services.document_templates_service._extract_excel_grid_preview",
            return_value={"rows": [["客户"], ["ACME Trading"]]},
        ),
        patch(
            "app.services.document_templates_service._extract_excel_grid_style_cache",
            return_value={"cells": {}},
        ),
        patch(
            "app.services.document_templates_service._extract_excel_all_sheets_preview",
            return_value=[{"sheet_name": "出货"}],
        ),
        patch(
            "app.services.document_templates_service._list_excel_sheet_names",
            return_value=["出货"],
        ),
    ):
        response = _client().post(
            "/api/templates/analyze",
            files={
                "file": (
                    "shipment-template.xlsx",
                    b"not-real-xlsx-but-route-saves-it",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            data={"template_name": "发货模板", "template_scope": "shipment"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["fields"][0]["label"] == "客户"
    assert payload["artifacts"][0]["artifact_type"] == "template_analysis"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "templates_analyze"
    assert run.tool_calls[0].tool_id == "template_extract"
    assert run.tool_calls[0].action == "extract"
    assert run.tool_calls[0].permission == "tool.template_extract.extract"
    assert run.tool_calls[0].cost_units == 1
    assert {artifact.artifact_type for artifact in run.artifacts} >= {
        "excel_file",
        "template_analysis",
    }
