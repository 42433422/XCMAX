from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client(*, authenticated_user_id: int | None = None) -> TestClient:
    from app.fastapi_routes.tools_execute import router

    app = FastAPI()
    if authenticated_user_id is not None:

        @app.middleware("http")
        async def inject_authenticated_owner(request, call_next):
            request.state.user_id = authenticated_user_id
            return await call_next(request)

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_tools_execute_route_runs_registered_tool_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = True
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain),
    ):
        response = _client().post(
            "/api/tools/execute",
            json={
                "tool_id": "ocr",
                "action": "request",
                "params": {
                    "request_id": "tools-ocr-1",
                    "image_url": "https://example.invalid/label.png",
                    "ocr_type": "invoice",
                    "user_id": "tenant-a",
                },
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["event"] == "ocr.requested"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "tools_execute_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"
    assert run.tool_calls[0].permission == "tool.ocr.request"
    assert run.tool_calls[0].cost_units == 1


def test_skills_execute_route_runs_registered_skill_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    ocr_domain = Mock()
    ocr_domain.emit_ocr_requested.return_value = True
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch("app.neuro_bus.domains.ocr_domain.get_ocr_domain", return_value=ocr_domain),
    ):
        response = _client().post(
            "/api/skills/execute",
            json={
                "skill_id": "ocr",
                "action": "request",
                "params": {
                    "request_id": "skills-ocr-1",
                    "image_url": "https://example.invalid/label.png",
                    "ocr_type": "invoice",
                    "user_id": "tenant-a",
                },
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "completed"
    assert run.intent == "tools_execute_ocr_request"
    assert run.tool_calls[0].tool_id == "ocr"
    assert run.tool_calls[0].action == "request"


def test_tools_execute_route_puts_medium_risk_tool_behind_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = _client().post(
            "/api/tools/execute",
            json={
                "tool_id": "business_db",
                "action": "write",
                "params": {
                    "entity": "customers",
                    "operation": "create",
                    "payload": {"customer_name": "ACME Trading"},
                },
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_status"] == "waiting_user"
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.status == "waiting_user"
    assert run.tool_calls == []
    assert run.steps[0].tool_id == "business_db"
    assert run.steps[0].action == "write"
    assert run.steps[0].status == "waiting_user"


def test_tools_execute_route_uses_authenticated_owner_not_spoofed_header(
    tmp_path,
    monkeypatch,
) -> None:
    """Private template authority must come from request.state, not caller JSON."""

    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = _client(authenticated_user_id=42).post(
            "/api/tools/execute",
            json={
                "tool_id": "shipment_orders",
                "action": "generate",
                "params": {
                    "unit_name": "金汉武家私",
                    "products": [{"model": "9803", "quantity_tins": 3}],
                    "user_id": "999999",
                },
            },
            headers={"X-User-Id": "999999"},
        )

    assert response.status_code == 202
    payload = response.json()
    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "42"
    assert run.metadata["runtime_context"]["owner_user_id"] == 42
    assert run.metadata["runtime_context"]["user_id"] == "42"


def test_confirmed_legacy_shipment_preview_uses_authenticated_owner_and_completes() -> None:
    """The card's real legacy endpoint must not enter a waiting Agent run.

    ``shipment_generate`` remains a compatibility tool id.  Its document
    template owner is injected from middleware state, never from a spoofable
    header/body value, and the explicit card click completes synchronously.
    """

    with patch(
        "app.services.shipment_number_mode_service.ShipmentNumberModeService"
    ) as service_type:
        service_type.return_value.execute.return_value = (
            {
                "success": True,
                "message": "发货单已生成",
                "doc_name": "金汉武发货单.xlsx",
                "file_path": "/tmp/金汉武发货单.xlsx",
            },
            200,
        )
        response = _client(authenticated_user_id=42).post(
            "/api/tools/execute",
            json={
                "tool_id": "shipment_generate",
                "action": "执行",
                "params": {
                    "order_text": "打印金汉武发货单，黑棕面用修色精，规格28，3桶",
                    "unit_name": "金汉武",
                    "products": [
                        {
                            "name": "黑棕面用修色精",
                            "tin_spec": 28,
                            "quantity_tins": 3,
                        }
                    ],
                    "template_id": "etl:private-template",
                    "owner_user_id": 999999,
                },
            },
            headers={"X-User-Id": "999999"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "agent_run_id" not in payload
    assert "agent_status" not in payload

    execute_kwargs = service_type.return_value.execute.call_args.kwargs
    assert execute_kwargs["owner_user_id"] == 42
    assert execute_kwargs["template_id"] == "etl:private-template"
    assert execute_kwargs["direct_unit_name"] == "金汉武"
    assert execute_kwargs["direct_products"] == [
        {
            "name": "黑棕面用修色精",
            "tin_spec": 28,
            "quantity_tins": 3,
        }
    ]
