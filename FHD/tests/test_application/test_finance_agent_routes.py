from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import finance as finance_routes
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(finance_routes, "_svc", lambda: fake_service)
    monkeypatch.setattr(
        "app.application.finance_app_service.FinanceAppService", lambda: fake_service
    )
    app = FastAPI()
    app.include_router(finance_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_finance_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "17"
    # Dispatch-only service mocks do not provide an independent transaction receipt.
    assert run.status == "blocked"
    assert run.intent == f"ERP Agent 请求执行 finance.{action}"
    (call,) = run.tool_calls
    assert call.tool_id == "finance"
    assert call.action == action
    assert call.permission == f"tool.finance.{action}"
    assert call.cost_units == 2
    assert call.output["success"] is True
    report = call.metadata["verification"]
    assert report["accepted"] is False
    assert report["code"] == "result_source_unavailable"
    events = {event.event_type for event in run.events}
    assert {"step.waiting_user", "step.approved", "verification.inconclusive"} <= events
    assert not {"tool.completed", "run.completed"} & events


def test_finance_transaction_mutation_routes_execute_through_agent_orchestrator(
    tmp_path, monkeypatch, local_tools, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_transaction.return_value = {
        "success": True,
        "data": {"id": 31, "transaction_type": "expense"},
    }
    svc.update_transaction.return_value = {"success": True, "data": {"id": 31}}
    svc.delete_transaction.return_value = {"success": True, "message": "凭证已删除"}
    actor = trusted_actor(user_id=17, role="admin")
    client = ApprovedCapabilityClient(_client(svc, monkeypatch), repo, actor)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        create_txn = client.post(
            "/api/finance/transactions",
            json={
                "transaction_type": "expense",
                "amount": 128.5,
                "description": "运费",
            },
            headers={"X-User-Id": "tenant-a"},
        )
        update_txn = client.put(
            "/api/finance/transactions/31",
            json={"status": "paid"},
            headers={"X-User-Id": "tenant-a"},
        )
        delete_txn = client.delete(
            "/api/finance/transactions/31",
            headers={"X-User-Id": "tenant-a"},
        )

    assert create_txn.status_code == 202
    assert update_txn.status_code == 202
    assert delete_txn.status_code == 202

    svc.create_transaction.assert_called_once_with(
        {"transaction_type": "expense", "amount": 128.5, "description": "运费"}
    )
    svc.update_transaction.assert_called_once_with(31, {"status": "paid"})
    svc.delete_transaction.assert_called_once_with(31)

    _assert_finance_run(repo, create_txn.json()["run_id"], "create_transaction")
    _assert_finance_run(repo, update_txn.json()["run_id"], "update_transaction")
    _assert_finance_run(repo, delete_txn.json()["run_id"], "delete_transaction")
