"""The model catalog is a live projection, never a second alias registry."""

from app.application.capability_catalog import workflow_registry
from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME
from app.application.tools.workflow import (
    get_workflow_tool_registry,
    invalidate_workflow_tool_registry,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def test_each_model_action_uses_its_authoritative_schema(trusted_actor):
    actor = trusted_actor(role="admin", tier="admin")
    authority = workflow_registry(actor.context)
    registry = get_workflow_tool_registry(actor.context)
    assert [entry["function"]["name"] for entry in registry] == [ERP_CAPABILITY_TOOL_NAME]
    branches = registry[0]["function"]["parameters"]["anyOf"]
    seen = set()
    for branch in branches:
        fields = branch["properties"]
        tool_id, action = fields["tool_id"]["enum"][0], fields["action"]["enum"][0]
        assert (tool_id, action) not in seen
        seen.add((tool_id, action))
        assert fields["params"] == authority[tool_id]["actions"][action]["input_schema"]
    assert seen == {
        (tool_id, action) for tool_id, tool in authority.items() for action in tool["actions"]
    }
    assert "delete_order" not in authority
    assert "business_db_read" not in authority


def test_invalidation_does_not_grant_ambient_identity(monkeypatch):
    monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "not-an-account-grant")
    invalidate_workflow_tool_registry()
    assert get_workflow_tool_registry() == []
    assert get_workflow_tool_registry({"user_id": "1", "role": "admin"}) == []
