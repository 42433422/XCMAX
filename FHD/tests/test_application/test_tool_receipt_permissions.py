"""Action-specific receipts must never change the business authorization boundary."""

import pytest

from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

_CASES = [
    ("materials", action, "material.edit")
    for action in ("create", "update", "delete", "batch_delete", "clear")
] + [
    ("document_template", action, "elt.template.manage")
    for action in ("create", "update", "delete", "clear", "ingest", "upload")
]


@pytest.mark.parametrize("tool,action,grant", _CASES)
def test_action_receipt_keeps_the_same_real_business_grant(trusted_actor, tool, action, grant):
    spec = get_tool_action_spec(tool, action)
    assert spec.permission == grant
    assert spec.receipt_permission == f"tool.{tool}.{action}"
    actor = trusted_actor(
        permissions=[grant],
        **({"tenant_id": None, "role": "admin", "tier": "admin"} if tool == "materials" else {}),
    )
    assert actor_tool_denial(tool, action, actor.context) is None


@pytest.mark.parametrize("tool,action,grant", _CASES)
@pytest.mark.parametrize("kind", ["read-only", "receipt-only"])
def test_read_or_receipt_permission_cannot_authorize_business_mutations(
    trusted_actor, tool, action, grant, kind
):
    permissions = (
        ["material.view", "elt.read"] if kind == "read-only" else [f"tool.{tool}.{action}"]
    )
    actor = trusted_actor(permissions=permissions)
    result = actor_tool_denial(tool, action, actor.context)
    assert result["success"] is False
    assert result["error_code"] == "tool_permission_denied"
    assert result["reason"] == (
        "legacy_store_not_scoped" if tool == "materials" else "permission_denied"
    )


@pytest.mark.parametrize(
    "tool,action,params",
    [
        ("products", "delete", {"id": 1}),
        ("products", "create", {"name_or_model": "scoped-test"}),
        ("customers", "get_addresses", {"customer_id": 1}),
        ("customers", "set_credit_limit", {"customer_id": 1, "credit_limit": 100}),
        ("materials", "list", {}),
        ("materials", "delete", {"id": 1}),
        (
            "unit_products_import",
            "execute_import",
            {"saved_name": "fixture.db", "unit_name": "scoped-test"},
        ),
        ("print", "print_document", {"file_path": "fixture.pdf"}),
        ("excel_vector_index", "list", {}),
        ("excel_vector_index", "query", {"index_id": "original", "query": "fixture"}),
        ("excel_vector_index", "delete", {"index_id": "original"}),
    ],
)
def test_legacy_store_contract_hides_and_denies_tenant_admin_before_task_admission(
    trusted_actor, monkeypatch, tool, action, params
):
    import json

    from app.application.capability_catalog import capability_entries
    from app.application.tools.registered_capabilities import execute_registered_capability

    actor = trusted_actor(role="admin")
    spec = get_tool_action_spec(tool, action)
    assert spec.policy["data_scope"] == "legacy_global"
    context = {**actor.context, "idempotency_key": "legacy-store-denial"}
    assert actor_tool_denial(tool, action, context, params)["reason"] == "legacy_store_not_scoped"
    assert f"{tool}.{action}" not in {row["capability_id"] for row in capability_entries(context)}

    def forbidden(*args, **kwargs):
        raise AssertionError("A tenant must not publish a task against a global legacy store")

    monkeypatch.setattr("app.application.agent_orchestrator.AgentOrchestrator", forbidden)
    result = json.loads(
        execute_registered_capability(
            {"tool_id": tool, "action": action, "params": params}, runtime_context=context
        )
    )
    assert result["success"] is False
    assert result["error_code"] == "tool_permission_denied"
    assert result["reason"] == "legacy_store_not_scoped"


@pytest.mark.parametrize(
    "tool,action,permission",
    [
        ("products", "query", "product.view"),
        ("customers", "query", "customer.view"),
        ("customers", "create", "customer.edit"),
        ("shipment_orders", "delete", "shipment.edit"),
    ],
)
def test_tenant_actions_require_their_business_permission(trusted_actor, tool, action, permission):
    assert get_tool_action_spec(tool, action).policy.get("data_scope") != "legacy_global"
    actor = trusted_actor(permissions=[permission])
    assert actor_tool_denial(tool, action, actor.context) is None
    unprivileged = trusted_actor(role="unprivileged", permissions=[])
    denial = actor_tool_denial(tool, action, unprivileged.context)
    assert denial["error_code"] == "tool_permission_denied"
    assert denial["reason"] == "permission_denied"


@pytest.mark.parametrize(
    "tool,action",
    [("customers", "delete"), ("customers", "batch_delete"), ("print", "list"), ("print", "test")],
)
def test_tenant_owned_customer_deletion_and_printer_devices_remain_authorized(
    trusted_actor, tool, action
):
    actor = trusted_actor(role="admin")
    assert get_tool_action_spec(tool, action).policy.get("data_scope") != "legacy_global"
    assert actor_tool_denial(tool, action, actor.context) is None
