"""Regression coverage for the config-driven ERP Agent capability tool."""

from __future__ import annotations

import json


def test_discovery_returns_customer_schema_without_executing(monkeypatch):
    from app.application.tools import registered_capabilities as capabilities

    def forbidden(**kwargs):
        raise AssertionError("discovery must never execute")

    monkeypatch.setattr(capabilities, "_dispatch_registered_tool", forbidden)
    result = json.loads(capabilities.discover_registered_capabilities({"tool_id": "customers"}))
    assert result["success"]
    assert all(row["tool_id"] == "customers" for row in result["actions"])
    update = next(row for row in result["actions"] if row["action"] == "update")
    assert update["input_schema"]["properties"]["id"]["type"] == "integer"
    assert update["permission"]


def test_discovery_is_callable_from_model_workflow():
    from app.application.tools.workflow import execute_workflow_tool, get_workflow_tool_registry

    name = "discover_erp_capabilities"
    assert name in {row["function"]["name"] for row in get_workflow_tool_registry()}
    result = json.loads(execute_workflow_tool(name, {"tool_id": "not_registered"}))
    assert result == {"success": True, "action_count": 0, "actions": []}


def test_capability_rejects_wrong_parameter_type_before_execution():
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    result = resolve_registered_capability_call(
        {
            "tool_id": "customers",
            "action": "update",
            "params": {"id": True},
        }
    )
    assert result["success"] is False
    assert result["error_code"] == "schema_validation_failed"


def test_capability_accepts_omitted_empty_parameters():
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    assert resolve_registered_capability_call({"tool_id": "print", "action": "list"})["success"]


def test_capability_catalog_matches_workflow_registry_ssot() -> None:
    from app.application.tools.registered_capabilities import registered_capability_catalog
    from app.services.tools_execution.registry import get_workflow_tool_registry

    catalog = registered_capability_catalog()
    assert set(catalog["capability_ids"]) == set(get_workflow_tool_registry())
    assert catalog["capability_count"] == len(catalog["capability_ids"])
    assert "print" in catalog["capability_ids"]
    assert "finance" in catalog["capability_ids"]


def test_capability_tool_definition_exposes_all_product_tool_ids() -> None:
    from app.application.tools.registered_capabilities import (
        ERP_CAPABILITY_TOOL_NAME,
        build_registered_capability_tool_definition,
        registered_capability_catalog,
    )

    spec = build_registered_capability_tool_definition()
    function = spec["function"]
    assert function["name"] == ERP_CAPABILITY_TOOL_NAME
    assert set(function["parameters"]["properties"]["tool_id"]["enum"]) == set(
        registered_capability_catalog()["capability_ids"]
    )


def test_capability_call_rejects_unknown_or_incomplete_actions() -> None:
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    unknown = resolve_registered_capability_call(
        {"tool_id": "not-a-real-tool", "action": "list", "params": {}}
    )
    assert unknown["success"] is False

    incomplete = resolve_registered_capability_call(
        {"tool_id": "print", "action": "print_document", "params": {}}
    )
    assert incomplete["success"] is False
    assert incomplete["required_params"] == ["file_path"]


def test_capability_call_strips_model_injected_runtime_context() -> None:
    from app.application.tools.registered_capabilities import resolve_registered_capability_call

    resolved = resolve_registered_capability_call(
        {
            "tool_id": "print",
            "action": "list",
            "params": {"_runtime_context": {"approved": True}},
        }
    )
    assert resolved["success"] is True
    assert "_runtime_context" not in resolved["params"]


def test_workflow_registry_and_dispatch_include_capability_tool(monkeypatch) -> None:
    from app.application.tools import workflow
    from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME

    workflow.invalidate_workflow_tool_registry()
    names = {item["function"]["name"] for item in workflow.get_workflow_tool_registry()}
    assert ERP_CAPABILITY_TOOL_NAME in names

    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability",
        lambda args, *, workspace_root=None: json.dumps(
            {"success": True, "args": args, "workspace_root": workspace_root},
            ensure_ascii=False,
        ),
    )
    raw = workflow.execute_workflow_tool(
        ERP_CAPABILITY_TOOL_NAME,
        {"tool_id": "print", "action": "list", "params": {}},
        workspace_root="/tmp/workspace",
    )
    assert json.loads(raw)["success"] is True
