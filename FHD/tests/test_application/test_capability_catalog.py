"""Execution, model and AIOPEN discovery share a live account contract."""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import FastAPI

from app.application.agent_orchestrator import tool_spec
from app.application.capability_catalog import (
    capability_entries,
    discover_capabilities,
    workflow_registry,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_projection_preserves_execution_schema_and_cannot_mutate_authority():
    registry = workflow_registry()
    spec = tool_spec.get_tool_action_spec("customers", "create")
    assert registry["customers"]["actions"]["create"]["input_schema"] == spec.input_schema
    registry["customers"]["actions"]["create"]["input_schema"]["required"] = []
    assert tool_spec.get_tool_action_spec("customers", "create").required_params == ["unit_name"]
    assert "import_excel_to_database" not in registry
    assert "aiopen" not in registry
    ids = [entry["capability_id"] for entry in capability_entries()]
    assert len(ids) == len(set(ids))
    assert ids.count("catalog_products_v1.append_price") == 1


def test_discovery_uses_live_permissions_and_entity_scope(trusted_actor):
    actor = trusted_actor(permissions=["customer.view"])
    result = discover_capabilities(actor.context, limit=500)
    assert result["success"]
    capabilities = {entry["capability_id"]: entry for entry in result["capabilities"]}
    assert "customers.query" not in capabilities
    assert "customers.create" not in capabilities
    read = capabilities["business_db.read"]
    assert read["input_schema"]["properties"]["entity"]["enum"] == ["customers"]
    assert "business_db.write" not in capabilities
    from app.application.workflow.llm_plan_generation import _tool_specs

    model_tools = _tool_specs(workflow_registry(actor.context))
    model_reader = next(row for row in model_tools if row["tool_id"] == "business_db")
    model_read = next(row for row in model_reader["actions"] if row["action"] == "read")
    assert model_read["input_schema"]["properties"]["entity"]["enum"] == ["customers"]
    assert result["employees"] == []

    from app.db.models.permission import Role

    with actor.factory.begin() as db:
        db.query(Role).filter_by(name="user").one().permissions = []
    refreshed = discover_capabilities(actor.context, limit=500)
    assert refreshed["success"]
    assert "customers.query" not in {row["capability_id"] for row in refreshed["capabilities"]}
    assert "business_db.read" not in {row["capability_id"] for row in refreshed["capabilities"]}


def test_platform_discovery_and_admission_share_current_approval_policy(trusted_actor, monkeypatch):
    import json
    from unittest.mock import Mock

    from app.application.tools.registered_capabilities import execute_registered_capability
    from app.application.workflow.approval_service import ApprovalService
    from app.infrastructure.tenant_scope import tenant_scope

    actor = trusted_actor(tenant_id=None, role="admin", tier="admin")
    registry = workflow_registry(actor.context)
    assert "list" in registry["print"]["actions"]
    assert "print_document" not in registry["print"]["actions"]
    assert "batch_delete" not in (registry.get("products") or {}).get("actions", {})
    assert discover_capabilities(actor.context)["employees"] == []
    monkeypatch.setattr(
        ApprovalService,
        "get_approval_required_nodes",
        lambda self, plan: [
            node for node in plan.nodes if (node.tool_id, node.action) == ("print", "list")
        ],
    )
    assert "list" not in (workflow_registry(actor.context).get("print") or {}).get("actions", {})
    publish = Mock(side_effect=AssertionError("unpersistable approval cannot publish a task"))
    monkeypatch.setattr("app.application.agent_orchestrator.unified_task.publish_task_run", publish)
    with tenant_scope(None):
        response = json.loads(
            execute_registered_capability(
                {"tool_id": "print", "action": "list", "params": {}},
                runtime_context={**actor.context, "idempotency_key": "original-call"},
            )
        )
    assert response["error_code"] == "approval_scope_required"
    assert response["execution_status"] == "not_started"
    publish.assert_not_called()


def test_tenant_admin_cannot_discover_global_unit_product_upload_import(trusted_actor):
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial

    actor = trusted_actor(role="admin", tier="admin")
    spec = tool_spec.get_tool_action_spec("unit_products_import", "execute_import")
    assert spec.policy["data_scope"] == "legacy_global"
    assert "unit_products_import" not in workflow_registry(actor.context)
    denial = actor_tool_denial("unit_products_import", "execute_import", actor.context)
    assert denial["reason"] == "legacy_store_not_scoped"


@pytest.mark.parametrize("context", [{}, {"user_id": "1", "tenant_id": "7", "role": "admin"}])
def test_discovery_never_accepts_unbound_identity(context):
    result = discover_capabilities(context)
    assert result["success"] is False
    assert result["capabilities"] == result["employees"] == []


def test_expired_session_does_not_reuse_catalog(trusted_actor):
    from app.db.models.user import User

    actor = trusted_actor(permissions=["customer.view"])
    assert discover_capabilities(actor.context)["success"]
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).is_active = False
    result = discover_capabilities(actor.context)
    assert result["success"] is False
    assert not result["capabilities"]


def test_employee_and_tenant_constraints_share_execution_gate(trusted_actor, monkeypatch):
    from app.application.agent_orchestrator import tool_permission
    from app.application.employee_runtime import loader

    actor = trusted_actor(permissions=["customer.view", "employee.list", "employee.execute"])
    monkeypatch.setattr(tool_permission, "_TENANT_TOOLS", {"tasks": {"88"}})
    monkeypatch.setattr(loader, "resolve_pack_dir", lambda pack_id: pack_id)
    monkeypatch.setattr(loader, "pack_has_direct_python_runtime", lambda _: True)
    monkeypatch.setattr(
        loader, "verify_direct_python_pack_trust", lambda path: (path != "untrusted", "test")
    )
    monkeypatch.setattr(
        "app.mod_sdk.employee_directory.build_employee_directory",
        lambda **kwargs: [
            {"pack_id": "ready", "runtime_ok": True},
            {"pack_id": "prompt-only", "runtime_ok": False},
            {"pack_id": "disabled", "runtime_ok": True, "enabled": False},
            {"pack_id": "untrusted", "runtime_ok": True},
        ],
    )
    result = discover_capabilities(actor.context, limit=500)
    assert [row["employee_id"] for row in result["employees"]] == ["ready"]
    assert "tasks.query" not in {row["capability_id"] for row in result["capabilities"]}
    narrowed = discover_capabilities(
        {**actor.context, "employee_tool_allowlist": ["business_db.read"]}
    )
    assert narrowed["employees"] == []
    assert {row["capability_id"] for row in narrowed["capabilities"]} == {"business_db.read"}


def test_aiopen_catalog_is_the_same_authority_and_routes_are_not_write_capabilities(trusted_actor):
    from app.application.aiopen.catalog_builder import get_catalog

    actor = trusted_actor(permissions=["customer.view"])
    app = FastAPI()

    @app.post("/api/customers")
    def create_customer():
        raise AssertionError("Discovery must not execute")

    catalog = get_catalog(app, actor.context)
    route = next(row for row in catalog["operations"] if row["path"] == "/api/customers")
    assert route["kind"] == "http_resource"
    assert route["executable"] is False
    canonical = next(
        row for row in catalog["operations"] if row["operation_id"] == "capability.business_db.read"
    )
    assert canonical["scope"] == "capability.business_db.read"
    assert (
        canonical["input_schema"]
        == workflow_registry(actor.context)["business_db"]["actions"]["read"]["input_schema"]
    )
    assert canonical["version"] == tool_spec.get_tool_action_spec("business_db", "read").version
    assert "capability.customers.create" not in {
        row["operation_id"] for row in catalog["operations"]
    }


def test_mcp_schema_and_exact_name_survive_all_projections(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"query": {"type": "integer", "minimum": 1}},
        "required": ["query"],
    }
    raw = {
        "mcp__demo": {
            "description": "demo",
            "actions": {
                "search": {
                    "risk": "high",
                    "input_schema": schema,
                    "required_params": ["query"],
                }
            },
        }
    }
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.get_workflow_tools_from_registry", lambda: {}
    )
    monkeypatch.setattr(
        "app.application.tools.mcp.registry.merge_mcp_tools", lambda registry: deepcopy(raw)
    )
    assert tool_spec.validate_tool_call("mcp__demo", "search", {"query": 2}).ok
    assert not tool_spec.validate_tool_call("mcp__demo", "search", {"query": "wrong"}).ok
    assert not tool_spec.validate_tool_call("mcp__demo", "query", {"query": 2}).ok
    assert workflow_registry()["mcp__demo"]["actions"]["search"]["input_schema"] == schema
    raw.clear()
    assert "mcp__demo" not in workflow_registry()


def test_duplicate_normalized_action_rejected_instead_of_overwriting(monkeypatch):
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.get_workflow_tools_from_registry",
        lambda: {"example": {"actions": {"search": {"risk": "low"}, "query": {"risk": "high"}}}},
    )
    monkeypatch.setattr(
        "app.application.tools.mcp.registry.merge_mcp_tools", lambda registry: registry
    )
    with pytest.raises(ValueError, match="Duplicate capability identity"):
        tool_spec.build_tool_specs_v2()


def test_provider_refresh_replaces_old_risk_and_removed_actions():
    from app.domain.autonomy.risk_policy import RiskPolicyCatalog

    policy = RiskPolicyCatalog()
    policy.register_actions(
        "mcp__demo", actions={"search": {"risk": "low"}, "removed": {"risk": "low"}}
    )
    policy.register_actions(
        "mcp__demo", actions={"search": {"risk": "high", "requires_write_approval": True}}
    )
    assert policy.get_action_spec("mcp__demo", "search")["risk"] == "high"
    assert policy.requires_write_approval("mcp__demo", "search")
    assert policy.get_action_spec("mcp__demo", "removed") is None
    with pytest.raises(ValueError, match="Duplicate capability definition"):
        policy.register_actions("customers", actions={"query": {"risk": "high"}})
