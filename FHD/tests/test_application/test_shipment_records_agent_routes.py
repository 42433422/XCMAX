from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

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


def test_shipment_record_mutation_routes_execute_through_agent_orchestrator(
    tmp_path, monkeypatch, trusted_actor
):
    from app import db as host_db

    actor7 = trusted_actor(user_id=11, tenant_id=7, permissions=["shipment.view", "shipment.edit"])
    actor8 = trusted_actor(user_id=22, tenant_id=8)
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    engine = actor7.factory.kw["bind"]
    # The real worker must reopen the same session rows and tenant records;
    # parent-only SQLAlchemy patches cannot authenticate a spawned process.
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "tool-claims.sqlite"))
    monkeypatch.setattr(host_db, "SessionLocal", actor7.factory)
    monkeypatch.setattr("app.db.session.SessionLocal", actor7.factory)
    repo = InMemoryAgentRunRepository()
    service = ShipmentApplicationService(
        SQLAlchemyShipmentRepository(),
        record_query=SQLAlchemyShipmentRecordQuery(),
        record_command=SQLAlchemyShipmentRecordCommand(),
    )
    user = [SimpleNamespace(id=11, is_active=True, role="user", tier="enterprise", tenant_id=7)]
    monkeypatch.setattr(shipment_orders, "_svc", lambda: service)
    monkeypatch.setattr(gate, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    allowed = [True]
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: SimpleNamespace(
            has_permission=lambda _u, code: (
                allowed[0] and code in {"shipment.view", "shipment.edit"}
            )
        ),
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setattr("app.infrastructure.mods.hooks.trigger", lambda *a, **kw: None)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    app = FastAPI()
    app.include_router(shipment_orders.router)

    @app.middleware("http")
    async def authenticated_tenant_scope(request, call_next):
        with tenant_scope(user[0].tenant_id if user[0] else None):
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
    try:
        response = client.post(
            path, json={**params, "user_id": "forged"}, headers={"X-User-ID": "forged"}
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        record_id = payload["shipment"]["id"]
        run = repo.get(payload["run_id"])
        assert run.user_id == "11" and run.status == "completed"
        assert run.metadata["runtime_context"]["tenant_id"] == "7"
        assert {"step.waiting_user", "step.approved", "tool.completed", "run.completed"} <= {
            e.event_type for e in run.events
        }
        allowed[0] = False
        assert client.patch(path, json={"id": record_id, "status": "printed"}).status_code == 403
        allowed[0] = True
        updated = client.patch(
            path,
            json={
                "id": record_id,
                "tenant_id": 8,
                "tenantId": 8,
                "user_id": "22",
                "userId": "22",
                "status": "printed",
                "product_name": "更新产品",
            },
        )
        assert updated.status_code == 200, updated.text
        update_run = repo.get(updated.json()["run_id"])
        assert update_run is not None and update_run.status == "completed"
        assert update_run.metadata["runtime_context"]["tenant_id"] == "7"
        assert not {"tenant_id", "tenantId", "user_id", "userId"} & set(update_run.steps[0].params)
        with tenant_scope(7):
            rows = service.get_shipment_records()
            assert len(rows) == 1 and rows[0]["tenant_id"] == 7 and rows[0]["status"] == "printed"
            assert service._record_query.get_shipment_by_id(str(record_id))["id"] == record_id
            assert service._record_query.get_latest_shipments(1)[0]["id"] == record_id
            reopened = service.get_shipment(record_id)
            assert (
                reopened.contact_info.person == "验收员"
                and reopened.items[0].product_name == "更新产品"
            )
            assert reopened.total_quantity.kg == 20 and reopened.total_amount.amount == 500
            reopened.metadata["document"] = {"order_number": "SHIP-metadata"}
            service._repository.save(reopened)
            assert service.mark_as_printed(record_id)["success"]
            assert (
                service._record_query.get_shipment_by_id(str(record_id))["order_number"]
                == "SHIP-metadata"
            )
            assert service.get_shipment(record_id).items[0].product_name == "更新产品"
        user[0] = SimpleNamespace(
            id=22, is_active=True, role="user", tier="enterprise", tenant_id=8
        )
        client.headers.update(actor8.headers)
        assert client.get(path + "s").json()["data"] == []
        assert client.patch(path, json={"id": record_id, "status": "cancelled"}).status_code == 404
        assert client.request("DELETE", path, json={"id": record_id}).status_code == 404
        missing = client.post(path, json={"unit_name": "同名客户", "products": []})
        assert missing.status_code == 400
        assert missing.json()["message"] == "出货单操作失败"
        assert "缺少" not in missing.json()["message"]
        step = AgentStep(
            node_id="create", tool_id="shipment_records", action="create", params=params
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            created = pool.submit(
                AgentToolExecutor().execute,
                step,
                runtime_context={
                    **actor8.context,
                    "tenant_id": "8",
                    "service_source": "fastapi_shipment_records_route",
                },
            ).result(timeout=20)
            assert created["success"], created
            assert pool.submit(current_tenant_id).result() is None
            denied = pool.submit(
                AgentToolExecutor().execute,
                step,
                runtime_context={
                    **actor8.context,
                    "tenant_id": None,
                    "service_source": "fastapi_shipment_records_route",
                },
            ).result(timeout=20)
            assert denied["success"] is False
        with tenant_scope(8):
            assert len(service.get_shipment_records()) == 1
            assert service._record_query.get_shipment_by_id(str(record_id)) is None

        def read_tenant(tid):
            with tenant_scope(tid):
                return {row["tenant_id"] for row in service.get_shipment_records()}

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(read_tenant, [7, 8] * 20)) == [{7}, {8}] * 20
        exported = client.get("/api/shipment/shipment-records/export")
        assert exported.status_code == 200
        workbook = load_workbook(BytesIO(exported.content), read_only=True)
        values = list(workbook.active.values)
        workbook.close()
        assert "验收产品" in str(values) and "更新产品" not in str(values)
        summary = next(row for row in values if row and row[0] == "合计")
        assert summary[8] in (500, 500.0)
        with tenant_scope(8):
            assert (
                service.export_shipment_records()["file_path"]
                != service.export_shipment_records()["file_path"]
            )
        user[0] = None
        del client.headers["X-Session-ID"]
        assert client.post(path, json=params, headers={"X-User-ID": "11"}).status_code == 401
        user[0] = SimpleNamespace(
            id=11, is_active=True, role="user", tier="enterprise", tenant_id=7
        )
        client.headers.update(actor7.headers)
        assert client.request("DELETE", path, json={"id": record_id}).status_code == 200
        with tenant_scope(7):
            assert service.get_shipment_records() == []
            assert service._record_query.query_shipments()["total"] == 0
            assert service.clear_all_orders()["success"]
        with tenant_scope(8):
            assert len(service.get_shipment_records()) == 1
    finally:
        engine.dispose()


def test_approved_shipment_then_export_uses_full_persisted_plan(
    tmp_path, monkeypatch, trusted_actor
):
    import logging
    from pathlib import Path
    from unittest.mock import Mock

    from app.application.agent_orchestrator.tool_permission import clear_idempotent_replay_for_tests

    clear_idempotent_replay_for_tests()

    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.approval_workspace.protocols import WorkflowBackends
    from app.application.approval_workspace.workflow_bridge import WorkflowApprovalBridge
    from app.application.inventory_app_service import InventoryAppService
    from app.application.workflow.approval_persistence import load_workflow_snapshot_for_execution
    from app.application.workflow.approval_service import ApprovalService
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_from_dict
    from app.db.models import InventoryLedger, Product, User, Warehouse
    from app.db.models.permission import DEFAULT_ROLES

    permissions = next(role["permissions"] for role in DEFAULT_ROLES if role["name"] == "admin")
    actor = trusted_actor(
        user_id=11,
        tenant_id=7,
        role="admin",
        permissions=[*permissions, "tool.inventory.query_transactions"],
    )
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "shipment-claims.sqlite"))
    engine = create_engine(f"sqlite:///{tmp_path / 'approved-shipment.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    monkeypatch.setattr("app.db.SessionLocal", factory)
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
        metadata={"approval_required_node_ids": ["stock", "shipment"]},
    )
    repo = SQLAlchemyAgentRunRepository(session_factory=factory)
    agent = AgentOrchestrator(repository=repo)
    approvals = ApprovalService()
    context = {
        **actor.context,
        "local_user_id": 11,
        "tenant_id": 7,
        "message": "生成出货记录并导出",
        "service_source": "fastapi_shipment_records_route",
    }
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
    with tenant_scope(7):
        waiting = agent.start_run_from_plan(
            user_id="11", message="生成出货记录并导出", plan=plan, runtime_context=context
        )
        assert waiting.status == "waiting_user", waiting.to_dict()
        stored_plan = plan_from_dict(waiting.metadata["plan"])
        assert stored_plan is not None
        request = approvals.create_approval_request(
            plan_id=stored_plan.plan_id,
            node=stored_plan.nodes[0],
            runtime_context={**context, "_approval_agent_run_required": True},
            plan=stored_plan,
            require_persistence=True,
        )
        request_no = request.request_id
        assert approvals.attach_pending_agent_run(
            request_no, agent_run_id=waiting.run_id, approved_step_id="stock"
        )
        assert shipment.get_shipment_records() == []
        outcome = bridge.resume(request_no=request_no, opinion="同意", approved_by="11")
        assert outcome.get("waiting_approval") is True, outcome
        with factory() as db:
            assert float(db.query(InventoryLedger).filter_by(tenant_id=7).one().quantity) == 8
        assert shipment.get_shipment_records() == []
        replay = bridge.resume(request_no=request_no, opinion="同意", approved_by="11")
        assert replay["success"] is False
        with factory() as db:
            assert float(db.query(InventoryLedger).filter_by(tenant_id=7).one().quantity) == 8
        outcome = bridge.resume(
            request_no=outcome["next_approval_request_id"], opinion="同意", approved_by="11"
        )
        assert outcome["success"], outcome
        stored = repo.get(outcome["agent_run_id"])
        assert [step.status for step in stored.steps] == ["completed", "completed", "completed"]
        output = stored.steps[2].output
        path = output.get("file_path") or (output.get("data") or {}).get("file_path")
        assert path and Path(path).is_file(), output
        book = load_workbook(path, read_only=True)
        rows = list(book.active.iter_rows(values_only=True))
        book.close()
        cells = [cell for row in rows for cell in row]
        text = {str(cell) for cell in cells}
        assert "隔离测试产品" in text
        assert 2 in cells or "2" in text
        assert 500 in cells or "500" in text
        summary = next(row for row in rows if row and row[0] == "合计")
        assert summary[8] in (500, 500.0)
        # The existing exporter owns the bytes and exact call binding. Reading
        # them again cannot accept a borrowed owner, changed file, or revoked grant.
        import copy

        from app.application.agent_orchestrator.task_background import task_execution_context
        from app.application.agent_orchestrator.verification_readback import (
            verify_independent_result,
        )
        from app.db.models.permission import Role

        step, call = stored.steps[2], stored.tool_calls[2]
        verification_context = {
            **stored.metadata["runtime_context"],
            **task_execution_context(stored, step),
            "run_id": stored.run_id,
            "step_id": step.step_id,
        }

        def readback(result):
            return verify_independent_result(
                run=stored, step=step, call=call, context=verification_context, output=result
            )

        assert readback(call.output)["status"] == "verified"
        borrowed = copy.deepcopy(call.output)
        borrowed["artifacts"][0]["metadata"]["owner_user_id"] = "another-owner"
        assert readback(borrowed)["code"] == "result_artifact_scope_mismatch"
        original_bytes = Path(path).read_bytes()
        Path(path).write_bytes(b"changed original export")
        assert readback(call.output)["status"] != "verified"
        Path(path).write_bytes(original_bytes)
        with actor.factory.begin() as db:
            role = db.query(Role).filter_by(name="admin").one()
            role.permissions = [p for p in role.permissions if p.code != "shipment.view"]
        assert readback(call.output)["code"] == "result_read_permission_unavailable"
    engine.dispose()


def test_r05_export_without_a_file_fails_the_business_assertion(
    tmp_path, monkeypatch, trusted_actor
):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from app.application.shipment_document_workflows import ShipmentDocumentWorkflowMixin

    def empty_export(self, *_args, **_kwargs):
        return {"success": True, "file_path": ""}

    monkeypatch.setattr(ShipmentDocumentWorkflowMixin, "export_shipment_records", empty_export)
    try:
        test_approved_shipment_then_export_uses_full_persisted_plan(
            tmp_path, monkeypatch, trusted_actor
        )
    except AssertionError:
        import json
        import sqlite3

        with sqlite3.connect(tmp_path / "approved-shipment.db") as db:
            runs = [json.loads(row[0]) for row in db.execute("SELECT payload_json FROM agent_runs")]
        assert len(runs) == 1 and runs[0]["status"] == "blocked"
        calls = runs[0]["tool_calls"]
        assert len(calls) == 3
        assert all(call["metadata"]["verification"]["accepted"] for call in calls[:2])
        assert calls[2]["output"] == {"success": True, "file_path": ""}
        assert calls[2]["metadata"]["verification"]["code"] == "result_artifact_missing"
    else:
        raise AssertionError("an export without a file was accepted")
    env = os.environ.copy()
    restored = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_application/test_shipment_records_agent_routes.py::test_approved_shipment_then_export_uses_full_persisted_plan",
            "-q",
            "-o",
            "addopts=",
            "--tb=line",
            "--basetemp",
            str(tmp_path / "fresh-positive"),
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr
