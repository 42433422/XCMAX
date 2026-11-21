"""Real host/Mod stores must agree across authenticated HTTP, tools and bus workers."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.application.enterprise_cognition import projection
from app.application.tools.workflow_tools.dispatch import execute_registered_workflow_tool
from app.db import Base
from app.db.host_base_db_api import should_use_base_database_for_path
from app.db.models import (
    AgentRunRecord,
    AgentTaskRecord,
    AiEmployeeProfile,
    EnterpriseEventCursor,
    EnterpriseStateProjection,
    SalesOrder,
    SalesOrderItem,
)
from app.fastapi_app.middleware_extra import register_extra_middleware
from app.fastapi_routes.domains.agent.task_routes import router
from app.http.request_context import reset_current_http_request, set_current_http_request
from app.infrastructure import enterprise_cognition_events as source_events
from app.infrastructure.tenant_scope import tenant_scope
from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture
def mod_world(trusted_actor, tmp_path, monkeypatch):
    actor = trusted_actor(
        role="enterprise-mod-reader",
        mod_id="sales",
        permissions=["tool.sales.query", "employee.list"],
    )
    mod_engine = create_engine(f"sqlite:///{tmp_path / 'sales.sqlite'}")
    Base.metadata.create_all(
        mod_engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if not table.name.startswith("enterprise_")
        ],
    )
    mod_sessions = sessionmaker(mod_engine)
    monkeypatch.setenv("XCAGI_MOD_DATABASE_URLS", json.dumps({"sales": str(mod_engine.url)}))
    monkeypatch.delenv("FHD_ALLOW_X_USER_ID_HEADER", raising=False)
    stamp = "2026-11-21T00:00:00+00:00"
    for factory, label, delivered in (
        (actor.factory, "HOST", 2),
        (mod_sessions, "MOD", 8),
    ):
        with tenant_scope(actor.tenant_id), factory.begin() as db:
            order = SalesOrder(id=101, order_no=label, state="confirmed", total_amount=100)
            order.items = [
                SalesOrderItem(
                    id=401,
                    product_name=label,
                    quantity=10,
                    ordered_quantity=10,
                    delivered_quantity=delivered,
                    unit="件",
                )
            ]
            db.add(order)
            db.add(
                AgentRunRecord(
                    run_id="run-a",
                    user_id=str(actor.user_id),
                    status="running",
                    message="Original task",
                    payload_json=json.dumps({"metadata": {"runtime_context": actor.context}}),
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
            db.add(
                AgentTaskRecord(
                    task_id="task-a",
                    user_id=str(actor.user_id),
                    tenant_id=str(actor.tenant_id),
                    active_run_id="run-a",
                    title=f"{label}-TASK",
                    status="running",
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
            db.add(
                AiEmployeeProfile(
                    employee_id="employee-a",
                    user_id=100,
                    owner_user_id=actor.user_id,
                    mod_id="sales",
                    display_name=f"{label}-EMPLOYEE",
                )
            )
    app = FastAPI()
    register_extra_middleware(app)
    app.include_router(router)
    try:
        with TestClient(app) as client:
            yield actor, client, mod_sessions
    finally:
        mod_engine.dispose()


def query(actor, client, kind="order", entity_id="101", *, host=False):
    headers = dict(actor.headers)
    if host:
        headers.pop("X-XCAGI-Active-Mod-Id")
    response = client.post(
        "/api/enterprise/cognition",
        headers=headers,
        json={"action": "query", "params": {"entity_type": kind, "entity_id": entity_id}},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["snapshots"][0]


def test_http_and_model_use_mod_order_but_management_routes_remain_host(mod_world):
    actor, client, mod_sessions = mod_world
    assert not should_use_base_database_for_path("/api/enterprise/cognition")
    assert should_use_base_database_for_path("/api/enterprise/profile")
    mod = query(actor, client)
    host = query(actor, client, host=True)
    assert mod["mod_id"] == "sales" and mod["state"]["order_no"] == "MOD"
    assert Decimal(mod["state"]["remaining_quantity"]) == 2
    assert host["mod_id"] == "" and host["state"]["order_no"] == "HOST"
    assert Decimal(host["state"]["remaining_quantity"]) == 8
    model = execute_registered_workflow_tool(
        "enterprise_cognition",
        "query",
        {"entity_id": "101", "_runtime_context": actor.context},
    )
    assert model["success"] is True
    assert model["data"]["snapshots"][0]["source_version"] == mod["source_version"]
    assert model["data"]["snapshots"][0]["retrieved_from"] == "projection"
    with actor.factory() as db:
        cached = list(db.scalars(select(EnterpriseStateProjection)))
        assert {row.mod_id for row in cached} == {"", "sales"}
    with mod_sessions() as db:
        assert not any(
            name.startswith("enterprise_") for name in inspect(db.get_bind()).get_table_names()
        )
    denied = client.post(
        "/api/enterprise/cognition",
        headers={**actor.headers, "X-XCAGI-Active-Mod-Id": "not-entitled"},
        json={"action": "query", "params": {"entity_id": "101"}},
    )
    assert denied.status_code == 403


def test_tasks_and_employees_read_host_authority_with_original_mod_binding(mod_world):
    actor, client, _ = mod_world
    assert query(actor, client, "task", "task-a")["state"]["title"] == "HOST-TASK"
    assert query(actor, client, "employee", "employee-a")["state"]["display_name"] == (
        "HOST-EMPLOYEE"
    )
    assert query(actor, client, "task", "task-a", host=True)["freshness"] == "unknown"
    response = client.post(
        "/api/enterprise/cognition",
        headers=actor.headers,
        json={"action": "query", "params": {"entity_type": "task"}},
    )
    assert response.status_code == 200
    assert response.json()["data"]["snapshots"][0]["state"]["title"] == "HOST-TASK"
    with actor.factory.begin() as db:
        run = db.get(AgentRunRecord, "run-a")
        payload = json.loads(run.payload_json)
        payload["metadata"]["runtime_context"]["mod_id"] = "another"
        run.payload_json = json.dumps(payload)
    assert query(actor, client, "task", "task-a")["freshness"] == "unknown"


@pytest.mark.asyncio
async def test_neurobus_worker_uses_event_mod_and_host_task_source(mod_world, monkeypatch):
    from app.mod_sdk import neuro_bus_runtime
    from app.neuro_bus import application_neuro_bridge
    from app.neuro_bus import bus as bus_module

    actor, client, mod_sessions = mod_world
    before = query(actor, client)
    host_before = query(actor, client, host=True)
    query(actor, client, "task", "task-a")
    query(actor, client, "employee", "employee-a")
    query(actor, client, "employee", "employee-a", host=True)
    bus = bus_module.NeuroBus()
    received = {
        key: asyncio.Event()
        for key in (("order", "sales"), ("task", "sales"), ("employee", "sales"), ("employee", ""))
    }
    loop = asyncio.get_running_loop()
    original_consume = projection.consume_entity_event

    def consume_and_signal(message):
        result = original_consume(message)
        key = (message.payload["entity_type"], message.payload["mod_id"])
        if result and key in received:
            loop.call_soon_threadsafe(received[key].set)
        return result

    monkeypatch.setattr(projection, "consume_entity_event", consume_and_signal)
    monkeypatch.setattr(application_neuro_bridge, "_stack_on", lambda: True)
    monkeypatch.setattr(neuro_bus_runtime, "is_neuro_bus_runtime_via_mod_enabled", lambda: False)
    monkeypatch.setattr(bus_module, "get_neuro_bus", lambda: bus)
    projection.register_enterprise_subscriptions(bus)
    # Deliberately inherit an unrelated host-only HTTP path at worker startup.
    request_token = set_current_http_request(
        Request({"type": "http", "path": "/api/enterprise/profile", "headers": []})
    )
    try:
        await bus.start()
    finally:
        reset_current_http_request(request_token)
    try:
        mod_token = set_request_active_mod_id("sales")
        try:
            with tenant_scope(actor.tenant_id), mod_sessions.begin() as db:
                db.get(SalesOrderItem, 401).delivered_quantity = 9
        finally:
            reset_request_active_mod_id(mod_token)
        await asyncio.wait_for(received[("order", "sales")].wait(), timeout=3)
        after = query(actor, client)
        assert after["source_version"] != before["source_version"]
        assert Decimal(after["state"]["remaining_quantity"]) == 1
        assert after["retrieved_from"] == "authority" and after["last_event_id"]
        host_after = query(actor, client, host=True)
        assert host_after["source_version"] == host_before["source_version"]
        assert host_after["retrieved_from"] == "projection"

        # Original task completion runs in host storage without an active Mod.
        with actor.factory.begin() as db:
            db.scalar(
                select(AgentTaskRecord).where(AgentTaskRecord.task_id == "task-a")
            ).title = "HOST-TASK-UPDATED"
            db.scalar(select(AiEmployeeProfile)).display_name = "HOST-EMPLOYEE-UPDATED"
        for key in (("task", "sales"), ("employee", "sales"), ("employee", "")):
            await asyncio.wait_for(received[key].wait(), timeout=3)
        task = query(actor, client, "task", "task-a")
        assert task["state"]["title"] == "HOST-TASK-UPDATED"
        assert task["retrieved_from"] == "authority" and task["last_event_id"]
        for host in (False, True):
            employee = query(actor, client, "employee", "employee-a", host=host)
            assert employee["state"]["display_name"] == "HOST-EMPLOYEE-UPDATED"
            assert employee["retrieved_from"] == "authority" and employee["last_event_id"]
        with actor.factory() as db:
            assert (
                db.scalar(
                    select(EnterpriseEventCursor).where(
                        EnterpriseEventCursor.entity_type == "task",
                        EnterpriseEventCursor.mod_id == "sales",
                    )
                ).event_id
                == task["last_event_id"]
            )
    finally:
        await bus.stop()
        for name, handler in (
            ("after_flush", source_events._capture),
            ("after_commit", source_events._committed),
            ("after_soft_rollback", source_events._rolled_back),
        ):
            event.remove(Session, name, handler)
