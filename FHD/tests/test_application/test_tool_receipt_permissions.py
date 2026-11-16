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
    actor = trusted_actor(permissions=[grant])
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
    assert result["reason"] == "permission_denied"
