from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.db.models.purchase_unit import PurchaseUnit
from app.fastapi_routes.domains.customer import routes as customer_routes
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_customer_cascade_authority import deletion as deletion
from tests.test_application.test_customer_cascade_authority import snapshot


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(customer_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def customer_sessions(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'customers.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    PurchaseUnit.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", factory)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    try:
        yield factory
    finally:
        engine.dispose()


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
    customer_sessions, local_tools
) -> None:
    repo = InMemoryAgentRunRepository()
    client = _client()

    def _insert_customer(name: str, contact: str, phone: str, address: str) -> dict:
        with customer_sessions.begin() as db:
            row = PurchaseUnit(
                id=7,
                tenant_id=7,
                unit_name=name,
                contact_person=contact,
                contact_phone=phone,
                address=address,
            )
            db.add(row)
            db.flush()
            return {"id": row.id, "unit_name": row.unit_name}

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
            side_effect=_insert_customer,
        ) as insert_customer,
        patch.object(
            customer_routes,
            "_customer_pg_update",
            return_value={"id": 7, "unit_name": "星光贸易二部"},
        ) as update_customer,
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

    assert create_customer.status_code == 200
    assert update_customer_resp.status_code == 200

    insert_customer.assert_called_once_with("星光贸易", "张三", "13900000000", "上海")
    update_customer.assert_called_once_with(7, "星光贸易二部", "李四", "13800000000", "杭州")

    assert create_customer.json()["data"]["unit_name"] == "星光贸易"
    assert update_customer_resp.json()["data"]["unit_name"] == "星光贸易二部"
    _assert_customer_run(repo, create_customer.json()["run_id"], "create")
    _assert_customer_run(repo, update_customer_resp.json()["run_id"], "update")


def test_customer_create_route_requires_a_persisted_row(customer_sessions, local_tools) -> None:
    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=False,
        ),
        patch.object(customer_routes, "_customers_write_raise"),
        patch.object(
            customer_routes,
            "_customer_body_name_contact",
            return_value=("未落库客户", "张三", "13900000000", "上海"),
        ),
        patch.object(
            customer_routes,
            "_customer_pg_insert",
            return_value={"id": 7, "unit_name": "未落库客户"},
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        response = _client().post(
            "/customers", json={"unit_name": "未落库客户"}, headers={"X-User-Id": "tenant-a"}
        )
    assert response.status_code == 200
    output = response.json()
    assert output["success"] is False
    assert output["error_code"] == "customer_receipt_unverified"
    assert output["reconciliation_required"] is True
    assert output["retryable"] is False
    run = repo.get(output["run_id"])
    assert run is not None and run.status == "blocked"
    assert "run.completed" not in {event.event_type for event in run.events}
    with customer_sessions() as db:
        assert (
            db.scalars(select(PurchaseUnit.id).execution_options(skip_tenant_filter=True)).all()
            == []
        )


@pytest.mark.parametrize("action,ids", [("delete", [3]), ("batch_delete", [3, 4])])
def test_customer_delete_routes_use_real_scoped_service_and_signed_approval(
    deletion, monkeypatch, local_tools, action, ids
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.infrastructure.tenant_scope import tenant_scope

    _, actor, _ = deletion
    with tenant_scope(7), actor.factory.begin() as db:
        db.add(PurchaseUnit(id=4, tenant_id=7, unit_name="Empty second"))
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    before = snapshot(actor)
    monkeypatch.setattr(
        "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled", lambda: False
    )
    with _client() as client:
        if action == "delete":
            response = client.delete("/customers/3", headers={**actor.headers, "X-User-ID": "999"})
        else:
            response = client.post(
                "/customers/batch-delete", json={"ids": ids}, headers=actor.headers
            )
    assert response.status_code == 200, response.text
    run = repo.get(response.json()["run_id"])
    assert run.user_id == str(actor.user_id)
    done = run
    if run.status == "waiting_user":
        assert snapshot(actor) == before
        issue_approval_grant(run, principal_id=str(actor.user_id))
        with tenant_scope(7):
            done = AgentOrchestrator(repository=repo).continue_run(
                run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
            )
    assert done.status == "completed", done.error
    assert done.metadata["approval_receipt"]["approved_by"] == str(actor.user_id)
    assert done.tool_calls[0].permission == "customer.edit"
    assert done.tool_calls[0].output["deleted_count"] == len(ids)
    assert {"step.approved", "tool.completed", "run.completed"} <= {
        e.event_type for e in done.events
    }
    assert all((value,) not in snapshot(actor)[0] for value in ids)
    assert snapshot(actor)[1:] == before[1:]
    assert (103,) in snapshot(actor)[0]


def test_customer_batch_route_rejects_invalid_ids_without_partial_effect(deletion, local_tools):
    _, actor, _ = deletion
    before = snapshot(actor)
    with _client() as client:
        response = client.post(
            "/customers/batch-delete", json={"ids": [3, "bad", 4]}, headers=actor.headers
        )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert snapshot(actor) == before
