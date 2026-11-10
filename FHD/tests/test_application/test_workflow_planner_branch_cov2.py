"""Current model admission filters and the canonical workflow action catalog."""

from app.application.workflow.planning_graph_policy import (
    filter_registry_for_profile as filter_tool_registry_for_profile,
)
from app.services.tools_execution.registry import get_workflow_tool_registry


def test_normal_profile_removes_pro_only_tools_and_actions():
    registry = {
        "shared": {"availability": "shared", "actions": {"read": {"availability": "shared"}}},
        "pro": {"availability": "pro_only", "actions": {"write": {"availability": "pro_only"}}},
        "mixed": {
            "availability": "shared",
            "actions": {
                "read": {"availability": "shared"},
                "admin": {"availability": "pro_only"},
            },
        },
    }

    result = filter_tool_registry_for_profile(registry, "normal")

    assert set(result) == {"shared", "mixed"}
    assert set(result["mixed"]["actions"]) == {"read"}


def test_pro_default_profile_rejects_normal_only_entries():
    registry = {
        "shared": {"availability": "shared", "actions": {"read": {"availability": "shared"}}},
        "normal": {
            "availability": "normal_only",
            "actions": {"slot": {"availability": "normal_only"}},
        },
    }

    result = filter_tool_registry_for_profile(registry, "pro_default")

    assert set(result) == {"shared"}


def test_canonical_registry_has_plannable_business_capabilities():
    registry = get_workflow_tool_registry()

    assert {"products", "customers", "business_db", "employee"} <= set(registry)
    assert "read" in registry["business_db"]["actions"]
    assert "write" in registry["business_db"]["actions"]
