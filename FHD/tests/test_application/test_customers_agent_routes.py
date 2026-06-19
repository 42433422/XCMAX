from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes.domains.customer import routes as customer_routes


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(customer_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_customer_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == f"customers_{action}"
    assert run.tool_calls[0].tool_id == "customers"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.customers.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_customer_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    client = _client()

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    deleted_ids: list[int] = []

    def _delete_customer(customer_id: int) -> None:
        deleted_ids.append(customer_id)

    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=False,
        ),
        patch.object(customer_routes, "_customers_write_raise"),
        patch.object(
            customer_routes,
            "_customer_body_name_contact",
            side_effect=[
                ("星光贸易", "张三", "13900000000", "上海"),
                ("星光贸易二部", "李四", "13800000000", "杭州"),
            ],
        ),
        patch.object(
            customer_routes,
            "_customer_pg_insert",
            return_value={"id": 7, "unit_name": "星光贸易"},
        ) as insert_customer,
        patch.object(
            customer_routes,
            "_customer_pg_update",
            return_value={"id": 7, "unit_name": "星光贸易二部"},
        ) as update_customer,
        patch.object(customer_routes, "_customer_delete_unified", side_effect=_delete_customer),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        create_customer = client.post(
            "/customers",
            json={"unit_name": "星光贸易"},
            headers={"X-User-Id": "tenant-a"},
        )
        update_customer_resp = client.put(
            "/customers/7",
            json={"unit_name": "星光贸易二部"},
            headers={"X-User-Id": "tenant-a"},
        )
        delete_customer = client.delete("/customers/7", headers={"X-User-Id": "tenant-a"})
        batch_delete = client.post(
            "/customers/batch-delete",
            json={"ids": [7, "bad", 8]},
            headers={"X-User-Id": "tenant-a"},
        )

    assert create_customer.status_code == 200
    assert update_customer_resp.status_code == 200
    assert delete_customer.status_code == 200
    assert batch_delete.status_code == 200

    insert_customer.assert_called_once_with("星光贸易", "张三", "13900000000", "上海")
    update_customer.assert_called_once_with(7, "星光贸易二部", "李四", "13800000000", "杭州")
    assert deleted_ids == [7, 7, 8]

    assert create_customer.json()["data"]["unit_name"] == "星光贸易"
    assert update_customer_resp.json()["data"]["unit_name"] == "星光贸易二部"
    assert delete_customer.json()["message"] == "已删除"
    assert batch_delete.json()["deleted"] == 2
    assert "bad" in batch_delete.json()["skipped"]

    _assert_customer_run(repo, create_customer.json()["run_id"], "create")
    _assert_customer_run(repo, update_customer_resp.json()["run_id"], "update")
    _assert_customer_run(repo, delete_customer.json()["run_id"], "delete")
    _assert_customer_run(repo, batch_delete.json()["run_id"], "batch_delete")
