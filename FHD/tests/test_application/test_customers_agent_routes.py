from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.task_lifecycle import TaskLifecycleRecord
from app.fastapi_routes.domains.customer import routes as customer_routes
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_customer_cascade_authority import deletion as deletion
from tests.test_application.test_customer_cascade_authority import snapshot


def _client(headers=None) -> TestClient:
    from app.fastapi_routes.tools_execute import router as tools_router

    app = FastAPI()
    app.include_router(customer_routes.router)
    app.include_router(tools_router)
    return TestClient(app, raise_server_exceptions=True, headers=headers or {})


@pytest.fixture
def customer_sessions(tmp_path, monkeypatch, trusted_actor):
    # Approvals and owned customer rows share the authenticated test database;
    # an isolated two-table store cannot persist a canonical approval.
    actor = trusted_actor(user_id=1, role="admin")
    factory = actor.factory
    monkeypatch.setattr("app.application.customer_app_service.get_customers_session", factory)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    return factory


def _assert_customer_run(repo: InMemoryAgentRunRepository, run_id: str, action: str) -> None:
    run = repo.get(run_id)
    assert run is not None
    assert run.user_id == "1"
    assert run.metadata["runtime_context"]["_actor_authorization"]
    assert run.status == "completed"
    assert run.intent == f"ERP Agent 请求执行 customers.{action}"
    assert run.tool_calls[0].tool_id == "customers"
    assert run.tool_calls[0].action == action
    assert run.tool_calls[0].permission == "customer.edit"
    assert run.tool_calls[0].cost_units == 2
    assert run.tool_calls[0].metadata["verification"]["accepted"] is True
    assert {
        "step.waiting_user",
        "step.approved",
        "tool.completed",
        "run.completed",
    } <= {event.event_type for event in run.events}


def test_customer_mutation_routes_execute_through_agent_orchestrator(
    customer_sessions, local_tools, trusted_actor, monkeypatch, tmp_path
) -> None:
    from unittest.mock import Mock

    from app.application.customer_app_service import CustomerApplicationService

    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "claims.sqlite"))
    actor = trusted_actor(user_id=1, role="admin")
    monkeypatch.setattr("app.db.SessionLocal", customer_sessions)
    monkeypatch.setattr("app.db.session.SessionLocal", customer_sessions)
    client = ApprovedCapabilityClient(_client(actor.headers), repo, actor)
    # Keep the historic route target and prove the other tenant is untouched.
    with customer_sessions.begin() as db:
        db.add(PurchaseUnit(id=6, tenant_id=8, unit_name="Other tenant"))
    service = Mock(wraps=CustomerApplicationService())
    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=False,
        ),
        patch("app.application.get_customer_app_service", return_value=service),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        create_customer = client.post(
            "/customers",
            json={
                "unit_name": "星光贸易",
                "contact_person": "张三",
                "contact_phone": "13900000000",
                "contact_address": "上海",
                "tenant_id": 8,
            },
            headers={"X-User-Id": "tenant-a"},
        )
        with customer_sessions() as db:
            created_rows = (
                db.connection()
                .exec_driver_sql(
                    "SELECT id, tenant_id, unit_name FROM purchase_units ORDER BY id LIMIT 3"
                )
                .fetchmany(3)
            )
        assert create_customer.json().get("success") is True, (
            create_customer.json(),
            created_rows,
        )
        update_customer_resp = client.put(
            "/customers/7",
            json={
                "unit_name": "星光贸易二部",
                "contact_person": "李四",
                "contact_phone": "13800000000",
                "contact_address": "杭州",
                "tenant_id": 8,
            },
            headers={"X-User-Id": "tenant-a"},
        )
    assert create_customer.status_code == 200, create_customer.text
    assert update_customer_resp.status_code == 200, update_customer_resp.text
    service.create.assert_called_once_with(
        {
            "customer_name": "星光贸易",
            "contact_person": "张三",
            "contact_phone": "13900000000",
            "contact_address": "上海",
        }
    )
    service.update.assert_called_once_with(
        7,
        {
            "customer_name": "星光贸易二部",
            "contact_person": "李四",
            "contact_phone": "13800000000",
            "contact_address": "杭州",
        },
    )
    assert create_customer.json()["data"]["customer_name"] == "星光贸易"
    assert update_customer_resp.json()["data"]["customer_name"] == "星光贸易二部"
    _assert_customer_run(repo, create_customer.json()["run_id"], "create")
    _assert_customer_run(repo, update_customer_resp.json()["run_id"], "update")
    with customer_sessions() as db:
        rows = (
            db.connection()
            .exec_driver_sql(
                "SELECT id, tenant_id, unit_name FROM purchase_units ORDER BY id LIMIT 3"
            )
            .fetchmany(3)
        )
        assert rows == [(6, 8, "Other tenant"), (7, 7, "星光贸易二部")]


def test_customer_create_route_requires_a_persisted_row(
    customer_sessions, local_tools, trusted_actor, monkeypatch
) -> None:
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(user_id=1, role="admin")
    monkeypatch.setattr("app.db.SessionLocal", customer_sessions)
    monkeypatch.setattr("app.db.session.SessionLocal", customer_sessions)
    repo = InMemoryAgentRunRepository()
    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=False,
        ),
        patch.object(
            customer_routes,
            "_customer_body_name_contact",
            return_value=("未落库客户", "张三", "13900000000", "上海"),
        ),
        patch(
            "app.application.customer_app_service.CustomerApplicationService.create",
            return_value={
                "success": True,
                "data": {"id": 7, "customer_name": "未落库客户"},
            },
        ),
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        response = ApprovedCapabilityClient(_client(actor.headers), repo, actor).post(
            "/customers",
            json={"unit_name": "未落库客户"},
            headers={"X-User-Id": "tenant-a"},
        )
    assert response.status_code == 202, response.text
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


def test_customer_create_rejects_identity_headers_without_session(monkeypatch):
    from unittest.mock import Mock

    insert = Mock()
    monkeypatch.setattr(
        "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
        lambda: False,
    )
    monkeypatch.setattr("app.application.get_customer_app_service", insert)
    response = _client().post(
        "/customers",
        json={"unit_name": "Untrusted customer", "user_id": "1", "tenant_id": 7},
        headers={"X-User-Id": "1", "X-Tenant-Id": "7"},
    )
    assert response.status_code == 401
    insert.assert_not_called()


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
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repo,
    )
    before = snapshot(actor)
    monkeypatch.setattr(
        "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
        lambda: False,
    )
    with _client() as client:
        if action == "delete":
            response = client.delete(
                "/customers/3",
                headers={
                    **actor.headers,
                    "X-User-ID": "999",
                    "Idempotency-Key": "delete-customer",
                },
            )
        else:
            response = client.post(
                "/customers/batch-delete",
                json={"ids": ids},
                headers={**actor.headers, "Idempotency-Key": "delete-customer"},
            )
        canonical = client.post(
            "/api/tools/execute",
            json={
                "tool_id": "customers",
                "action": action,
                "params": {"id": ids[0]} if action == "delete" else {"ids": ids},
            },
            headers={**actor.headers, "Idempotency-Key": "delete-customer"},
        )
        assert canonical.status_code == response.status_code == 202, canonical.text
        assert canonical.json()["run_id"] == response.json()["run_id"]
        assert canonical.json()["request_id"] == response.json()["request_id"]
        assert snapshot(actor) == before
    assert response.status_code == 202, response.text
    run = repo.get(response.json()["run_id"])
    assert run.user_id == str(actor.user_id)
    done = run
    if run.status == "waiting_user":
        assert snapshot(actor) == before
        issue_approval_grant(run, principal_id=str(actor.user_id))
        with tenant_scope(actor.tenant_id):
            done = AgentOrchestrator(repository=repo).continue_run(
                run.run_id,
                approved_by=str(actor.user_id),
                runtime_context=run.metadata["runtime_context"],
                approval_request_id=run.metadata["approval_request_id"],
            )
    assert done.status == "completed", done.error
    assert done.tool_calls[0].metadata["verification"]["accepted"] is True
    assert done.metadata["approval_receipt"]["approved_by"] == str(actor.user_id)
    assert done.tool_calls[0].permission == "customer.edit"
    assert done.tool_calls[0].output["deleted_count"] == len(ids)
    assert {"step.approved", "tool.completed", "run.completed"} <= {
        e.event_type for e in done.events
    }
    assert all((value,) not in snapshot(actor)[0] for value in ids)
    assert snapshot(actor)[1:] == before[1:]
    assert (103,) in snapshot(actor)[0]


def test_customer_batch_route_rejects_invalid_ids_without_partial_effect(
    deletion, local_tools, monkeypatch
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant

    _, actor, _ = deletion
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repo,
    )
    before = snapshot(actor)
    with _client() as client:
        response = client.post(
            "/customers/batch-delete",
            json={"ids": [3, "bad", 4]},
            headers={**actor.headers, "Idempotency-Key": "invalid-customer-delete"},
        )
    assert response.status_code == 202
    assert response.json()["success"] is False
    assert snapshot(actor) == before
    run = repo.get(response.json()["run_id"])
    issue_approval_grant(run, principal_id=str(actor.user_id))
    with tenant_scope(actor.tenant_id):
        stopped = AgentOrchestrator(repository=repo).continue_run(
            run.run_id,
            approved_by=str(actor.user_id),
            runtime_context=run.metadata["runtime_context"],
            approval_request_id=run.metadata["approval_request_id"],
        )
    assert stopped.status == "failed", stopped.error
    assert stopped.steps[0].output["success"] is False
    assert snapshot(actor) == before


@pytest.mark.parametrize(
    "method,path,body,action",
    [
        ("POST", "/customers", {"unit_name": "星光贸易"}, "create"),
        ("PUT", "/customers/7", {"unit_name": "星光贸易二部"}, "update"),
    ],
)
def test_customer_global_routes_fail_closed_without_approval_scope(
    customer_sessions,
    local_tools,
    trusted_actor,
    monkeypatch,
    method,
    path,
    body,
    action,
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    actor = trusted_actor(user_id=7, tenant_id=None, role="admin", tier="admin")
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repo,
    )
    with (
        tenant_scope(None),
        patch("app.application.get_customer_app_service") as service,
    ):
        response = _client().request(
            method,
            path,
            json={**body, "user_id": "999"},
            headers={
                **actor.headers,
                "X-User-Id": "999",
                "Idempotency-Key": "customer-command",
            },
        )
    assert response.status_code == 403, response.text
    receipt = response.json()
    assert receipt["success"] is False and receipt["error_code"] == "approval_scope_required"
    assert receipt["execution_status"] == "not_started"
    assert not receipt.get("run_id")
    service.assert_not_called()


def _customer_workbook():
    from io import BytesIO

    from openpyxl import Workbook

    stream = BytesIO()
    workbook = Workbook()
    workbook.active.append(["单位名称", "联系人", "电话", "地址"])
    workbook.active.append(["原始客户", "负责人", "123456", "原始地址"])
    workbook.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize("tenant_id", [None, 7])
def test_customer_import_cannot_bypass_global_scope_or_approval(
    tmp_path, trusted_actor, local_tools, monkeypatch, tenant_id
):
    actor = trusted_actor(user_id=7, tenant_id=tenant_id, role="admin", tier="admin")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "uploads"))
    with (
        tenant_scope(tenant_id),
        patch(
            "app.application.customer_app_service.CustomerApplicationService.import_from_excel"
        ) as execute,
        _client() as client,
    ):
        receipt = client.post(
            "/customers/import",
            files={"file": ("customers.xlsx", _customer_workbook())},
            headers={
                **actor.headers,
                "X-User-Id": "999",
                "Idempotency-Key": "original-import",
            },
        )
    assert receipt.status_code == 403, receipt.text
    if tenant_id is None:
        assert receipt.json()["error_code"] == "approval_scope_required"
        assert receipt.json()["execution_status"] == "not_started"
    execute.assert_not_called()


def test_capability_upload_replay_owner_mod_and_original_content_binding(
    tmp_path, trusted_actor, monkeypatch
):
    from app.utils.path_io.upload_helpers import (
        read_capability_upload,
        stage_capability_upload,
    )

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    owner = trusted_actor(user_id=7, mod_id="mod-a")
    other = trusted_actor(user_id=8, mod_id="mod-a")
    other_mod = trusted_actor(user_id=7, mod_id="mod-b")
    options = {
        "namespace": "customer-import",
        "suffixes": frozenset({".xlsx", ".xlsm"}),
    }
    content = _customer_workbook()
    original = stage_capability_upload(content, "customers.xlsx", owner.context, **options)
    assert stage_capability_upload(content, "retry.xlsx", owner.context, **options) == original
    assert read_capability_upload(original, owner.context, **options) == content
    files = list((tmp_path / "data").rglob("*.xlsx"))
    assert len(files) == 1
    for actor in (other, other_mod):
        with pytest.raises((PermissionError, FileNotFoundError)):
            read_capability_upload(original, actor.context, **options)
    with pytest.raises(PermissionError):
        read_capability_upload(
            {**original, "saved_name": "../../customers.xlsx"}, owner.context, **options
        )
    files[0].write_bytes(b"changed after approval")
    with pytest.raises(PermissionError):
        read_capability_upload(original, owner.context, **options)
