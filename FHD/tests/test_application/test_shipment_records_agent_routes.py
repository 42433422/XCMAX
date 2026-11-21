from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.shipment_app_service import ShipmentApplicationService
from app.db.db_base import Base
from app.fastapi_routes import shipment_orders
from app.infrastructure.auth import business_scope_gate as gate
from app.infrastructure.persistence.shipment_record_command_impl import (
    SQLAlchemyShipmentRecordCommand,
)
from app.infrastructure.persistence.shipment_record_query_impl import SQLAlchemyShipmentRecordQuery
from app.infrastructure.repositories.shipment_repository_impl import SQLAlchemyShipmentRepository
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_shipment_record_routes_keep_approval_and_real_tenant_data(
    tmp_path, monkeypatch, trusted_actor, local_tools
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.approval_grant import issue_approval_grant
    from app.application.agent_orchestrator.result_verification import verification_blocked
    from app.infrastructure.auth.dependencies import resolve_session_user

    actor7 = trusted_actor(user_id=11, tenant_id=7, role="admin")
    actor8 = trusted_actor(user_id=22, tenant_id=8, role="admin")
    weak = trusted_actor(user_id=33, tenant_id=7, permissions=[])
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    service = ShipmentApplicationService(
        SQLAlchemyShipmentRepository(),
        record_query=SQLAlchemyShipmentRecordQuery(),
        record_command=SQLAlchemyShipmentRecordCommand(),
    )
    monkeypatch.setattr(shipment_orders, "_svc", lambda: service)
    monkeypatch.setattr("app.infrastructure.mods.hooks.trigger", lambda *_a, **_k: None)
    app = FastAPI()
    app.include_router(shipment_orders.router)

    @app.middleware("http")
    async def authenticated_tenant_scope(request, call_next):
        user = resolve_session_user(request)
        with tenant_scope(user.tenant_id if user else None):
            return await call_next(request)

    client = TestClient(app, headers=actor7.headers)
    path = "/api/shipment/shipment-records/record"
    params = {
        "unit_name": "同名客户",
        "products": [
            {
                "product_name": "验收产品",
                "quantity_tins": 2,
                "tin_spec": 10,
                "unit_price": 25,
                "amount": 500,
            }
        ],
        "contact_person": "验收员",
        "contact_phone": "13800000000",
    }

    def approve(response, actor):
        assert response.status_code == 202, response.text
        receipt = response.json()
        assert receipt["pending_approval"] is True and receipt["success"] is False
        run = repo.get(receipt["run_id"])
        assert not run.tool_calls and run.user_id == str(actor.user_id)
        with tenant_scope(actor.tenant_id):
            issue_approval_grant(run, principal_id=str(actor.user_id))
            return AgentOrchestrator(repository=repo).continue_run(
                run.run_id,
                approved_by=str(actor.user_id),
                runtime_context=run.metadata["runtime_context"],
                approval_request_id=run.metadata["approval_request_id"],
            )

    created = client.post(
        path,
        json={**params, "user_id": "forged"},
        headers={"X-User-ID": "forged", "Idempotency-Key": "record-create"},
    )
    with tenant_scope(7):
        assert service.get_shipment_records() == []
    run = approve(created, actor7)
    assert run.status == "blocked" and verification_blocked(run), run.error
    assert run.metadata["runtime_context"]["tenant_id"] == "7"
    with tenant_scope(7):
        records = service.get_shipment_records()
        assert len(records) == 1 and records[0]["tenant_id"] == 7
        record_id = records[0]["id"]
    replay = client.post(path, json=params, headers={"Idempotency-Key": "record-create"})
    assert replay.json()["run_id"] == run.run_id
    with tenant_scope(7):
        assert len(service.get_shipment_records()) == 1
    denied = client.patch(
        path,
        json={"id": record_id, "status": "printed", "user_id": "11"},
        headers={**weak.headers, "X-User-ID": "11", "Idempotency-Key": "denied-patch"},
    )
    assert denied.status_code == 403
    updated = approve(
        client.patch(
            path,
            json={"id": record_id, "tenant_id": 8, "status": "printed", "product_name": "更新产品"},
            headers={"Idempotency-Key": "record-update"},
        ),
        actor7,
    )
    assert updated.status == "blocked" and verification_blocked(updated)
    with tenant_scope(7):
        row = service._record_query.get_shipment_by_id(str(record_id))
        assert row["tenant_id"] == 7 and row["status"] == "printed"
        reopened = service.get_shipment(record_id)
        assert (
            reopened.contact_info.person == "验收员"
            and reopened.items[0].product_name == "更新产品"
        )
        assert reopened.total_quantity.kg == 20 and reopened.total_amount.amount == 500
    client.headers.update(actor8.headers)
    assert client.get(path + "s").json()["data"] == []
    for method in ("PATCH", "DELETE"):
        foreign = approve(
            client.request(
                method,
                path,
                json={"id": record_id, "status": "cancelled"},
                headers={"Idempotency-Key": f"foreign-{method}"},
            ),
            actor8,
        )
        assert foreign.tool_calls[0].output["success"] is False
    second = approve(
        client.post(path, json=params, headers={"Idempotency-Key": "tenant8-create"}), actor8
    )
    assert second.status == "blocked" and verification_blocked(second)
    with tenant_scope(8):
        assert service._record_query.get_shipment_by_id(str(record_id)) is None
        assert len(service.get_shipment_records()) == 1

    def read_tenant(tid):
        with tenant_scope(tid):
            return {row["tenant_id"] for row in service.get_shipment_records()}

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(read_tenant, [7, 8] * 20)) == [{7}, {8}] * 20
    exported = client.get("/api/shipment/shipment-records/export")
    assert exported.status_code == 200, exported.text
    workbook = load_workbook(BytesIO(exported.content), read_only=True)
    values = list(workbook.active.values)
    workbook.close()
    assert "验收产品" in str(values) and "更新产品" not in str(values)
    assert next(row for row in values if row and row[0] == "合计")[8] in (500, 500.0)
    client.headers.pop("X-Session-ID")
    assert client.post(path, json=params, headers={"X-User-ID": "11"}).status_code == 401
    client.headers.update(actor7.headers)
    deleted = approve(
        client.request(
            "DELETE", path, json={"id": record_id}, headers={"Idempotency-Key": "record-delete"}
        ),
        actor7,
    )
    assert deleted.status == "blocked" and verification_blocked(deleted)
    with tenant_scope(7):
        assert service.get_shipment_records() == []
    with tenant_scope(8):
        assert len(service.get_shipment_records()) == 1


def test_approved_inventory_without_independent_proof_stops_dependent_shipment(
    tmp_path, monkeypatch, trusted_actor
):
    import logging
    from pathlib import Path
    from unittest.mock import Mock, patch

    from app.application.agent_orchestrator.tool_permission import clear_idempotent_replay_for_tests

    clear_idempotent_replay_for_tests()

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
    from app.application.inventory_app_service import InventoryAppService
    from app.application.workflow.approval_persistence import load_workflow_snapshot_for_execution
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models import InventoryLedger, Product, User, Warehouse

    actor = trusted_actor(user_id=11, tenant_id=7, role="admin")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    engine = create_engine(f"sqlite:///{tmp_path / 'approved-shipment.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setattr("app.infrastructure.mods.hooks.trigger", lambda *a, **kw: None)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.AgentToolExecutor",
        lambda: SimpleNamespace(execute=AgentToolExecutor().execute),
    )
    with factory() as db:
        db.add(
            User(
                id=11,
                username="synthetic-shipment-user",
                password="test",
                tenant_id=7,
                role="admin",
            )
        )
        db.add(Product(id=1, tenant_id=7, name="隔离测试产品", model_number="TEST"))
        db.add(Warehouse(id=1, tenant_id=7, code="TEST", name="隔离测试仓", status="active"))
        db.commit()
    with tenant_scope(7):
        seeded = InventoryAppService().inventory_in(product_id=1, warehouse_id=1, quantity=10)
        assert seeded["success"], seeded
    shipment = ShipmentApplicationService(
        SQLAlchemyShipmentRepository(),
        record_query=SQLAlchemyShipmentRecordQuery(),
        record_command=SQLAlchemyShipmentRecordCommand(),
    )
    monkeypatch.setattr(shipment_orders, "_svc", lambda: shipment)
    params = {
        "unit_name": "隔离测试客户",
        "products": [
            {
                "product_name": "隔离测试产品",
                "quantity_tins": 2,
                "tin_spec": 10,
                "unit_price": 25,
                "amount": 500,
            }
        ],
    }
    plan = PlanGraph(
        plan_id="shipment-export-approval",
        intent="shipment",
        nodes=[
            WorkflowNode(
                "stock",
                "inventory",
                "stock_out",
                params={"product_id": 1, "warehouse_id": 1, "quantity": 2},
                risk="high",
            ),
            WorkflowNode(
                "shipment",
                "shipment_records",
                "create",
                params=params,
                risk="high",
                depends_on=["stock"],
            ),
            WorkflowNode(
                "export",
                "shipment_records",
                "export",
                params={"unit_name": "隔离测试客户"},
                risk="low",
                idempotent=True,
                depends_on=["shipment"],
            ),
        ],
    )
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    agent = AgentOrchestrator(repository=repo)
    approvals = ApprovalService()
    service = object.__new__(AIChatApplicationService)
    context = {
        **actor.context,
        "local_user_id": 11,
        "tenant_id": 7,
        "message": "生成出货记录并导出",
        "service_source": "fastapi_shipment_records_route",
    }
    service._pending_workflows = {
        "11": {
            "plan": plan,
            "runtime_context": context,
            "approval_required": True,
            "approval_nodes": [{"node_id": "stock"}, {"node_id": "shipment"}],
        }
    }
    service.approval_service = approvals
    unexpected = Mock(side_effect=AssertionError("alternate path"))
    bridge = WorkflowApprovalBridge(
        WorkflowBackends(
            approvals=lambda: ApprovalService(),
            pending_snapshot=unexpected,
            execution_snapshot=load_workflow_snapshot_for_execution,
            agent=lambda: AgentOrchestrator(
                repository=SQLAlchemyAgentRunRepository(session_factory=factory)
            ),
            load_run=repo.get,
        ),
        (RuntimeError,),
        logging.getLogger(__name__),
    )
    with (
        tenant_scope(7),
        patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=agent),
    ):
        handled, reply = service._resume_pending_dynamic_workflow("11", "确认", "确认")
        assert handled and reply["success"], reply
        assert shipment.get_shipment_records() == []
        request_no = reply["data"]["data"]["approval_request_ids"][0]
        outcome = bridge.resume(request_no=request_no, opinion="同意", approved_by="11")
        assert outcome["success"] is False, outcome
        stored = repo.get(outcome["agent_run_id"])
        assert stored.status == "blocked"
        assert stored.steps[0].status == "completed"
        assert (
            stored.tool_calls[0].metadata["verification"]["code"] == "result_verifier_unavailable"
        )
        assert [step.status for step in stored.steps[1:]] == ["pending", "pending"]
        with factory() as db:
            assert float(db.query(InventoryLedger).filter_by(tenant_id=7).one().quantity) == 8
        assert shipment.get_shipment_records() == []
        replay = bridge.resume(request_no=request_no, opinion="同意", approved_by="11")
        assert replay["success"] is False
        with factory() as db:
            assert float(db.query(InventoryLedger).filter_by(tenant_id=7).one().quantity) == 8
        assert shipment.get_shipment_records() == []
    engine.dispose()


def test_export_success_without_a_file_remains_unverified(
    tmp_path, monkeypatch, trusted_actor, local_tools
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.result_verification import verification_blocked
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor = trusted_actor(user_id=11, role="admin")
    repository = InMemoryAgentRunRepository()
    service = SimpleNamespace(
        export_shipment_records=lambda **_: {"success": True, "file_path": ""}
    )
    monkeypatch.setattr(shipment_orders, "_svc", lambda: service)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    plan = PlanGraph(
        plan_id="missing-export-file",
        intent="export",
        nodes=[
            WorkflowNode(
                node_id="export",
                tool_id="shipment_records",
                action="export",
                params={},
                risk="low",
                idempotent=True,
            )
        ],
    )
    with tenant_scope(actor.tenant_id):
        run = AgentOrchestrator(repository=repository).start_run_from_plan(
            user_id=str(actor.user_id),
            message="导出出货记录",
            plan=plan,
            runtime_context={**actor.context, "service_source": "fastapi_shipment_records_route"},
        )
    assert run.status == "blocked", run.error
    assert verification_blocked(run)
    assert run.tool_calls[0].output["success"] is True
    assert run.tool_calls[0].metadata["verification"]["accepted"] is False
    assert not run.artifacts


def _canonical_record_service(monkeypatch):
    service = ShipmentApplicationService(
        SQLAlchemyShipmentRepository(),
        record_query=SQLAlchemyShipmentRecordQuery(),
        record_command=SQLAlchemyShipmentRecordCommand(),
    )
    monkeypatch.setattr("app.bootstrap.get_shipment_application_service_core", lambda: service)
    monkeypatch.setattr("app.infrastructure.mods.hooks.trigger", lambda *_a, **_k: None)
    return service


@pytest.mark.parametrize("products_key", ["products", "items"])
@pytest.mark.parametrize(
    "contacts",
    [
        {},
        {"contact_person": None, "contact_phone": None},
        {"contact_person": "真实联系人", "contact_phone": "13800000000"},
    ],
)
def test_canonical_record_create_uses_actual_service_parameter_types(
    trusted_actor, monkeypatch, products_key, contacts
):
    from app.domain.shared_services.tools_workflow_shipments_docs import (
        _registered_router_shipment_records,
    )

    actor = trusted_actor(role="admin")
    service = _canonical_record_service(monkeypatch)
    create = Mock(wraps=service.create_shipment)
    monkeypatch.setattr(service, "create_shipment", create)
    products = [{"product_name": "真实产品", "quantity_kg": 2.5, "unit_price": 4}]
    with tenant_scope(actor.tenant_id):
        result = _registered_router_shipment_records(
            "create",
            {"unit_name": "真实客户", products_key: products, **contacts},
            actor.context,
            "admin",
            "",
        )
        assert result["success"] is True, result
        rows = service.get_shipment_records()
        assert isinstance(rows, list) and len(rows) == 1
        stored = service.get_shipment(rows[0]["id"])
    expected_person = contacts.get("contact_person") or ""
    expected_phone = contacts.get("contact_phone") or ""
    create.assert_called_once_with(
        unit_name="真实客户",
        items_data=products,
        contact_person=expected_person,
        contact_phone=expected_phone,
    )
    assert stored.contact_info.person == expected_person
    assert stored.contact_info.phone == expected_phone
    assert stored.items[0].product_name == "真实产品"
    assert stored.total_quantity.kg == 2.5


def test_canonical_record_create_rejects_invalid_items_before_service(trusted_actor, monkeypatch):
    from app.domain.shared_services.tools_workflow_shipments_docs import (
        _registered_router_shipment_records,
    )

    actor = trusted_actor(role="admin")
    service = _canonical_record_service(monkeypatch)
    create = Mock(wraps=service.create_shipment)
    monkeypatch.setattr(service, "create_shipment", create)
    with tenant_scope(actor.tenant_id):
        result = _registered_router_shipment_records(
            "create", {"unit_name": "真实客户", "products": [None]}, actor.context, "admin", ""
        )
        assert result["success"] is False
        assert service.get_shipment_records() == []
    create.assert_not_called()


def test_canonical_record_clear_removes_over_one_page_only_in_original_tenant(
    trusted_actor, monkeypatch
):
    from app.db.models import ShipmentRecord
    from app.domain.shared_services.tools_workflow_shipments_docs import (
        _registered_router_shipment_records,
    )

    actor = trusted_actor(role="admin")
    service = _canonical_record_service(monkeypatch)
    for tenant_id, count in ((actor.tenant_id, 137), (8, 2)):
        with tenant_scope(tenant_id), actor.factory.begin() as db:
            db.add_all(
                ShipmentRecord(
                    tenant_id=tenant_id,
                    purchase_unit="真实客户",
                    product_name=f"产品-{index}",
                    quantity_kg=1,
                    quantity_tins=1,
                    tin_spec=1,
                )
                for index in range(count)
            )
    with tenant_scope(actor.tenant_id):
        listed = _registered_router_shipment_records("list", {}, actor.context, "admin", "")
        assert listed["success"] is True and isinstance(listed["data"], list)
        assert len(listed["data"]) == 100
        list_again = Mock(side_effect=AssertionError("clear must use the existing atomic command"))
        delete_one = Mock(
            side_effect=AssertionError("clear must not recreate a per-row implementation")
        )
        monkeypatch.setattr(service, "get_shipment_records", list_again)
        monkeypatch.setattr(service, "delete_shipment_record", delete_one)
        result = _registered_router_shipment_records("clear", {}, actor.context, "admin", "")
        assert result["success"] is True, result
        assert "deleted_count" not in result and "failed_count" not in result
        with actor.factory() as db:
            assert db.query(ShipmentRecord).count() == 0
    with tenant_scope(8), actor.factory() as db:
        assert db.query(ShipmentRecord).count() == 2
    list_again.assert_not_called()
    delete_one.assert_not_called()


@pytest.mark.parametrize("failure", ["unconfigured", "database"])
def test_canonical_record_clear_preserves_real_service_failure(trusted_actor, monkeypatch, failure):
    from app.domain.shared_services.tools_workflow_shipments_docs import (
        _registered_router_shipment_records,
    )

    actor = trusted_actor(role="admin")
    service = _canonical_record_service(monkeypatch)
    if failure == "unconfigured":
        service._record_command = None
        expected = {"success": False, "message": "record_command 未配置"}
    else:
        monkeypatch.setattr(
            "app.infrastructure.persistence.shipment_record_command_impl.get_db",
            Mock(side_effect=OSError("database unavailable")),
        )
        expected = {"success": False, "message": "清空失败：database unavailable"}
    with tenant_scope(actor.tenant_id):
        result = _registered_router_shipment_records("clear", {}, actor.context, "admin", "")
    assert result == expected
    assert "deleted_count" not in result
    assert "failed_count" not in result
