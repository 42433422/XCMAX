from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(actor) -> TestClient:
    from app.fastapi_routes.ocr import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers=actor.headers)


def test_ocr_recognize_route_executes_through_agent_orchestrator(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    actor = trusted_actor(user_id=7, role="admin")
    repo = InMemoryAgentRunRepository()
    ocr_service = Mock()
    ocr_service.recognize_file.return_value = {
        "success": True,
        "message": "识别成功",
        "text": "购货单位：ACME Trading",
        "file_path": "/tmp/label.png",
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
        patch("app.fastapi_routes.ocr._get_ocr_service", return_value=ocr_service),
    ):
        response = _client(actor).post(
            "/api/ocr/recognize",
            data={"file_path": "/tmp/label.png"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["text"] == "购货单位：ACME Trading"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "7"
    assert run.status == "completed"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "recognize"
    assert run.tool_calls[0].permission == "tool.ocr.recognize"
    assert run.tool_calls[0].cost_units == 1
    assert run.artifacts[0].artifact_type == "ocr_text"
    assert run.metadata["artifact_count"] == 1


def test_ocr_analyze_route_executes_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
    trusted_actor,
) -> None:
    actor = trusted_actor(user_id=7, role="admin")
    repo = InMemoryAgentRunRepository()
    ocr_service = Mock()
    ocr_service.analyze_text.return_value = {
        "text_type": "order",
        "confidence": 0.67,
        "detected_fields": {"purchase_unit": True},
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
        patch("app.fastapi_routes.ocr._get_ocr_service", return_value=ocr_service),
    ):
        response = _client(actor).post(
            "/api/ocr/analyze",
            json={"text": "订单编号：SO-1\n购货单位：ACME Trading"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["text_type"] == "order"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "analyze"
    assert run.tool_calls[0].permission == "tool.ocr.analyze"
    assert run.tool_calls[0].cost_units == 1
