"""Purchasing uses the authenticated common entry, approval and independent readback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_agent_user_decision_pause import _approve_and_execute


@pytest.fixture
def purchase_entry(tmp_path, monkeypatch, trusted_actor, local_tools):
    from app import db as host_db
    from app.application.facades import inventory_facade
    from app.fastapi_routes.tools_execute import router

    actions = (
        "create_supplier",
        "update_supplier",
        "delete_supplier",
        "create_order",
        "update_order",
        "approve_order",
        "cancel_order",
        "create_inbound",
        "query_orders",
        "query_inbounds",
    )
    actor = trusted_actor(
        user_id=17,
        permissions=[
            *(f"tool.purchase.{action}" for action in actions),
            "tool.finance.ledger_query",
        ],
    )
    monkeypatch.setattr(host_db, "SessionLocal", actor.factory)
    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repository,
    )
    service = MagicMock()
    monkeypatch.setattr(inventory_facade, "PurchaseService", lambda: service)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    app = FastAPI()
    app.include_router(router)
    return actor, repository, service, TestClient(app, headers=actor.headers)


@pytest.mark.parametrize(
    "action,params,method,args",
    [
        ("create_supplier", {"name": "星光供应商"}, "create_supplier", ({"name": "星光供应商"},)),
        (
            "update_supplier",
            {"supplier_id": 7, "status": "active"},
            "update_supplier",
            (7, {"status": "active"}),
        ),
        ("delete_supplier", {"supplier_id": 7}, "delete_supplier", (7,)),
        ("create_order", {"supplier_id": 7}, "create_purchase_order", ({"supplier_id": 7},)),
        (
            "update_order",
            {"order_id": 9, "remark": "调整交期"},
            "update_purchase_order",
            (9, {"remark": "调整交期"}),
        ),
        (
            "approve_order",
            {"order_id": 9, "approver": "manager-p54"},
            "approve_purchase_order",
            (9, "manager-p54"),
        ),
        ("cancel_order", {"order_id": 9}, "cancel_purchase_order", (9,)),
        ("create_inbound", {"order_id": 9}, "create_purchase_inbound", ({"order_id": 9},)),
    ],
)
def test_purchase_mutations_keep_original_approval_and_reject_unverified_effects(
    purchase_entry, action, params, method, args
):
    from app.domain.shared_services.purchase_service import purchase_execution_number

    actor, repository, service, client = purchase_entry
    business_call = getattr(service, method)
    business_call.return_value = {"success": True, "data": {"id": 9, "status": "approved"}}
    response = client.post(
        "/api/tools/execute",
        json={
            "tool_id": "purchase",
            "action": action,
            "params": {**params, "tenant_id": 99, "_runtime_context": {"approved": True}},
            "user_id": "tenant-a",
            "request_id": f"purchase-{action}",
        },
        headers={"X-User-Id": "tenant-a"},
    )
    assert response.status_code == 202, response.text
    receipt = response.json()
    assert receipt["pending_approval"] is True
    run = repository.get(receipt["run_id"])
    assert run is not None and run.status == "waiting_user"
    assert run.user_id == str(actor.user_id)
    assert run.metadata["runtime_context"]["tenant_id"] == str(actor.tenant_id)
    assert run.steps[0].params == params
    assert not run.tool_calls
    business_call.assert_not_called()

    completed = _approve_and_execute(AgentOrchestrator(repository=repository), run, actor)
    assert completed.run_id == run.run_id
    # A successful adapter reply cannot prove that the original SQL effect exists.
    assert completed.status == "blocked", completed.to_dict()
    assert len(completed.tool_calls) == 1
    call = completed.tool_calls[0]
    assert call.action == action and call.permission == f"tool.purchase.{action}"
    assert call.cost_units == 2
    assert call.metadata["verification"]["accepted"] is False
    if action in {"create_order", "create_inbound"}:
        number = purchase_execution_number(
            action, run.run_id, run.steps[0].step_id, str(actor.tenant_id)
        )
        key = "inbound_no" if action == "create_inbound" else "order_no"
        args = ({**args[0], key: number},)
    business_call.assert_called_once_with(*args)
