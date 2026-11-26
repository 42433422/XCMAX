from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import inventory as inventory_routes
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch, actor=None) -> TestClient:
    monkeypatch.setattr(inventory_routes, "_svc", lambda: fake_service)
    monkeypatch.setattr(
        "app.application.inventory_app_service.InventoryAppService",
        lambda: fake_service,
    )
    app = FastAPI()
    app.state.actor = actor
    app.include_router(inventory_routes.router)
    return TestClient(
        app,
        raise_server_exceptions=False,
        headers=actor.headers if actor is not None else {},
    )


def _assert_inventory_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None and run.user_id == "17"
    assert run.status == "blocked"
    assert run.intent == f"ERP Agent 请求执行 inventory.{action}"
    assert run.metadata["runtime_context"]["tenant_id"] == "7"
    assert run.metadata["runtime_context"]["_actor_authorization"]
    assert run.tool_calls[0].tool_id == "inventory"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.inventory.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert len(run.tool_calls) == 1 and run.steps[0].attempt_count == 1
    assert run.tool_calls[0].output["success"] is True
    report = run.tool_calls[0].metadata["verification"]
    assert report["accepted"] is False and report["status"] == "inconclusive"
    assert report["code"] == (
        "result_inventory_identity_missing"
        if action in {"stock_in", "stock_out"}
        else "result_verifier_unavailable"
    )
    assert all(check["status"] != "passed" for check in report["checks"])
    events = {event.event_type for event in run.events}
    assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= events
    assert not {"tool.completed", "run.completed"} & events


def _assert_unverified_payload(response) -> None:
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "result_verification_required"
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    assert payload["outcome"] == "unknown"


@pytest.mark.parametrize(
    "action,method,path,payload,expected,result",
    [
        (
            "create_storage_location",
            "POST",
            "/locations",
            {"code": "A-01"},
            ({"code": "A-01"},),
            {"success": True, "id": 11},
        ),
        (
            "update_storage_location",
            "PUT",
            "/locations/10",
            {"status": "full"},
            (10, {"status": "full"}),
            {"success": True, "data": {"id": 10}},
        ),
        (
            "create_warehouse",
            "POST",
            "/warehouses",
            {"name": "主仓"},
            ({"name": "主仓"},),
            {"success": True, "data": {"id": 3}},
        ),
        (
            "update_warehouse",
            "PUT",
            "/warehouses/3",
            {"name": "副仓"},
            (3, {"name": "副仓"}),
            {"success": True, "data": {"id": 3}},
        ),
        ("delete_warehouse", "DELETE", "/warehouses/3", None, (3,), {"success": True}),
    ],
)
def test_inventory_structure_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
    action,
    method,
    path,
    payload,
    expected,
    result,
    local_tools,
    trusted_actor,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    getattr(svc, action).return_value = result
    client = _client(
        svc,
        monkeypatch,
        trusted_actor(user_id=17, permissions=[f"tool.inventory.{action}"]),
    )
    client = ApprovedCapabilityClient(client, repo, client.app.state.actor)
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = client.request(
            method,
            "/api/inventory" + path,
            json=payload,
            headers={"X-User-Id": "tenant-a"},
        )
    _assert_unverified_payload(response)
    getattr(svc, action).assert_called_once_with(*expected)
    _assert_inventory_run(repo, response.json()["run_id"], action)


def test_inventory_stock_mutation_routes_execute_through_agent_orchestrator(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.inventory_in.return_value = {"success": True}
    svc.inventory_out.return_value = {"success": True}
    svc.inventory_transfer.return_value = {"success": True}
    client = _client(
        svc,
        monkeypatch,
        trusted_actor(
            user_id=17,
            permissions=[
                "tool.inventory.stock_in",
                "tool.inventory.stock_out",
                "tool.inventory.transfer",
                "tool.inventory.query_transactions",
            ],
        ),
    )
    client = ApprovedCapabilityClient(client, repo, client.app.state.actor)
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        stock_in = client.post(
            "/api/inventory/in",
            json={"product_id": 1, "warehouse_id": 2, "quantity": 3},
            headers={"X-User-Id": "tenant-a"},
        )
        stock_out = client.post(
            "/api/inventory/out",
            json={"product_id": 1, "warehouse_id": 2, "quantity": 1, "unit_price": 5},
            headers={"X-User-Id": "tenant-a"},
        )
        transfer = client.post(
            "/api/inventory/transfer",
            json={
                "product_id": 1,
                "from_warehouse_id": 2,
                "to_warehouse_id": 3,
                "quantity": 1,
            },
            headers={"X-User-Id": "tenant-a"},
        )

    for response in (stock_in, stock_out, transfer):
        _assert_unverified_payload(response)
    svc.inventory_in.assert_called_once()
    svc.inventory_out.assert_called_once()
    svc.inventory_transfer.assert_called_once()

    assert svc.inventory_in.call_args.kwargs["unit_price"] is None
    assert svc.inventory_in.call_args.kwargs["quantity"] == 3.0
    assert "unit_price" not in svc.inventory_out.call_args.kwargs
    assert svc.inventory_transfer.call_args.kwargs["from_warehouse_id"] == 2
    assert svc.inventory_transfer.call_args.kwargs["quantity"] == 1.0

    _assert_inventory_run(repo, stock_in.json()["run_id"], "stock_in")
    _assert_inventory_run(repo, stock_out.json()["run_id"], "stock_out")
    _assert_inventory_run(repo, transfer.json()["run_id"], "transfer")


@pytest.mark.parametrize("authenticated", [False, True])
def test_inventory_mutation_rejects_missing_session_or_permission(
    authenticated, monkeypatch, trusted_actor, local_tools
) -> None:
    svc = MagicMock()
    actor = (
        trusted_actor(user_id=17, permissions=["tool.inventory.query_transactions"])
        if authenticated
        else None
    )
    client = _client(svc, monkeypatch, actor)
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    repo = InMemoryAgentRunRepository()
    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = client.post(
            "/api/inventory/in",
            json={"product_id": 1, "warehouse_id": 2, "quantity": 3, "user_id": 17},
            headers={"X-User-Id": "17"},
        )
    svc.inventory_in.assert_not_called()
    if not authenticated:
        assert response.status_code == 401
    else:
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "tool_permission_denied"
        assert not response.json().get("run_id")
