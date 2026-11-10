"""Cross-domain deletion requires a live signed actor and one atomic transaction."""

import copy

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.application.customer_app_service import CustomerApplicationService
from app.db.models.product import Product
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.shipment import ShipmentRecord
from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def deletion(trusted_actor, monkeypatch):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    weak = trusted_actor(
        tenant_id=7, role="customers-only", permissions=["customer.edit", "tool.customers.delete"]
    )
    full = trusted_actor(
        tenant_id=7,
        role="cascade-owner",
        permissions=["customer.edit", "product.edit", "shipment.edit", "tool.customers.delete"],
    )
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", full.factory)
    monkeypatch.setattr(
        "app.infrastructure.persistence.compat_db.compat_db_base.get_sync_engine",
        lambda: full.factory.kw["bind"],
    )
    for tenant, offset in ((7, 0), (8, 100)):
        with tenant_scope(tenant), full.factory.begin() as db:
            db.add_all(
                [
                    PurchaseUnit(id=1 + offset, unit_name="Same", tenant_id=tenant),
                    PurchaseUnit(id=2 + offset, unit_name="Similar", tenant_id=tenant),
                    PurchaseUnit(id=3 + offset, unit_name="Empty", tenant_id=tenant),
                ]
            )
            db.add_all(
                [
                    Product(id=1 + offset, name="P", unit="Same", tenant_id=tenant),
                    Product(id=2 + offset, name="Q", unit="Similar", tenant_id=tenant),
                ]
            )
            db.add_all(
                [
                    ShipmentRecord(
                        id=1 + offset,
                        unit_id=1 + offset,
                        purchase_unit="Same",
                        tenant_id=tenant,
                        product_name="Shipment",
                        quantity_kg=1,
                        quantity_tins=1,
                    ),
                    ShipmentRecord(
                        id=2 + offset,
                        unit_id=2 + offset,
                        purchase_unit="Same",
                        tenant_id=tenant,
                        product_name="Shipment",
                        quantity_kg=1,
                        quantity_tins=1,
                    ),
                ]
            )
            db.add(
                ShipmentEtlImportFingerprint(
                    tenant_key=f"tenant:{tenant}", fingerprint="one", shipment_id=1 + offset
                )
            )
    return weak, full, CustomerApplicationService()


def snapshot(actor):
    with actor.factory() as db:
        return [
            db.connection().exec_driver_sql(f"select id from {table} order by id").fetchall()
            for table in (
                "purchase_units",
                "products",
                "shipment_records",
                "shipment_etl_import_fingerprints",
            )
        ]


def test_force_requires_live_cross_domain_authority_and_ignores_client_context(deletion):
    from app.domain.shared_services.tools_workflow_erp import _registered_router_customers

    weak, full, service = deletion
    before = snapshot(full)
    forged = copy.deepcopy(full.context)
    forged["_actor_authorization"]["proof"] = "forged"
    with tenant_scope(7):
        for context in (None, weak.context, forged):
            result = service.delete(1, force=True, runtime_context=context)
            assert result["error_code"] == "cascade_permission_denied"
        result = _registered_router_customers(
            "delete",
            {"id": 1, "force": True, "_runtime_context": full.context},
            weak.context,
            "",
            "",
        )
        assert result["error_code"] == "cascade_permission_denied"
    with tenant_scope(8):
        assert service.delete(1, force=True, runtime_context=full.context)["success"] is False
    assert snapshot(full) == before


def test_http_cascade_uses_signed_actor_and_preserves_other_owners(deletion):
    from app.mod_sdk.erp_customers_facade import customers_delete

    _, full, _ = deletion
    with tenant_scope(7):
        result = customers_delete(full.request, 1, cascade=True)
    assert result["success"] is True
    remaining = snapshot(full)
    assert remaining[0] == [(2,), (3,), (101,), (102,), (103,)]
    assert remaining[1] == [(2,), (101,), (102,)]
    assert remaining[2] == [(2,), (101,), (102,)]  # Same name, different customer ID is not ours.
    assert len(remaining[3]) == 1


def test_batch_checks_product_only_association_and_foreign_ids_before_writes(deletion):
    _, full, service = deletion
    with tenant_scope(7), full.factory.begin() as db:
        db.query(ShipmentRecord).filter(ShipmentRecord.id == 2).delete()
    before = snapshot(full)
    with tenant_scope(7):
        result = service.batch_delete([3, 2])
        assert result["has_associations"] is True
        assert result["affected_units"][0]["product_count"] == 1
        assert result["affected_units"][0]["shipment_count"] == 0
        assert result["deleted_count"] == 0
        assert not service.batch_delete([3, 101], force=True, runtime_context=full.context)[
            "success"
        ]
    assert snapshot(full) == before


def test_batch_cascade_rolls_back_all_effects_on_late_database_failure(deletion):
    _, full, service = deletion
    before = snapshot(full)
    engine = full.factory.kw["bind"]

    def fail_second(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM products") and "Similar" in parameters:
            raise OperationalError(statement, parameters, Exception("injected failure"))

    event.listen(engine, "before_cursor_execute", fail_second)
    try:
        with tenant_scope(7):
            result = service.batch_delete([1, 2], force=True, runtime_context=full.context)
        assert result["success"] is False
        assert result["deleted_count"] == 0
    finally:
        event.remove(engine, "before_cursor_execute", fail_second)
    assert snapshot(full) == before


def test_batch_cascade_success_and_plain_empty_customer_delete(deletion):
    _, full, service = deletion
    with tenant_scope(7):
        assert service.delete(3)["success"] is True
        assert (
            service.batch_delete([1, 2], force=True, runtime_context=full.context)["deleted_count"]
            == 2
        )
    assert snapshot(full)[0] == [(101,), (102,), (103,)]
    assert snapshot(full)[1] == [(101,), (102,)]
    assert snapshot(full)[2] == [(101,), (102,)]


@pytest.mark.parametrize("revocation", ["session", "permission"])
def test_cascade_revalidates_authority_at_execution_time(deletion, revocation):
    from datetime import timedelta

    from app.db.models.permission import Role
    from app.db.models.user import Session as UserSession
    from app.utils.time import utc_now_naive

    _, full, service = deletion
    before = snapshot(full)
    with full.factory.begin() as db:
        if revocation == "session":
            db.get(UserSession, full.session_row_id).expires_at = utc_now_naive() - timedelta(
                seconds=1
            )
        else:
            role = db.query(Role).filter_by(name="cascade-owner").one()
            role.permissions = [p for p in role.permissions if p.code != "shipment.edit"]
    with tenant_scope(7):
        result = service.delete(1, force=True, runtime_context=full.context)
    assert result["error_code"] == "cascade_permission_denied"
    assert snapshot(full) == before


@pytest.mark.parametrize("ids", [[3, "bad"], [3, 101], [3, 999999], [3]])
def test_real_http_batch_uses_atomic_policy_after_signed_approval(
    deletion, monkeypatch, local_tools, ids
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.fastapi_routes.domains.customer.customer_routes import router

    actor, _, _ = deletion
    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repository,
    )
    app = FastAPI()
    app.include_router(router)
    before = snapshot(actor)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/customers/batch-delete", json={"ids": ids}, headers=actor.headers)
    assert response.status_code == 200, response.text
    run = repository.get(response.json()["run_id"])
    assert run is not None
    if run.status == "waiting_user":
        issue_approval_grant(run, principal_id=str(actor.user_id))
        run = AgentOrchestrator(repository=repository).continue_run(
            run.run_id, approved_by=str(actor.user_id), runtime_context=actor.context
        )
    assert run.tool_calls, run.to_dict()
    output = run.tool_calls[0].output
    if ids == [3]:
        assert output["success"] is True
        assert output["deleted_count"] == 1
        assert snapshot(actor)[0] == [(1,), (2,), (101,), (102,), (103,)]
    else:
        assert output["success"] is False
        assert output["deleted_count"] == 0
        assert snapshot(actor) == before


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/customers/batch-delete", {"ids": [3]}),
        ("DELETE", "/customers/3", None),
    ],
)
def test_owned_http_delete_gate_rejects_forged_or_unprivileged_callers(
    deletion, method, path, body
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.db.models.permission import Role
    from app.fastapi_routes.domains.customer.customer_routes import router

    weak, full, _ = deletion
    before = snapshot(full)
    with full.factory.begin() as db:
        role = db.query(Role).filter_by(name="customers-only").one()
        role.permissions = []
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        forged = client.request(
            method, path, json=body, headers={"X-User-Id": str(full.user_id), "X-Tenant-ID": "7"}
        )
        denied = client.request(method, path, json=body, headers=weak.headers)
    assert forged.status_code == 401
    assert denied.status_code == 403
    assert snapshot(full) == before


def test_delete_tool_contract_requires_customer_edit_without_lowering_approval():
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    for action in ("delete", "batch_delete"):
        spec = get_tool_action_spec("customers", action)
        assert spec.permission == "customer.edit"
        assert spec.risk == "high"
        assert spec.idempotent is False


@pytest.mark.parametrize("mixed", [False, True])
def test_platform_admin_http_batch_is_limited_to_null_rows(
    deletion, trusted_actor, monkeypatch, local_tools, mixed
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.fastapi_routes.domains.customer.customer_routes import router

    _, full, _ = deletion
    admin = trusted_actor(tenant_id=None, role="admin", tier="admin", permissions=["customer.edit"])
    with tenant_scope(None), full.factory.begin() as db:
        db.connection().exec_driver_sql(
            "INSERT INTO purchase_units (id,unit_name,tenant_id,is_active,version) VALUES (50,?,NULL,1,1)",
            ("Platform local",),
        )
    before = snapshot(full)
    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repository,
    )
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/customers/batch-delete",
            json={"ids": [50, 101] if mixed else [50]},
            headers=admin.headers,
        )
    assert response.status_code == 200, response.text
    run = repository.get(response.json()["run_id"])
    done = run
    if run.status == "waiting_user":
        issue_approval_grant(run, principal_id=str(admin.user_id))
        with tenant_scope(None):
            done = AgentOrchestrator(repository=repository).continue_run(
                run.run_id, approved_by=str(admin.user_id), runtime_context=admin.context
            )
    assert done.tool_calls, done.to_dict()
    assert done.metadata["approval_receipt"]["approved_by"] == str(admin.user_id)
    assert any(
        event.event_type == "step.approved" and event.data["approved_by"] == str(admin.user_id)
        for event in done.events
    )
    output = done.tool_calls[0].output
    if mixed:
        assert output["success"] is False
        assert snapshot(full) == before
    else:
        assert output["success"] is True
        assert output["deleted_count"] == 1
        assert snapshot(full)[0] == [(1,), (2,), (3,), (101,), (102,), (103,)]
        assert snapshot(full)[1:] == before[1:]


def test_personal_null_owner_and_admin_force_remain_closed(deletion, trusted_actor, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes.domains.customer.customer_routes import router

    _, full, service = deletion
    personal = trusted_actor(tenant_id=None, role="personal", permissions=["customer.edit"])
    admin = trusted_actor(tenant_id=None, role="admin", tier="admin", permissions=["customer.edit"])
    with tenant_scope(None), full.factory.begin() as db:
        db.connection().exec_driver_sql(
            "INSERT INTO purchase_units (id,unit_name,tenant_id,is_active,version) VALUES (50,?,NULL,1,1)",
            ("Platform local",),
        )
    before = snapshot(full)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        denied = client.post(
            "/customers/batch-delete", json={"ids": [50]}, headers=personal.headers
        )
        assert denied.status_code == 403
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", "generic")
        denied = client.post(
            "/customers/batch-delete", json={"ids": [50]}, headers=personal.headers
        )
        assert denied.status_code == 403
    with tenant_scope(None):
        assert service.delete(50)["success"] is False
        assert service.delete(101)["success"] is False
        assert service.delete(50, runtime_context=personal.context)["success"] is False
        assert service.delete(50, force=True, runtime_context=admin.context)["success"] is False
    assert snapshot(full) == before
