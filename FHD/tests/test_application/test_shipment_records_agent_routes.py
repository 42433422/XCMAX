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
from app.db.base import Base
from app.fastapi_routes import shipment_orders
from app.infrastructure.auth import business_scope_gate as gate
from app.infrastructure.persistence.shipment_record_command_impl import (
    SQLAlchemyShipmentRecordCommand,
)
from app.infrastructure.persistence.shipment_record_query_impl import SQLAlchemyShipmentRecordQuery
from app.infrastructure.repositories.shipment_repository_impl import SQLAlchemyShipmentRepository
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope


def test_shipment_record_mutation_routes_execute_through_agent_orchestrator(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    engine = create_engine(f"sqlite:///{tmp_path / 'shipments.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=engine))
    repo = InMemoryAgentRunRepository()
    service = ShipmentApplicationService(
        SQLAlchemyShipmentRepository(),
        record_query=SQLAlchemyShipmentRecordQuery(),
        record_command=SQLAlchemyShipmentRecordCommand(),
    )
    user = [SimpleNamespace(id=11, is_active=True, role="user", tier="enterprise", tenant_id=7)]
    monkeypatch.setattr(shipment_orders, "_svc", lambda: service)
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_principal.resolve_session_user", lambda _r: user[0]
    )
    monkeypatch.setattr(gate, "resolve_session_user", lambda _r: user[0])
    monkeypatch.setattr(gate, "resolve_product_sku", lambda: "enterprise")
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

    client = TestClient(app)
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
        assert (
            client.patch(
                path,
                json={
                    "id": record_id,
                    "tenant_id": 8,
                    "status": "printed",
                    "product_name": "更新产品",
                },
            ).status_code
            == 200
        )
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
        assert client.get(path + "s").json()["data"] == []
        assert client.patch(path, json={"id": record_id, "status": "cancelled"}).status_code == 404
        assert client.request("DELETE", path, json={"id": record_id}).status_code == 404
        missing = client.post(path, json={"unit_name": "同名客户", "products": []})
        assert missing.status_code == 400 and "缺少" in missing.json()["message"]
        step = AgentStep(
            node_id="create", tool_id="shipment_records", action="create", params=params
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            created = pool.submit(
                AgentToolExecutor().execute,
                step,
                runtime_context={
                    "tenant_id": "8",
                    "service_source": "fastapi_shipment_records_route",
                },
            ).result(timeout=20)
            assert created["success"], created
            assert pool.submit(current_tenant_id).result() is None
            denied = pool.submit(
                AgentToolExecutor().execute,
                step,
                runtime_context={"service_source": "fastapi_shipment_records_route"},
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
        with tenant_scope(8):
            assert (
                service.export_shipment_records()["file_path"]
                != service.export_shipment_records()["file_path"]
            )
        user[0] = None
        assert client.post(path, json=params, headers={"X-User-ID": "11"}).status_code == 401
        user[0] = SimpleNamespace(
            id=11, is_active=True, role="user", tier="enterprise", tenant_id=7
        )
        assert client.request("DELETE", path, json={"id": record_id}).status_code == 200
        with tenant_scope(7):
            assert service.get_shipment_records() == []
            assert service._record_query.query_shipments()["total"] == 0
        with tenant_scope(8):
            assert len(service.get_shipment_records()) == 1
    finally:
        engine.dispose()
