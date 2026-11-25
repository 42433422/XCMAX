"""Authority isolation, expiry, read-only projection and commit-only event contract."""

from __future__ import annotations

import importlib.util
import json
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
    EnterpriseStateProjection,
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
    assert set(catalog) == {
        "order",
        "customer",
        "employee",
        "task",
        "fund",
        "inventory",
        "production",
        "supplier",
        "purchase_order",
        "purchase_inbound",
        "journal_entry",
    }
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
        raise ConnectionError("bus offline")

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
        # Keep observation order monotonic without expiring the cache.
        clock[0] += 1
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
    service, sessions, clock, _ = world
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
    clock[0] += 1
    state = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert state["workload"]["status"] == "unknown"
    assert "open_count" not in state["workload"]
    assert state["capability_evidence"]["status"] == "unknown"


def test_world_history_replays_only_authorized_observations(world):
    service, sessions, clock, permissions = world
    before = get(service)
    assert before["knowledge_kind"] == "fact"
    with sessions.begin() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = Decimal(5)
    clock[0] += 31
    after = get(service)
    assert after["state"]["remaining_quantity"] == "5.0000"
    historical = get(service, as_of=before["observed_at"])
    assert historical["observation"]["state"]["remaining_quantity"] == "8.0000"
    assert historical["observation"]["source_version"] == before["source_version"]
    assert historical["observation"]["freshness"] == "historical"
    assert historical["business_validity_verified"] is False
    assert historical["current_state_verified"] is False
    assert get(service, as_of="2000-01-01T00:00:00+00:00")["knowledge_kind"] == "unknown"
    other = service.get("order", "101", tenant_id=11, actor_id="3", as_of=after["observed_at"])
    assert other["knowledge_kind"] == "unknown"
    permissions.remove("tool.sales.query")
    with pytest.raises(PermissionError):
        get(service, as_of=before["observed_at"])


def test_conflicting_observations_are_retained_not_last_writer_wins(world):
    service, sessions, clock, _ = world
    first = get(service)
    with sessions.begin() as db:
        db.get(SalesOrderItem, 401).delivered_quantity = Decimal(5)
    conflict = get(service, force_refresh=True)
    assert conflict["knowledge_kind"] == "unknown"
    assert conflict["reason_code"] == "conflicting_observation_order"
    history = get(service, as_of=first["observed_at"])
    assert history["knowledge_kind"] == "unknown"
    assert history["reason_code"] == "conflicting_observations"
    assert {x["state"]["remaining_quantity"] for x in history["conflict_evidence"]} == {
        "8.0000",
        "5.0000",
    }
    clock[0] += 1
    assert get(service)["state"]["remaining_quantity"] == "5.0000"
    assert get(service, as_of=first["observed_at"])["knowledge_kind"] == "unknown"


def test_conditional_delivery_scenario_does_not_modify_authority(world):
    from app.domain.enterprise_cognition.world_observation import delivery_scenario

    service, sessions, *_ = world
    before = get(service)
    scenario = delivery_scenario(before, "3")
    assert scenario["knowledge_kind"] == "prediction"
    assert Decimal(scenario["value"]) == 5
    assert scenario["probability"] is None
    assert scenario["causal_effect_verified"] is False
    assert scenario["baseline_source_version"] == before["source_version"]
    assert delivery_scenario(before, "99")["knowledge_kind"] == "unknown"
    assert delivery_scenario({"freshness": "unknown"}, "3")["knowledge_kind"] == "unknown"
    with sessions() as db:
        assert db.get(SalesOrderItem, 401).delivered_quantity == 2


def test_world_reads_inventory_movements_and_manufacturing_rows(world, observer):
    from datetime import UTC, datetime

    from app.db.models.inventory import InventoryTransaction, Warehouse
    from app.db.models.mrp import Bom, ManufacturingOrder, ManufacturingOrderLine
    from app.db.models.product import Product

    service, sessions, clock, permissions = world
    with sessions.begin() as db:
        db.add_all(
            [
                Product(id=501, tenant_id=11, name="Finished product"),
                Warehouse(id=502, tenant_id=11, code="WORLD-W", name="Warehouse"),
            ]
        )
        db.flush()
        db.add(Bom(id=503, tenant_id=11, code="WORLD-B", product_id=501, product_name="Finished"))
        db.flush()
        db.add_all(
            [
                InventoryTransaction(
                    id=504,
                    tenant_id=11,
                    transaction_type="in",
                    product_id=501,
                    warehouse_id=502,
                    quantity=Decimal(3),
                    before_quantity=Decimal(1),
                    after_quantity=Decimal(4),
                    transaction_date=datetime.now(UTC),
                ),
                ManufacturingOrder(
                    id=505,
                    tenant_id=11,
                    order_no="WORLD-M",
                    bom_id=503,
                    product_id=501,
                    product_name="Finished",
                    warehouse_id=502,
                    quantity=2,
                    status="confirmed",
                ),
            ]
        )
        db.flush()
        db.add(
            ManufacturingOrderLine(
                id=506,
                tenant_id=11,
                order_id=505,
                product_id=501,
                product_name="Finished",
                quantity=Decimal(2),
                consumed_quantity=Decimal(0),
            )
        )
    with pytest.raises(PermissionError):
        get(service, "inventory", "504")
    with pytest.raises(PermissionError):
        get(service, "production", "505")
    permissions.update({"tool.inventory.query_transactions", "tool.mrp.query_orders"})
    movement = get(service, "inventory", "504")
    assert movement["knowledge_kind"] == "fact"
    assert Decimal(movement["state"]["after_quantity"]) == 4
    assert movement["source_last_changed"] is None
    # Same source row edited within the TTL: an old memory reference cannot win.
    from app.application.enterprise_cognition.service import (
        make_fact_reference,
        verify_source_reference,
    )

    with sessions.begin() as db:
        db.get(InventoryTransaction, 504).after_quantity = Decimal(6)
    clock[0] += 1
    changed_movement = get(service, "inventory", "504", force_refresh=True)
    assert changed_movement["source_version"] != movement["source_version"]
    assert verify_source_reference(
        changed_movement,
        movement["source_version"],
        make_fact_reference(movement)["fact_token"],
    )["status"] == "superseded"
    assert get(service, "production", "505")["state"]["status"] == "confirmed"
    with sessions.begin() as db:
        db.get(ManufacturingOrderLine, 506).consumed_quantity = Decimal(1)
    assert any(
        payload["entity_type"] == "production" and payload["entity_id"] == "505"
        for _, payload in observer
    )
    clock[0] += 31
    updated = get(service, "production", "505")
    assert Decimal(updated["state"]["lines"][0]["consumed_quantity"]) == 1
    assert get(service, "inventory", "999")["knowledge_kind"] == "unknown"


@pytest.mark.parametrize(
    "cutoff",
    ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"],
)
def test_historical_query_out_of_range_utc_fails_closed(world, cutoff):
    service, *_ = world
    assert get(service)["knowledge_kind"] == "fact"
    response = get(service, as_of=cutoff)
    assert response["knowledge_kind"] == "unknown"
    assert response["reason_code"] == "observation_history_unavailable"


def test_purchase_authority_read_permissions_and_committed_changes(world, observer):
    from datetime import date

    from app.db.models.inventory import Warehouse
    from app.db.models.product import Product
    from app.db.models.purchase import (
        PurchaseInbound,
        PurchaseInboundItem,
        PurchaseOrder,
        PurchaseOrderItem,
        Supplier,
    )

    service, sessions, clock, permissions = world
    with sessions.begin() as db:
        db.add_all(
            [
                Supplier(id=610, tenant_id=11, code="WORLD-S", name="Supplier A"),
                Warehouse(id=611, tenant_id=11, code="WORLD-P-W", name="Purchasing warehouse"),
                Product(id=612, tenant_id=11, name="Material"),
            ]
        )
        db.flush()
        db.add_all(
            [
                PurchaseOrder(
                    id=613,
                    tenant_id=11,
                    order_no="WORLD-P-613",
                    supplier_id=610,
                    warehouse_id=611,
                    order_date=date(2026, 11, 24),
                    status="approved",
                ),
                PurchaseInbound(
                    id=614,
                    tenant_id=11,
                    inbound_no="WORLD-I-614",
                    supplier_id=610,
                    warehouse_id=611,
                    order_id=613,
                    inbound_date=date(2026, 11, 24),
                    status="completed",
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                PurchaseOrderItem(
                    id=615,
                    tenant_id=11,
                    order_id=613,
                    product_id=612,
                    quantity=Decimal(5),
                    received_quantity=Decimal(2),
                    unit="件",
                ),
                PurchaseInboundItem(
                    id=616,
                    tenant_id=11,
                    inbound_id=614,
                    product_id=612,
                    quantity=Decimal(2),
                    unit="件",
                ),
            ]
        )
    # The other tenant's row is committed under its own tenant context, never
    # smuggled through the current caller's tenant-scoped write session.
    with tenant_scope(22), sessions.begin() as db:
        db.add(Supplier(id=617, tenant_id=22, code="WORLD-OTHER-S", name="Foreign Supplier"))
    for kind, identity in (
        ("supplier", "610"),
        ("purchase_order", "613"),
        ("purchase_inbound", "614"),
    ):
        with pytest.raises(PermissionError):
            get(service, kind, identity)
    permissions.update(
        {
            "tool.purchase.query_suppliers",
            "tool.purchase.query_orders",
            "tool.purchase.query_inbounds",
        }
    )
    supplier = get(service, "supplier", "610")
    assert supplier["knowledge_kind"] == "fact"
    assert supplier["state"]["name"] == "Supplier A"
    assert "contact_phone" not in supplier["state"]
    purchase = get(service, "purchase_order", "613")
    assert purchase["knowledge_kind"] == "fact"
    assert purchase["state"]["items"][0]["received_quantity"] == "2.0000"
    assert purchase["state"]["items_truncated"] is False
    inbound = get(service, "purchase_inbound", "614")
    assert inbound["state"]["items"][0]["quantity"] == "2.0000"
    assert get(service, "purchase_order", "999")["knowledge_kind"] == "unknown"
    assert get(service, "supplier", "617")["knowledge_kind"] == "unknown"
    with sessions.begin() as db:
        db.get(PurchaseOrderItem, 615).received_quantity = Decimal(4)
    assert any(
        payload["entity_type"] == "purchase_order" and payload["entity_id"] == "613"
        for _, payload in observer
    )
    clock[0] += 31
    after = get(service, "purchase_order", "613")
    assert after["state"]["items"][0]["received_quantity"] == "4.0000"
    assert after["source_version"] != purchase["source_version"]
    permissions.remove("tool.purchase.query_orders")
    with pytest.raises(PermissionError):
        get(service, "purchase_order", "613")


def test_procurement_references_are_unverified_pointers_not_facts_about_targets():
    from app.domain.enterprise_cognition.world_observation import relationship_references

    source = {
        "knowledge_kind": "fact",
        "entity_type": "purchase_inbound",
        "state": {"order_id": 613, "supplier_id": 610, "warehouse_id": 611},
        "evidence": [{"source": "purchase_inbounds", "row_id": "614"}],
    }
    refs = relationship_references(source)
    assert {(row["entity_type"], row["entity_id"]) for row in refs} == {
        ("purchase_order", "613"),
        ("supplier", "610"),
        ("warehouse", "611"),
    }
    assert all(row["target_visibility_verified"] is False for row in refs)
    assert all(row["evidence"] == source["evidence"] for row in refs)
    assert relationship_references({**source, "knowledge_kind": "unknown"}) == []


def test_tampered_current_projection_is_not_reused_as_authoritative_fact(world):
    service, sessions, *_ = world
    original = get(service)
    assert original["knowledge_kind"] == "fact"
    with sessions.begin() as db:
        row = db.scalar(select(EnterpriseStateProjection))
        saved = row.snapshot_json
        decoded = json.loads(saved)
        decoded["state"]["remaining_quantity"] = "999"
        row.snapshot_json = json.dumps(decoded, ensure_ascii=False)
    unsafe = get(service)
    assert unsafe["knowledge_kind"] == "unknown"
    assert unsafe["reason_code"] == "observation_history_unavailable"
    assert unsafe["evidence"] == []
    with sessions.begin() as db:
        db.scalar(select(EnterpriseStateProjection)).snapshot_json = saved
    assert get(service)["state"]["remaining_quantity"] == original["state"]["remaining_quantity"]


def test_tampered_history_cannot_validate_a_cached_current_fact(world):
    service, sessions, *_ = world
    assert get(service)["knowledge_kind"] == "fact"
    with sessions.begin() as db:
        row = db.scalar(select(EnterpriseStateProjection))
        tampered = json.loads(row.snapshot_json)
        tampered["_observation_history"][0]["state"]["remaining_quantity"] = "1000"
        row.snapshot_json = json.dumps(tampered, ensure_ascii=False)
    unsafe = get(service)
    assert unsafe["knowledge_kind"] == "unknown"
    assert unsafe["reason_code"] == "observation_history_unavailable"


def test_journal_entry_authority_is_scoped_without_invented_account_balances(world, observer):
    from datetime import date

    from app.db.models.accounting import JournalEntry, JournalEntryLine

    service, sessions, clock, permissions = world
    with sessions.begin() as db:
        db.add(
            JournalEntry(
                id=620,
                tenant_id=11,
                entry_no="WORLD-J-620",
                journal_date=date(2026, 11, 24),
                status="posted",
                debit_total=Decimal("10.00"),
                credit_total=Decimal("10.00"),
            )
        )
        db.flush()
        db.add_all(
            [
                JournalEntryLine(
                    id=621,
                    tenant_id=11,
                    entry_id=620,
                    account_code="1122",
                    debit=Decimal("10.00"),
                    credit=Decimal("0.00"),
                ),
                JournalEntryLine(
                    id=622,
                    tenant_id=11,
                    entry_id=620,
                    account_code="6001",
                    debit=Decimal("0.00"),
                    credit=Decimal("10.00"),
                ),
            ]
        )
    permissions.remove("tool.finance.ledger_query")
    with pytest.raises(PermissionError):
        get(service, "journal_entry", "620")
    permissions.add("tool.finance.ledger_query")
    before = get(service, "journal_entry", "620")
    assert before["knowledge_kind"] == "fact"
    assert before["state"]["debit_total"] == "10.00"
    assert before["state"]["credit_total"] == "10.00"
    assert before["state"]["lines"][0]["account_code"] == "1122"
    assert before["state"]["lines"][0]["debit"] == "10.00"
    assert before["state"]["lines_truncated"] is False
    assert "cash_balance" not in before["state"]
    assert "accounts_receivable" not in before["state"]
    assert "partner_name" not in before["state"]["lines"][0]
    assert get(service, "journal_entry", "999")["knowledge_kind"] == "unknown"
    with sessions.begin() as db:
        db.get(JournalEntryLine, 621).account_code = "1123"
    assert any(
        payload["entity_type"] == "journal_entry" and payload["entity_id"] == "620"
        for _, payload in observer
    )
    clock[0] += 31
    after = get(service, "journal_entry", "620")
    assert after["state"]["lines"][0]["account_code"] == "1123"
    assert after["source_version"] != before["source_version"]
    permissions.remove("tool.finance.ledger_query")
    with pytest.raises(PermissionError):
        get(service, "journal_entry", "620")


@pytest.mark.parametrize(
    "entity_type,entity_id,model,field,replacement",
    [
        ("customer", "201", Customer, "customer_name", "Customer A corrected"),
        ("fund", "301", FinancialTransaction, "amount", Decimal(95)),
    ],
)
def test_customer_and_finance_remembered_facts_are_superseded_by_erp(
    world, entity_type, entity_id, model, field, replacement
):
    from app.application.enterprise_cognition.service import (
        make_fact_reference,
        verify_source_reference,
    )

    service, sessions, clock, _ = world
    before = get(service, entity_type, entity_id)
    assert before["knowledge_kind"] == "fact"
    with sessions.begin() as db:
        setattr(db.get(model, int(entity_id)), field, replacement)
    clock[0] += 1  # preserve observation ordering, but stay within the 30s TTL
    after = get(service, entity_type, entity_id, force_refresh=True)
    assert after["retrieved_from"] == "authority"
    assert after["source_version"] != before["source_version"]
    superseded = verify_source_reference(
        after, before["source_version"], make_fact_reference(before)["fact_token"]
    )
    assert superseded["status"] == "superseded"
    assert superseded["memory_reuse_allowed"] is False
    assert superseded["requires_reconciliation"] is True
    assert verify_source_reference(
        after, after["source_version"], make_fact_reference(after)["fact_token"]
    )["status"] == "current"
