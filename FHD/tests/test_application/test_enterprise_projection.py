"""Authority isolation, expiry, read-only projection and commit-only event contract."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.application.enterprise_cognition.projection import ProjectionService, consume_entity_event
from app.db import Base
from app.db.models import (
    AgentRunRecord,
    AgentTaskRecord,
    AiEmployeeProfile,
    Customer,
    EnterpriseEventCursor,
    FinancialTransaction,
    SalesOrder,
    SalesOrderItem,
    User,
)
from app.db.models.employee_run_log import EmployeeRunLog
from app.domain.enterprise_cognition.catalog import entity_catalog
from app.infrastructure.enterprise_cognition_sources import AuthorityReader
from app.infrastructure.tenant_scope import tenant_scope
from app.neuro_bus.events.events_base import EventMetadata, NeuroEvent
from app.request_active_mod_ctx import (
    reset_request_active_mod_id,
    set_request_active_mod_id,
)


@pytest.fixture
def world(tmp_path):
    # Authority reads and host projections own separate transactions; use real
    # connections rather than one StaticPool connection shared by both sessions.
    engine = create_engine(f"sqlite:///{tmp_path / 'enterprise-authority.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        db.add_all(
            [
                User(
                    id=1,
                    username="owner",
                    password="hash",
                    tenant_id=11,
                    tier="enterprise",
                ),
                User(
                    id=2,
                    username="foreign",
                    password="hash",
                    tenant_id=22,
                    tier="enterprise",
                ),
                User(
                    id=3,
                    username="coworker",
                    password="hash",
                    tenant_id=11,
                    tier="enterprise",
                ),
            ]
        )
        db.add_all(
            [
                SalesOrder(
                    id=101,
                    tenant_id=11,
                    order_no="ORDER-101",
                    state="confirmed",
                    total_amount=100,
                ),
                SalesOrder(
                    id=102,
                    tenant_id=22,
                    order_no="ORDER-102",
                    state="confirmed",
                    total_amount=200,
                ),
                Customer(id=201, tenant_id=11, customer_name="Customer A"),
                AiEmployeeProfile(employee_id="employee-a", user_id=10, owner_user_id=1),
                FinancialTransaction(id=301, tenant_id=11, transaction_type="income", amount=100),
                AgentTaskRecord(
                    task_id="task-a",
                    user_id="1",
                    tenant_id="11",
                    title="Delivery",
                    status="running",
                    created_at="2026-11-21T00:00:00+00:00",
                    updated_at="2026-11-21T00:00:00+00:00",
                ),
            ]
        )
        db.flush()
        db.add(
            SalesOrderItem(
                id=401,
                tenant_id=11,
                order_id=101,
                ordered_quantity=10,
                delivered_quantity=2,
                quantity=10,
                unit="件",
            )
        )
        db.commit()
    permissions = {
        "tool.sales.query",
        "customer.view",
        "employee.list",
        "tool.finance.ledger_query",
    }
    reader = AuthorityReader(
        sessions, permission_loader=lambda actor: permissions, business_session_factory=sessions
    )
    clock = [1795219200.0]
    service = ProjectionService(sessions, reader, clock=lambda: clock[0])
    with tenant_scope(11):
        yield service, sessions, clock, permissions
    engine.dispose()


def get(service, kind="order", entity_id="101", **kwargs):
    return service.get(kind, entity_id, tenant_id=11, actor_id="1", **kwargs)


def test_catalog_names_existing_authorities():
    catalog = {row["entity_type"]: row for row in entity_catalog()}
    assert set(catalog) == {"order", "customer", "employee", "task", "fund"}
    assert catalog["task"]["id_field"] == "task_id"
    assert all(row["read_only"] for row in catalog.values())


def test_fresh_projection_hash_items_and_expiry(world):
    service, sessions, clock, _ = world
    before = get(service)
    assert before["freshness"] == "fresh"
    assert before["state"]["remaining_quantity"] == "8.0000"
    assert before["state"]["delay_status"] == "unknown"
    assert before["evidence"][0]["row_id"] == "101"
    assert before["source_version"] == "sha256:" + before["evidence"][0]["content_sha256"]
    with tenant_scope(11), sessions() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = Decimal(5)
        db.commit()
    assert get(service)["retrieved_from"] == "projection"
    clock[0] += 31
    after = get(service)
    assert after["state"]["remaining_quantity"] == "5.0000"
    assert after["source_version"] != before["source_version"]
    assert after["observed_at"].endswith("+00:00")
    with tenant_scope(11), sessions() as db:
        assert db.get(SalesOrder, 101).state == "confirmed"


@pytest.mark.parametrize(
    "kind,identity",
    [
        ("customer", "201"),
        ("employee", "employee-a"),
        ("task", "task-a"),
        ("fund", "301"),
    ],
)
def test_existing_authorities_read_scoped(world, kind, identity):
    service, *_ = world
    assert get(service, kind, identity)["freshness"] == "fresh"
    refs = service.list_refs(kind, tenant_id=11, actor_id="1")
    assert refs["refs"] == [{"entity_type": kind, "entity_id": identity}]


def test_foreign_tenant_owner_and_rbac_cannot_reuse_cache(world):
    service, _, _, permissions = world
    get(service)
    assert get(service, entity_id="102")["freshness"] == "unknown"
    assert (
        service.get("employee", "employee-a", tenant_id=11, actor_id="3")["freshness"] == "unknown"
    )
    assert service.get("task", "task-a", tenant_id=11, actor_id="3")["freshness"] == "unknown"
    with pytest.raises(PermissionError):
        service.get("order", "101", tenant_id=22, actor_id="1")
    permissions.remove("tool.sales.query")
    with pytest.raises(PermissionError):
        get(service)


def test_mod_scope_and_owner_change_revalidated(world):
    service, sessions, *_ = world
    get(service, "employee", "employee-a")
    with sessions() as db:
        db.scalar(select(AiEmployeeProfile)).owner_user_id = 3
        db.commit()
    assert get(service, "employee", "employee-a")["freshness"] == "unknown"
    with pytest.raises(PermissionError):
        get(service, mod_id="another-mod")
    token = set_request_active_mod_id("mod-a")
    try:
        result = get(service, mod_id="mod-a")
        assert result["mod_id"] == "mod-a"
    finally:
        reset_request_active_mod_id(token)


def test_source_failure_does_not_return_stale_facts(world, monkeypatch):
    service, _, clock, _ = world
    get(service)
    clock[0] += 31

    def fail(*args):
        raise OperationalError("query", {}, RuntimeError("offline"))

    monkeypatch.setattr(service.reader, "read", fail)
    result = get(service)
    assert result["freshness"] == "unknown"
    assert result["state"] == {} and result["evidence"] == []


def test_mixed_units_are_not_added_as_one_metric(world):
    service, sessions, *_ = world
    with sessions() as db:
        db.add(
            SalesOrderItem(tenant_id=11, order_id=101, ordered_quantity=5, quantity=5, unit="箱")
        )
        db.commit()
    state = get(service)["state"]
    assert state["quantity_unit"] is None
    assert state["remaining_quantity"] is None


def test_scoped_event_invalidates_without_trusting_payload_and_dedupes(world):
    service, sessions, clock, _ = world
    get(service)
    payload = {
        "tenant_id": 11,
        "mod_id": "",
        "entity_type": "order",
        "entity_id": "101",
        "source_table": "sales_orders",
        "state": {"paid_amount": 999999},
    }
    ev = NeuroEvent(
        "enterprise.entity_changed",
        payload,
        metadata=EventMetadata(event_id="event-1", timestamp=clock[0]),
        preserve_queue_identity=True,
    )
    assert consume_entity_event(ev, service=service)
    assert not consume_entity_event(ev, service=service)
    actual = get(service)
    assert actual["retrieved_from"] == "authority"
    assert actual["state"]["paid_amount"] != "999999"
    assert actual["last_event_id"] == "event-1"
    older = NeuroEvent(
        "enterprise.entity_changed",
        payload,
        metadata=EventMetadata(event_id="old", timestamp=clock[0] - 10),
        preserve_queue_identity=True,
    )
    assert not consume_entity_event(older, service=service)
    payload.pop("tenant_id")
    assert not consume_entity_event(ev, service=service)
    with sessions() as db:
        assert db.scalar(select(EnterpriseEventCursor)).generation == 1


@pytest.fixture
def observer(monkeypatch):
    from app.infrastructure import enterprise_cognition_events as source_events

    calls = []
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.publish_neuro_event",
        lambda name, payload, domain: calls.append((name, payload)) or True,
    )
    source_events.install_source_observer()
    yield calls
    for name, handler in (
        ("after_flush", source_events._capture),
        ("after_commit", source_events._committed),
        ("after_soft_rollback", source_events._rolled_back),
    ):
        event.remove(Session, name, handler)


def test_observer_only_committed_changes_and_nested_rollback(world, observer):
    _, sessions, *_ = world
    with tenant_scope(11), sessions() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = 3
        db.flush()
        with pytest.raises(RuntimeError):
            with db.begin_nested():
                db.add(Customer(id=202, tenant_id=11, customer_name="rolled back"))
                db.flush()
                raise RuntimeError("rollback savepoint")
        assert observer == []
        db.commit()
    assert len(observer) == 1
    assert observer[0][1] == {
        "tenant_id": 11,
        "mod_id": "",
        "entity_type": "order",
        "entity_id": "101",
        "source_table": "sales_orders",
    }
    with tenant_scope(11), sessions() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = 4
        db.flush()
        db.rollback()
    assert len(observer) == 1


def test_observer_nested_commit_waits_for_outer_and_publish_failure_is_nonfatal(
    world, observer, monkeypatch
):
    _, sessions, *_ = world
    with tenant_scope(11), sessions() as db:
        with db.begin_nested():
            db.get(SalesOrderItem, 401).delivered_quantity = 6
        assert observer == []
        db.commit()
    assert len(observer) == 1

    def unavailable(*args):
        raise RuntimeError("bus offline")

    monkeypatch.setattr("app.neuro_bus.application_neuro_bridge.publish_neuro_event", unavailable)
    with tenant_scope(11), sessions() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = 7
        db.commit()
    with tenant_scope(11), sessions() as db:
        assert db.get(SalesOrderItem, 401).delivered_quantity == 7


def test_migration_and_bootstrap_provision_only_derived_tables():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.db.init_db import ensure_enterprise_cognition_bootstrap

    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/2026_11_21_enterprise_cognition.py"
    )
    spec = importlib.util.spec_from_file_location("enterprise_projection_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
    expected = {
        "enterprise_state_projections",
        "enterprise_event_cursors",
        "enterprise_goal_bindings",
    }
    assert set(inspect(engine).get_table_names()) == expected
    ensure_enterprise_cognition_bootstrap(engine, swallow_errors=False)
    assert set(inspect(engine).get_table_names()) == expected


def test_task_mod_binding_is_checked_before_cache(world):
    import json

    service, sessions, *_ = world
    with sessions() as db:
        task = db.scalar(select(AgentTaskRecord))
        task.active_run_id = "run-a"
        db.add(
            AgentRunRecord(
                run_id="run-a",
                user_id="1",
                status="running",
                message="delivery",
                payload_json=json.dumps(
                    {
                        "metadata": {
                            "runtime_context": {
                                "tenant_id": "11",
                                "mod_id": "mod-a",
                                "_mod_authorization": {"mod_id": "mod-a"},
                            }
                        }
                    }
                ),
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )
        db.commit()
    assert get(service, "task", "task-a")["freshness"] == "unknown"
    token = set_request_active_mod_id("mod-a")
    try:
        assert get(service, "task", "task-a", mod_id="mod-a")["freshness"] == "fresh"
        assert service.list_refs("task", tenant_id=11, actor_id="1", mod_id="mod-a")["refs"]
    finally:
        reset_request_active_mod_id(token)
    assert service.list_refs("task", tenant_id=11, actor_id="1")["refs"] == []


@pytest.mark.asyncio
async def test_committed_orm_change_reaches_running_neurobus_and_refreshes(world, monkeypatch):
    import asyncio
    import time

    from app.application.enterprise_cognition import projection
    from app.infrastructure import enterprise_cognition_events as source_events
    from app.mod_sdk import neuro_bus_runtime
    from app.neuro_bus import application_neuro_bridge
    from app.neuro_bus import bus as bus_module

    service, sessions, clock, _ = world
    clock[0] = time.time()
    before = get(service)
    bus = bus_module.NeuroBus()
    delivered = asyncio.Event()
    loop = asyncio.get_running_loop()
    original_consume = projection.consume_entity_event

    def consume_and_signal(event):
        result = original_consume(event, service=service)
        loop.call_soon_threadsafe(delivered.set)
        return result

    monkeypatch.setattr(projection, "consume_entity_event", consume_and_signal)
    monkeypatch.setattr(application_neuro_bridge, "_stack_on", lambda: True)
    monkeypatch.setattr(neuro_bus_runtime, "is_neuro_bus_runtime_via_mod_enabled", lambda: False)
    monkeypatch.setattr(bus_module, "get_neuro_bus", lambda: bus)
    count = projection.register_enterprise_subscriptions(bus)
    assert count == projection.register_enterprise_subscriptions(bus)
    await bus.start()
    try:
        with tenant_scope(11), sessions() as db:
            db.get(SalesOrderItem, 401).delivered_quantity = 9
            db.commit()
        await asyncio.wait_for(delivered.wait(), timeout=2)
        after = get(service)
        assert after["retrieved_from"] == "authority"
        assert after["state"]["remaining_quantity"] == "1.0000"
        assert after["source_version"] != before["source_version"]
        assert after["last_event_id"]
    finally:
        await bus.stop()
        for name, handler in (
            ("after_flush", source_events._capture),
            ("after_commit", source_events._committed),
            ("after_soft_rollback", source_events._rolled_back),
        ):
            event.remove(Session, name, handler)


def test_employee_observation_reads_scoped_role_declarations_and_persisted_load(world, monkeypatch):
    service, sessions, clock, _ = world
    from app.infrastructure.mods import employee_registry

    class Registry:
        def list_packs(self):
            return [
                {
                    "pack_id": "employee-a",
                    "version": "1.2.3",
                    "employee": {"capabilities": ["Excel", "Finance review", "excel"]},
                },
                {
                    "pack_id": "unrelated",
                    "employee": {"capabilities": ["unrelated-capability"]},
                },
            ]

    monkeypatch.setattr(employee_registry, "get_employee_registry", Registry)
    with sessions() as db:
        db.add(
            User(
                id=10,
                username="ai-employee:employee-a",
                password="hash",
                tenant_id=11,
                role="ai_employee",
                is_active=True,
            )
        )
        for status in ("running", "pending", "awaiting_approval", "unknown", "success"):
            db.add(EmployeeRunLog(employee_id="employee-a", tenant_id=11, user_id=1, status=status))
        db.add_all(
            [
                EmployeeRunLog(employee_id="employee-a", tenant_id=11, user_id=3, status="running"),
                EmployeeRunLog(employee_id="other", tenant_id=11, user_id=1, status="running"),
            ]
        )
        db.commit()
    with tenant_scope(22), sessions() as db:
        db.add(EmployeeRunLog(employee_id="employee-a", tenant_id=22, user_id=2, status="running"))
        db.commit()
    first = get(service, "employee", "employee-a", force_refresh=True)
    state = first["state"]
    assert state["role"] == "ai_employee" and state["identity_active"] is True
    assert state["capability_evidence"] == {
        "status": "declared",
        "source": "installed_employee_pack",
        "declared": ["excel", "finance_review"],
        "pack_version": "1.2.3",
        "independent_verified": False,
    }
    assert state["workload"]["open_count"] == 4
    assert state["workload"]["running_count"] == 1
    assert state["workload"]["unresolved_count"] == 1
    assert state["workload"]["capacity_verified"] is False
    assert state["workload"]["counts"]["succeeded"] == 1
    with sessions() as db:
        db.add(EmployeeRunLog(employee_id="employee-a", tenant_id=11, user_id=1, status="running"))
        db.commit()
    clock[0] += 31
    second = get(service, "employee", "employee-a")
    assert second["state"]["workload"]["open_count"] == 5
    assert second["source_version"] != first["source_version"]


def test_employee_observation_missing_evidence_does_not_prove_availability(world, monkeypatch):
    service, sessions, *_ = world
    from app.infrastructure.mods import employee_registry

    class Registry:
        def list_packs(self):
            return []

    monkeypatch.setattr(employee_registry, "get_employee_registry", Registry)
    state = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert state["role"] is None and state["identity_active"] is None
    assert state["capability_evidence"]["status"] == "unknown"
    assert state["workload"]["status"] == "no_history"
    assert state["workload"]["capacity_verified"] is False
    with sessions() as db:
        db.scalar(select(AiEmployeeProfile)).mod_id = "sales"
        db.commit()
    state = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert state["workload"]["status"] == "unknown"
    assert "open_count" not in state["workload"]
    assert state["capability_evidence"]["status"] == "unknown"
