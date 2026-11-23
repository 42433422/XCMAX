"""The retained business registry and execution profile boundaries."""

from app.application.workflow.planning_graph_policy import (
    filter_registry_for_profile as _filter_tool_registry_for_profile,
)
from app.services.tools_execution.registry import get_workflow_tool_registry as get_tool_registry


class TestGetToolRegistry:
    def test_returns_dict(self):
        reg = get_tool_registry()
        assert isinstance(reg, dict)
        assert "products" in reg
        assert "customers" in reg
        assert "shipment_orders" in reg

    def test_tool_has_actions(self):
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


class TestFilterToolRegistryForProfile:
    def test_normal_removes_pro_only(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "pro_only",
                "actions": {"exec": {"availability": "pro_only", "risk": "high"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_pro_default_removes_normal_only(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
            "tool_b": {
                "availability": "normal_only",
                "actions": {"slot": {"availability": "normal_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "pro_default")
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_shared_kept_in_both(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": {"availability": "shared", "risk": "low"}},
            },
        }
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" in _filter_tool_registry_for_profile(reg, "pro_default")

    def test_action_level_filtering(self):
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {
                    "query": {"availability": "shared", "risk": "low"},
                    "admin": {"availability": "pro_only", "risk": "high"},
                },
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "query" in result["tool_a"]["actions"]
        assert "admin" not in result["tool_a"]["actions"]

    def test_non_dict_spec_skipped(self):
        reg = {"bad": "not a dict"}
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad" not in result

    def test_empty_actions_skipped(self):
        reg = {
            "tool_a": {
                "availability": "pro_only",
                "actions": {"query": {"availability": "pro_only", "risk": "low"}},
            },
        }
        result = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool_a" not in result
