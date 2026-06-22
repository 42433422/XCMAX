from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import finance as finance_routes


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(finance_routes, "_svc", lambda: fake_service)
    app = FastAPI()
    app.include_router(finance_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_finance_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"finance_{action}"
    assert run.tool_calls[0].tool_id == "finance"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.finance.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_finance_transaction_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.create_transaction.return_value = {
        "success": True,
        "data": {"id": 31, "transaction_type": "expense"},
    }
    svc.update_transaction.return_value = {"success": True, "data": {"id": 31}}
    svc.delete_transaction.return_value = {"success": True, "message": "凭证已删除"}
    client = _client(svc, monkeypatch)

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

    assert create_txn.status_code == 200
    assert update_txn.status_code == 200
    assert delete_txn.status_code == 200

    svc.create_transaction.assert_called_once_with(
        {"transaction_type": "expense", "amount": 128.5, "description": "运费"}
    )
    svc.update_transaction.assert_called_once_with(31, {"status": "paid"})
    svc.delete_transaction.assert_called_once_with(31)

    _assert_finance_run(repo, create_txn.json()["run_id"], "create_transaction")
    _assert_finance_run(repo, update_txn.json()["run_id"], "update_transaction")
    _assert_finance_run(repo, delete_txn.json()["run_id"], "delete_transaction")
