"""Business model contracts project the same live account schema as execution."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.tools import workflow
from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_model_catalog_is_scoped_and_rechecks_permission_revocation(trusted_actor):
    from app.application.capability_catalog import workflow_registry
    from app.db.models.permission import Role

    actor = trusted_actor(permissions=["customer.view"])
    tools = workflow.get_workflow_tool_registry(actor.context)
    assert [row["function"]["name"] for row in tools] == [ERP_CAPABILITY_TOOL_NAME]
    branches = tools[0]["function"]["parameters"]["anyOf"]
    reader = next(
        row for row in branches if row["properties"]["tool_id"]["enum"] == ["business_db"]
    )
    canonical = workflow_registry(actor.context)["business_db"]["actions"]["read"]
    assert reader["properties"]["params"] == canonical["input_schema"]
    assert reader["properties"]["params"]["properties"]["entity"]["enum"] == ["customers"]
    with actor.factory.begin() as db:
        db.query(Role).filter_by(name="user").one().permissions = []
    refreshed = workflow.get_workflow_tool_registry(actor.context)
    assert all(
        row["properties"]["tool_id"]["enum"] != ["business_db"]
        for spec in refreshed
        for row in spec["function"]["parameters"]["anyOf"]
    )
    assert workflow.get_workflow_tool_registry() == []


@pytest.mark.parametrize(
    "name", ["business_db_read", "business_db_write", "delete_order", "update_customer"]
)
def test_retired_alias_has_no_dispatch(name, monkeypatch):
    from app.application.tools.workflow_tools import adapters

    for port in ("employee", "native", "legacy_employee"):
        monkeypatch.setattr(adapters, port, lambda *_: None)
    result = json.loads(workflow.execute_workflow_tool(name, {"confirm": True}))
    assert result == {
        "success": False,
        "error": "unknown_tool",
        "error_code": "unknown_tool",
        "execution_status": "not_started",
        "execution_state": "not_started",
        "retryable": False,
        "tool": name,
    }


@pytest.mark.parametrize(
    "args",
    [
        {"tool_id": "business_db", "action": "read", "params": {"entity": "products"}},
        {
            "tool_id": "business_db",
            "action": "write",
            "params": {"entity": "customers", "operation": "create", "payload": {}},
        },
    ],
)
def test_employee_cannot_escape_projected_action_schema(args, trusted_actor, monkeypatch):
    from app.application.employee_runtime.agent_runner import _xiaox_employee_tool_scope
    from app.application.employee_runtime.tool_scope import resolve_employee_tools

    actor = trusted_actor(permissions=["customer.view"])
    tools = resolve_employee_tools("e", {}, {"tools": ["business_db"]}, actor.context)
    execute = Mock(side_effect=AssertionError("out-of-scope model action must not dispatch"))
    allowed, check = _xiaox_employee_tool_scope(tools, execute)
    assert allowed == ["business_db.read"]
    assert check(args["tool_id"], args["action"], args["params"])["ok"] is False
    execute.assert_not_called()


def test_employee_agent_passes_bound_context_to_discovery(trusted_actor):
    from app.application.employee_runtime.agent import EmployeeAgent

    actor = trusted_actor(permissions=["customer.view"])
    config = {"tools": ["business_db"]}
    specs = EmployeeAgent("e")._build_agent_tools({}, config, actor.context)
    assert {
        tuple(row["properties"]["tool_id"]["enum"])
        for row in specs[0]["function"]["parameters"]["anyOf"]
    } == {("business_db",)}


def test_employee_persists_projected_allowlist_for_shared_approval(trusted_actor, monkeypatch):
    from app.application.agent_runtime import gateway
    from app.application.employee_runtime.agent_runner import run_employee_agent_loop
    from app.application.employee_runtime.tool_scope import resolve_employee_tools

    actor = trusted_actor(permissions=["customer.view"])
    tools = resolve_employee_tools("e", {}, {"tools": ["business_db"]}, actor.context)
    runtime = Mock(return_value={"runtime": "codex", "ok": True})
    monkeypatch.setattr(gateway, "run_runtime_task", runtime)
    gate = Mock(return_value={"ok": True})
    run_employee_agent_loop(
        employee_id="e",
        system_prompt="",
        task="query",
        tools=tools,
        runtime_context=actor.context,
        gate=gate,
    )
    runtime.assert_called_once()
    invocation = runtime.call_args.kwargs
    assert (
        invocation["runtime_context"]["_actor_authorization"]
        == actor.context["_actor_authorization"]
    )
    assert invocation["allowed_actions"] == ["business_db.read"]
    assert invocation["gate"]("business_db", "read", {"entity": "customers"})["ok"] is True
    gate.assert_called_once_with(
        ERP_CAPABILITY_TOOL_NAME,
        {"tool_id": "business_db", "action": "read", "params": {"entity": "customers"}},
    )
    assert "employee_tool_allowlist" not in actor.context


@pytest.mark.parametrize("entity", ["customers", "products", "materials", "shipment_records"])
@pytest.mark.parametrize("by_id", [False, True], ids=["list", "id"])
def test_business_reads_never_expose_unowned_migration_rows(
    trusted_actor, monkeypatch, entity, by_id
):
    from sqlalchemy import insert

    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.business_db_write_verification import _model_config
    from app.infrastructure.tenant_scope import current_tenant_id, owned_tenant_id, tenant_scope

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
    actor = trusted_actor(
        permissions=["customer.view", "product.view", "material.view", "shipment.view"]
    )
    model, _, _ = _model_config(entity)
    rows = []
    for record_id, tenant in ((70, 7), (80, 8), (90, None)):
        row = {"id": record_id, "tenant_id": tenant}
        if entity == "customers":
            row["unit_name"] = f"customer-{record_id}"
        elif entity == "shipment_records":
            row.update(
                purchase_unit=f"customer-{record_id}",
                product_name="product",
                quantity_kg=10,
                quantity_tins=1,
            )
        else:
            row["name"] = f"item-{record_id}"
            if entity == "materials":
                row["material_code"] = f"code-{record_id}"
        rows.append(row)
    with actor.factory.kw["bind"].begin() as db:
        db.execute(insert(model.__table__), rows)

    def read(record_id=None):
        params = {"entity": entity}
        if record_id is not None:
            params["id"] = record_id
        return AgentToolExecutor().execute(
            AgentStep(node_id="read", tool_id="business_db", action="read", params=params),
            runtime_context=actor.context,
        )

    with tenant_scope(999):
        result = read(70 if by_id else None)
        assert result["success"] is True, result
        assert {row["id"] for row in result["data"]} == {70}
        if by_id:
            assert read(80)["data"] == []
            assert read(90)["data"] == []
        assert current_tenant_id() == 999
        assert owned_tenant_id() is None


def test_business_read_discovery_and_execution_require_owned_tenant(trusted_actor):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.capability_catalog import workflow_registry

    actor = trusted_actor(tenant_id=None, role="admin", tier="admin")
    assert "business_db" not in workflow_registry(actor.context)
    result = AgentToolExecutor().execute(
        AgentStep(
            node_id="read", tool_id="business_db", action="read", params={"entity": "customers"}
        ),
        runtime_context=actor.context,
    )
    assert result["success"] is False
    assert result["reason"] == "owned_tenant_required"


@pytest.mark.parametrize("sku", ["personal", None], ids=["personal", "unset"])
def test_product_discovery_uses_the_same_existing_sku_gate_as_execution(
    trusted_actor, monkeypatch, sku
):
    from app.application.agent_orchestrator.run_models import AgentStep
    from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
    from app.application.capability_catalog import workflow_registry

    for name in (
        "XCAGI_PRODUCT_SKU",
        "XCAGI_PRODUCT_SKU_FILE",
        "XCAGI_RESOURCES_DIR",
        "XCAGI_DESKTOP_RESOURCES",
    ):
        monkeypatch.delenv(name, raising=False)
    if sku:
        monkeypatch.setenv("XCAGI_PRODUCT_SKU", sku)
    actor = trusted_actor(permissions=["product.view", "customer.view"])
    metadata = workflow_registry(actor.context)["business_db"]["actions"]["read"]
    entities = metadata["input_schema"]["properties"]["entity"]["enum"]
    executor = AgentToolExecutor()
    product = executor.execute(
        AgentStep(
            node_id="products", tool_id="business_db", action="read", params={"entity": "products"}
        ),
        runtime_context=actor.context,
    )
    assert product["success"] is False and product["error_code"] == "tool_permission_denied"
    customer = executor.execute(
        AgentStep(
            node_id="customers",
            tool_id="business_db",
            action="read",
            params={"entity": "customers"},
        ),
        runtime_context=actor.context,
    )
    assert "customers" in entities and customer["success"] is True, customer
    assert "products" not in entities


@pytest.mark.parametrize(
    "tool_id,operation",
    [
        ("business_db", "update"),
        ("business_db", "delete"),
        ("shipment_records", "update"),
        ("shipment_records", "delete"),
        ("shipment_records", "clear"),
    ],
    ids=["business-update", "business-delete", "direct-update", "direct-delete", "direct-clear"],
)
@pytest.mark.parametrize("target_tenant", [7, None, 8], ids=["owned", "legacy-null", "foreign"])
def test_approved_business_write_rechecks_target_ownership_before_effect(
    trusted_actor, monkeypatch, local_tools, tool_id, operation, target_tenant
):
    from sqlalchemy import insert, select, update

    from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
    from app.application.agent_orchestrator.approval_grant import (
        consume_approval_grant,
        issue_approval_grant,
    )
    from app.application.shipment_app_service import ShipmentApplicationService
    from app.application.tools.registered_capabilities import execute_registered_capability
    from app.db.models import ShipmentRecord
    from app.infrastructure.persistence.shipment_record_command_impl import (
        SQLAlchemyShipmentRecordCommand,
    )
    from app.infrastructure.persistence.shipment_record_query_impl import (
        SQLAlchemyShipmentRecordQuery,
    )
    from app.infrastructure.repositories.shipment_repository_impl import (
        SQLAlchemyShipmentRepository,
    )
    from app.infrastructure.tenant_scope import owned_tenant_id, tenant_scope

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("XCAGI_TENANT_ALLOW_LEGACY_NULL_VISIBLE", "1")
    actor = trusted_actor(role="admin")
    repository = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repository,
    )
    service = ShipmentApplicationService(
        SQLAlchemyShipmentRepository(),
        record_query=SQLAlchemyShipmentRecordQuery(),
        record_command=SQLAlchemyShipmentRecordCommand(),
    )
    monkeypatch.setattr("app.bootstrap.get_shipment_application_service_core", lambda: service)
    engine = actor.factory.kw["bind"]
    table = ShipmentRecord.__table__
    with engine.begin() as db:
        db.execute(
            insert(table),
            {
                "id": 70,
                "tenant_id": actor.tenant_id,
                "purchase_unit": "owned-customer",
                "product_name": "owned-product",
                "quantity_kg": 10,
                "quantity_tins": 1,
                "status": "pending",
            },
        )
    payload = {"id": 70}
    if operation == "update":
        payload["changes"] = {"status": "printed"}
    if tool_id == "business_db":
        action = "write"
        params = {"entity": "shipment_records", "operation": operation, "payload": payload}
    else:
        action = operation
        params = {} if operation == "clear" else {"id": 70}
        if operation == "update":
            params["status"] = "printed"
    response = json.loads(
        execute_registered_capability(
            {"tool_id": tool_id, "action": action, "params": params},
            runtime_context={
                **actor.context,
                "idempotency_key": f"approved-write-{tool_id}-{target_tenant}-{operation}",
            },
        )
    )
    run = repository.get(response["run_id"])
    assert run.status == "waiting_user", response
    assert run.tool_calls == []
    assert owned_tenant_id() is None
    # A signed plan binds the reviewed ID and fields, not ownership of the row
    # at a later execution time. The actual adapter must recheck that boundary.
    with engine.begin() as db:
        db.execute(update(table).where(table.c.id == 70).values(tenant_id=target_tenant))
    with tenant_scope(actor.tenant_id):
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        claims = consume_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        done = AgentOrchestrator(repository=repository).continue_run(
            run.run_id,
            approved_by=str(actor.user_id),
            approved_step_id=claims["step_id"],
            runtime_context=run.metadata["runtime_context"],
            approval_request_id=run.metadata["approval_request_id"],
        )
    with engine.connect() as db:
        row = db.execute(select(table.c.tenant_id, table.c.status).where(table.c.id == 70)).first()
    if target_tenant == actor.tenant_id:
        assert (
            row is None
            if operation in {"delete", "clear"}
            else tuple(row) == (actor.tenant_id, "printed")
        )
        assert done.tool_calls[0].output["success"] is True, done.tool_calls[0].output
    else:
        assert row is not None and tuple(row) == (target_tenant, "pending"), done.steps[0].output
        if operation != "clear":
            assert done.steps[0].output.get("success") is not True
