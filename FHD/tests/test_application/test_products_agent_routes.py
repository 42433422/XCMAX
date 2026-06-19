from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes.domains.product import compat_routes as product_compat_routes
from app.fastapi_routes.domains.product import routes as product_routes


def _client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(product_routes, "_svc", lambda: fake_service)
    app = FastAPI()
    app.include_router(product_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_product_run(
    repo: InMemoryAgentRunRepository,
    run_id: str,
    action: str,
    *,
    intent: str | None = None,
) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == (intent or f"products_{action}")
    assert run.tool_calls[0].tool_id == "products"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == f"tool.products.{action}"
    assert run.tool_calls[0].cost_units == 2
    assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
        event.event_type for event in run.events
    }


def test_product_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    repo = InMemoryAgentRunRepository()
    svc = MagicMock()
    svc.batch_add_products.return_value = {"success": True, "data": {"success_count": 1}}
    svc.update_product.return_value = {"success": True, "data": {"id": 7}}
    svc.delete_product.return_value = {"success": True, "message": "产品删除成功"}
    client = _client(svc, monkeypatch)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        batch_create = client.post(
            "/api/products/batch",
            json={"products": [{"name": "5003", "unit_price": 12.5}]},
            headers={"X-User-Id": "tenant-a"},
        )
        update_put = client.put(
            "/api/products/7",
            json={"name": "5003 v2"},
            headers={"X-User-Id": "tenant-a"},
        )
        update_patch = client.patch(
            "/api/products/7",
            json={"unit_price": 13.0},
            headers={"X-User-Id": "tenant-a"},
        )
        delete_product = client.delete(
            "/api/products/7",
            headers={"X-User-Id": "tenant-a"},
        )

    assert batch_create.status_code == 200
    assert update_put.status_code == 200
    assert update_patch.status_code == 200
    assert delete_product.status_code == 200

    svc.batch_add_products.assert_called_once_with([{"name": "5003", "unit_price": 12.5}])
    assert svc.update_product.call_args_list[0].args == (7, {"name": "5003 v2"})
    assert svc.update_product.call_args_list[1].args == (7, {"unit_price": 13.0})
    svc.delete_product.assert_called_once_with(7)

    _assert_product_run(repo, batch_create.json()["run_id"], "batch_create")
    _assert_product_run(repo, update_put.json()["run_id"], "update")
    _assert_product_run(repo, update_patch.json()["run_id"], "update")
    _assert_product_run(repo, delete_product.json()["run_id"], "delete")


def test_product_compat_mutation_routes_execute_through_agent_orchestrator(
    tmp_path,
    monkeypatch,
) -> None:
    import app.application.excel_imports as excel_imports

    repo = InMemoryAgentRunRepository()
    app = FastAPI()
    app.include_router(product_compat_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    excel_imports.__dict__["_parse_price"] = lambda value: 0.0

    try:
        with patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ), patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._products_write_raise"
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
            return_value=None,
        ), patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
            return_value=11,
        ) as insert_row, patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_update_row",
        ) as update_row, patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row",
        ) as delete_row, patch(
            "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
            return_value=(2, []),
        ) as batch_delete_rows:
            add_product = client.post(
                "/products/add",
                json={"product_name": "5003", "unit": "个"},
                headers={"X-User-Id": "tenant-a"},
            )
            update_product = client.post(
                "/products/update",
                json={"id": 11, "name": "5003 v2"},
                headers={"X-User-Id": "tenant-a"},
            )
            delete_product = client.post(
                "/products/delete",
                json={"id": 11},
                headers={"X-User-Id": "tenant-a"},
            )
            batch_delete = client.post(
                "/products/batch-delete",
                json={"ids": [11, 12]},
                headers={"X-User-Id": "tenant-a"},
            )
    finally:
        excel_imports.__dict__.pop("_parse_price", None)

    assert add_product.status_code == 200
    assert update_product.status_code == 200
    assert delete_product.status_code == 200
    assert batch_delete.status_code == 200
    assert add_product.json()["data"]["id"] == 11
    assert batch_delete.json()["deleted"] == 2

    insert_row.assert_called_once()
    update_row.assert_called_once()
    delete_row.assert_called_once_with(11)
    batch_delete_rows.assert_called_once_with([11, 12])

    _assert_product_run(
        repo,
        add_product.json()["run_id"],
        "create",
        intent="products_create_compat",
    )
    _assert_product_run(
        repo,
        update_product.json()["run_id"],
        "update",
        intent="products_update_compat",
    )
    _assert_product_run(
        repo,
        delete_product.json()["run_id"],
        "delete",
        intent="products_delete_compat",
    )
    _assert_product_run(
        repo,
        batch_delete.json()["run_id"],
        "batch_delete",
        intent="products_batch_delete_compat",
    )
