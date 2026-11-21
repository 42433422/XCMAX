from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import shipment_orders
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_approval_route_does_not_report_failed_execution_as_success(monkeypatch):
    from app.fastapi_routes.domains.shipment import shipment_routes

    plan = SimpleNamespace(plan_id="p", intent="test", nodes=[object()])
    approvals = MagicMock()
    approvals.get_pending_workflow.return_value = {"plan": plan, "runtime_context": {}}
    resume = {"success": False, "workflow_executed": False, "code": "workflow_plan_unavailable"}
    monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approvals)
    monkeypatch.setattr(
        "app.application.approval_workspace_app_service._pending_snapshot", lambda _: None
    )
    monkeypatch.setattr(
        "app.application.approval_workspace_app_service._resume_pending_ai_workflow_after_approval",
        lambda **_: resume,
    )
    monkeypatch.setattr(shipment_routes, "_owned_request_id", lambda *_args: "req")
    monkeypatch.setattr(
        shipment_routes, "_trace_approval_route", lambda payload, **_kwargs: payload
    )
    result = shipment_routes.ai_approval_approve({"request_id": "req"}, user=object())
    assert result["success"] is False
    assert result["data"]["workflow_executed"] is False
    approvals.approve.assert_not_called()


def test_approval_route_missing_plan_does_not_claim_execution(monkeypatch):
    from app.fastapi_routes.domains.shipment import shipment_routes

    approvals = MagicMock()
    approvals.get_pending_workflow.return_value = {"plan": None}
    monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approvals)
    monkeypatch.setattr(
        "app.application.approval_workspace_app_service._pending_snapshot", lambda _: None
    )
    monkeypatch.setattr(
        "app.application.approval_workspace_app_service._resume_pending_ai_workflow_after_approval",
        lambda **_: {
            "success": False,
            "workflow_executed": False,
            "code": "agent_run_unavailable",
        },
    )
    monkeypatch.setattr(shipment_routes, "_owned_request_id", lambda *_args: "req")
    monkeypatch.setattr(
        shipment_routes, "_trace_approval_route", lambda payload, **_kwargs: payload
    )
    result = shipment_routes.ai_approval_approve({"request_id": "req"}, user=object())
    assert result["success"] is False
    assert result["data"]["workflow_executed"] is False


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch, actor) -> TestClient:
    monkeypatch.setattr(shipment_orders, "_svc", lambda: fake_service)
    app = FastAPI()
    app.include_router(shipment_orders.router)
    return TestClient(app, raise_server_exceptions=False, headers=actor.headers)


@pytest.mark.parametrize(
    "method,path,body,action",
    [
        (
            "POST",
            "/api/shipment/generate",
            {"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]},
            "generate",
        ),
        (
            "POST",
            "/api/shipment/generate-batch",
            {"shipments": [{"unit_name": "星光贸易", "products": [{"name": "5003", "qty": 2}]}]},
            "generate_batch",
        ),
        (
            "POST",
            "/api/shipment/print",
            {"file_path": "fixture", "order_id": 7, "printer_name": "HP"},
            "print",
        ),
        (
            "POST",
            "/api/shipment/orders/clear-shipment",
            {"purchase_unit": "星光贸易"},
            "clear_shipment",
        ),
        ("POST", "/api/orders/set-sequence", {"sequence": 12}, "set_sequence"),
        ("POST", "/api/shipment/orders/reset-sequence", {}, "reset_sequence"),
        ("DELETE", "/api/orders/clear-all", None, "clear_all"),
        ("DELETE", "/api/shipment/orders/7", None, "delete"),
    ],
)
def test_shipment_global_routes_fail_closed_without_approval_scope(
    tmp_path, monkeypatch, local_tools, trusted_actor, method, path, body, action
):
    repo = InMemoryAgentRunRepository()
    actor = trusted_actor(user_id=17, tenant_id=None, role="admin", tier="admin")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    from app.infrastructure.tenant_scope import tenant_scope
    from app.utils.path_io.path_utils import get_shipment_output_dir

    with tenant_scope(None):
        shipment_outputs = Path(get_shipment_output_dir())
    shipment_outputs.mkdir(parents=True)
    shipment_file = shipment_outputs / "shipment.xlsx"
    from openpyxl import Workbook

    Workbook().save(shipment_file)
    if action == "print":
        body = {**body, "file_path": str(shipment_file)}
    service = MagicMock()
    client = _client(service, monkeypatch, actor)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    from app.infrastructure.tenant_scope import tenant_scope

    with (
        tenant_scope(None),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        response = client.request(
            method,
            path,
            json=body,
            headers={"X-User-Id": "999", "Idempotency-Key": "shipment-command"},
        )
        assert response.status_code == 403, response.text
        receipt = response.json()
        assert receipt["success"] is False and receipt["error_code"] == "approval_scope_required"
        assert receipt["execution_status"] == "not_started"
        assert not receipt.get("run_id")
    assert service.mock_calls == []
