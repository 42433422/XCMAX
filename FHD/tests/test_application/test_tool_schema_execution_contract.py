"""C02/C04: exact contracts reject invalid calls before any business adapter runs."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock

import pytest

from app.application.agent_orchestrator import tool_spec
from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


@pytest.mark.parametrize(
    "schema,params",
    [
        ({"properties": {"value": {"const": "accepted"}}}, {"value": "other"}),
        ({"properties": {"value": {"type": ["string", "null"]}}}, {"value": 7}),
        ({"properties": {"value": {"type": "string"}}}, {"value": None}),
        ({"properties": {"value": {"type": "number"}}}, {"value": float("nan")}),
        (
            {"properties": {"value": {"type": "string", "format": "date-time"}}},
            {"value": "not-a-date"},
        ),
        ({"properties": {"value": {"type": "string", "format": "date"}}}, {"value": "2026-02-31"}),
        ({"properties": {"items": {"type": "array", "items": {"enum": ["a"]}}}}, {"items": ["b"]}),
        ({"properties": {"items": {"type": "array", "uniqueItems": True}}}, {"items": [1, 1]}),
        ({"properties": {"items": {"type": "array", "items": {"minimum": 1}}}}, {"items": [0]}),
        ({"allOf": [{"required": ["receipt"]}]}, {}),
        ({"if": {"required": ["write"]}, "then": {"required": ["receipt"]}}, {"write": True}),
        ({"dependentSchemas": {"write": {"required": ["receipt"]}}}, {"write": True}),
        ({"not": {"required": ["unsafe"]}}, {"unsafe": True}),
        ({"additionalProperties": {"type": "integer"}}, {"unexpected": "text"}),
        ({"properties": {"known": {}}, "unevaluatedProperties": False}, {"unknown": 1}),
        (
            {
                "$defs": {"id": {"type": "integer", "minimum": 1}},
                "properties": {"id": {"$ref": "#/$defs/id"}},
            },
            {"id": 0},
        ),
        ({"properties": {"id": {"$ref": "https://untrusted.invalid/schema"}}}, {"id": 1}),
    ],
)
def test_full_schema_is_enforced_by_executor_and_plan_preflight(monkeypatch, schema, params):
    contract = tool_spec.ToolActionSpecV2(
        "contract_fixture", "execute", input_schema={"type": "object", **schema}
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.get_tool_action_spec", lambda *_: contract
    )
    dispatch = Mock(side_effect=AssertionError("invalid input must never reach business execution"))
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    plan = PlanGraph(
        "invalid",
        "reject before first action",
        nodes=[WorkflowNode("first", contract.tool_id, contract.action, params=deepcopy(params))],
    )
    registry = {contract.tool_id: {"actions": {contract.action: contract.to_dict()}}}
    assert validate_required_params(plan, registry) is not None
    result = AgentToolExecutor().execute(
        AgentStep("first", contract.tool_id, contract.action, params=deepcopy(params)),
        runtime_context={},
    )
    assert result["success"] is False
    assert result["error_code"] == "schema_validation_failed"
    assert result["execution"] == {"outcome": "not_executed", "committed": False}
    dispatch.assert_not_called()


def test_declared_reference_is_deferred_but_its_resolved_value_is_checked(monkeypatch):
    contract = tool_spec.ToolActionSpecV2(
        "contract_fixture",
        "execute",
        input_schema={
            "type": "object",
            "required": ["id"],
            "$defs": {"id": {"type": "integer", "minimum": 1}},
            "properties": {"id": {"$ref": "#/$defs/id"}},
        },
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    reference = {"id": "{{lookup.data.id}}"}
    assert tool_spec.validate_tool_call(
        *("contract_fixture", "execute"), reference, allow_references_from={"lookup"}
    ).ok
    assert not tool_spec.validate_tool_call("contract_fixture", "execute", reference).ok
    assert not tool_spec.validate_tool_call(
        "contract_fixture", "execute", reference, allow_references_from=set()
    ).ok
    assert not tool_spec.validate_tool_call("contract_fixture", "execute", {"id": -1}).ok
    assert tool_spec.validate_tool_call("contract_fixture", "execute", {"id": 4}).ok


@pytest.mark.parametrize(
    "schema,params,expected",
    [
        (
            {"properties": {"ids": {"type": "array", "items": {"type": "string"}}}},
            {"ids": "one, two；three"},
            {"ids": ["one", "two", "three"]},
        ),
        (
            {
                "properties": {
                    "input": {
                        "type": "object",
                        "properties": {"ids": {"type": "array", "items": {"type": "string"}}},
                    }
                }
            },
            {"input": {"ids": "one;two"}},
            {"input": {"ids": ["one", "two"]}},
        ),
        (
            {"properties": {"reference_id": {"type": "string"}}},
            {"reference_id": 17},
            {"reference_id": "17"},
        ),
    ],
)
def test_executor_dispatches_validated_copy_without_changing_original_plan(
    monkeypatch, schema, params, expected
):
    from app.application.agent_orchestrator import tool_permission
    from app.application.workflow.workflow_types import plan_fingerprint

    contract = tool_spec.ToolActionSpecV2(
        "contract_fixture", "execute", input_schema={"type": "object", **schema}, read_only=True
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_executor.get_tool_action_spec", lambda *_: contract
    )
    dispatch = Mock(return_value={"success": True, "data": [], "message": "ok"})
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    original = deepcopy(params)
    step = AgentStep("first", contract.tool_id, contract.action, params=params)
    plan = PlanGraph(
        "frozen",
        "preserve business intent",
        nodes=[WorkflowNode("first", contract.tool_id, contract.action, params=params)],
    )
    fingerprint = plan_fingerprint(plan)
    permission_check = Mock(wraps=tool_permission.actor_tool_denial)
    monkeypatch.setattr(tool_permission, "actor_tool_denial", permission_check)

    result = AgentToolExecutor().execute(step, runtime_context={})

    assert result["success"], result
    dispatched = dispatch.call_args.args[2]
    assert {
        key: value for key, value in dispatched.items() if key != "_runtime_context"
    } == expected
    checked = permission_check.call_args.args[3]
    assert {key: value for key, value in checked.items() if key != "_runtime_context"} == expected
    assert step.params == params == original
    assert plan_fingerprint(plan) == fingerprint


def test_validated_employee_chain_keeps_original_child_arguments():
    from tests.fixtures.employee_business_chain import business_plan

    params = {
        "employee_id": "employee-a",
        "task": "Sales report",
        "continuity_action": "chain",
        "input": business_plan(),
    }
    original = deepcopy(params)
    validation = tool_spec.validate_tool_call("employee", "execute", params)
    assert validation.ok, validation.message
    assert validation.normalized_params == original == params
    assert validation.normalized_params is not params


def test_validated_shipment_alias_is_carried_without_rewriting_original():
    spec = tool_spec.get_tool_action_spec("shipment_records", "create")
    params = deepcopy(spec.contract_samples[0]["input"])
    params["purchase_unit"] = params.pop("unit_name")
    original = deepcopy(params)
    validation = tool_spec.validate_tool_call("shipment_records", "create", params)
    assert validation.ok, validation.message
    assert validation.normalized_params["unit_name"] == original["purchase_unit"]
    assert params == original


@pytest.mark.parametrize("params", [None, {}])
def test_validated_empty_params_are_an_independent_object(monkeypatch, params):
    contract = tool_spec.ToolActionSpecV2("contract_fixture", "execute", input_schema={})
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    validation = tool_spec.validate_tool_call("contract_fixture", "execute", params)
    assert validation.ok and validation.normalized_params == {}
    assert validation.normalized_params is not params


@pytest.mark.parametrize("value", [7, "7", 0, False, [], {}])
def test_legacy_required_metadata_rejects_missing_and_null_without_narrowing_values(
    monkeypatch, value
):
    contract = tool_spec.ToolActionSpecV2(
        "contract_fixture", "execute", input_schema=tool_spec._schema_from_required(["value"])
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    assert tool_spec.validate_tool_call("contract_fixture", "execute", {"value": value}).ok
    for invalid in ({}, {"value": None}):
        result = tool_spec.validate_tool_call("contract_fixture", "execute", invalid)
        assert not result.ok and result.error_code == "schema_validation_failed"


def test_explicit_nullable_schema_survives_legacy_required_metadata(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"value": {"type": ["string", "null"]}},
    }
    monkeypatch.setattr(
        "resources.config.risk_actions_loader.get_workflow_tools_from_registry",
        lambda: {
            "nullable_fixture": {
                "actions": {"execute": {"required_params": ["value"], "input_schema": schema}}
            }
        },
    )
    monkeypatch.setattr("app.application.tools.mcp.registry.merge_mcp_tools", lambda tools: tools)
    monkeypatch.setattr(tool_spec, "_add_aiopen_tool_specs", lambda specs: None)
    monkeypatch.setattr(tool_spec, "_TOOL_SPECS_CACHE", None)
    monkeypatch.setattr(tool_spec, "_TOOL_SPECS_SOURCE", None)
    assert tool_spec.validate_tool_call("nullable_fixture", "execute", {"value": None}).ok
    assert not tool_spec.validate_tool_call("nullable_fixture", "execute", {}).ok


@pytest.mark.parametrize(
    "tool,action,params,identifiers",
    [
        (
            "inventory",
            "stock_out",
            {"product_id": 1, "warehouse_id": 2, "quantity": 3},
            ("product_id", "warehouse_id"),
        ),
        (
            "inventory",
            "transfer",
            {"product_id": 1, "from_warehouse_id": 2, "to_warehouse_id": 3, "quantity": 4},
            ("product_id", "from_warehouse_id", "to_warehouse_id"),
        ),
        ("document_template", "update", {"id": 7}, ("id",)),
        ("document_template", "delete", {"id": "fs:owned.xlsx"}, ("id",)),
    ],
)
def test_required_identifiers_refuse_null_before_dispatch_and_keep_existing_forms(
    monkeypatch, tool, action, params, identifiers
):
    dispatch = Mock(side_effect=AssertionError("null identifiers must not reach business tools"))
    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    original = deepcopy(params)
    assert tool_spec.validate_tool_call(tool, action, params).ok
    assert tool_spec.validate_tool_call(
        tool, action, {**params, **{key: str(params[key]) for key in identifiers}}
    ).ok
    for key in identifiers:
        result = AgentToolExecutor().execute(
            AgentStep("invalid", tool, action, params={**params, key: None}), runtime_context={}
        )
        assert not result["success"] and result["error_code"] == "schema_validation_failed"
        assert result["execution"] == {"outcome": "not_executed", "committed": False}
    assert params == original
    dispatch.assert_not_called()


@pytest.mark.parametrize("payload", [None, 7, "invalid", []])
def test_sales_closed_loop_requires_an_object_payload(payload):
    assert not tool_spec.validate_tool_call("sales", "execute_closed_loop", {"payload": payload}).ok
    assert tool_spec.validate_tool_call(
        "sales", "execute_closed_loop", {"payload": {"idempotency_key": "original-request"}}
    ).ok


@pytest.mark.parametrize("action", [None, 7])
def test_computer_steps_require_a_nonnull_action(action):
    params = {"request_id": "original-request", "target": "browser", "steps": [{"action": action}]}
    assert not tool_spec.validate_tool_call("desktop_automation", "computer_execute", params).ok
    params["steps"] = [{"action": "navigate", "url": "https://example.com"}]
    assert tool_spec.validate_tool_call("desktop_automation", "computer_execute", params).ok


def test_memory_candidate_keeps_its_explicit_nullable_value_contract():
    params = {"memory_type": "preference", "key": "optional_preference", "value": None}
    assert tool_spec.validate_tool_call("memory_v2", "propose_candidate", params).ok
    assert not tool_spec.validate_tool_call(
        "memory_v2",
        "propose_candidate",
        {key: value for key, value in params.items() if key != "value"},
    ).ok


@pytest.mark.parametrize("action", ["append_price", "correct_price"])
@pytest.mark.parametrize("field", ["operation_id", "revision", "reason", "price"])
def test_catalog_required_values_refuse_null_before_original_effect_lookup(
    monkeypatch, action, field
):
    spec = tool_spec.get_tool_action_spec("catalog_products_v1", action)
    assert spec is not None
    params = deepcopy(spec.contract_samples[0]["input"])
    if action == "correct_price":
        params.update(period_start=None, period_end=None)
    assert tool_spec.validate_tool_call("catalog_products_v1", action, params).ok
    original = deepcopy(params)
    lookup = Mock(side_effect=AssertionError("invalid input must not enter the catalog adapter"))
    monkeypatch.setattr("app.application.agent_orchestrator.tool_executor._execute_catalog", lookup)
    result = AgentToolExecutor().execute(
        AgentStep("invalid", "catalog_products_v1", action, params={**params, field: None}),
        runtime_context={},
    )
    assert not result["success"] and result["error_code"] == "schema_validation_failed"
    assert result["execution"] == {"outcome": "not_executed", "committed": False}
    assert params == original
    lookup.assert_not_called()


@pytest.mark.parametrize("deferred", ["reference", "clarification"])
@pytest.mark.parametrize(
    "known_schema,known",
    [
        ({"const": "safe"}, "unsafe"),
        ({"$ref": "#/$defs/positive"}, -1),
        ({"type": "array", "items": {"enum": ["allowed"]}}, ["denied"]),
    ],
)
def test_pending_field_never_hides_an_independent_known_violation(
    monkeypatch, deferred, known_schema, known
):
    contract = tool_spec.ToolActionSpecV2(
        "contract_fixture",
        "execute",
        input_schema={
            "type": "object",
            "required": ["pending", "known"],
            "$defs": {"positive": {"type": "integer", "minimum": 1}},
            "properties": {"pending": {"type": "integer"}, "known": known_schema},
        },
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    params = {"known": known}
    if deferred == "reference":
        params["pending"] = "{{lookup.data.id}}"
    result = tool_spec.validate_tool_call(
        "contract_fixture",
        "execute",
        params,
        allow_references_from={"lookup"},
        allow_missing_fields={"pending"} if deferred == "clarification" else set(),
    )
    assert not result.ok and result.error_code == "schema_validation_failed"


def test_anyof_can_defer_only_a_branch_without_known_violations(monkeypatch):
    schema = {
        "type": "object",
        "anyOf": [
            {"properties": {"pending": {"type": "integer"}, "known": {"const": "a"}}},
            {"properties": {"pending": {"type": "boolean"}, "known": {"const": "b"}}},
        ],
    }
    contract = tool_spec.ToolActionSpecV2("contract_fixture", "execute", input_schema=schema)
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    args = {"pending": "{{lookup.data.id}}", "known": "c"}
    assert not tool_spec.validate_tool_call(
        "contract_fixture", "execute", args, allow_references_from={"lookup"}
    ).ok
    assert tool_spec.validate_tool_call(
        "contract_fixture", "execute", {**args, "known": "a"}, allow_references_from={"lookup"}
    ).ok


@pytest.mark.parametrize(
    "schema,params",
    [
        ({"properties": {"pending": {}}, "additionalProperties": False}, {"typo": 1}),
        ({"not": {"required": ["pending"]}}, {}),
        (
            {
                "if": {"properties": {"kind": {"const": "write"}}, "required": ["kind"]},
                "then": {"properties": {"mode": {"const": "safe"}}},
            },
            {"kind": "write", "mode": "unsafe"},
        ),
    ],
)
def test_reference_does_not_hide_known_object_or_conditional_constraints(
    monkeypatch, schema, params
):
    contract = tool_spec.ToolActionSpecV2(
        "contract_fixture", "execute", input_schema={"type": "object", **schema}
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    result = tool_spec.validate_tool_call(
        "contract_fixture",
        "execute",
        {"pending": "{{lookup.data.id}}", **params},
        allow_references_from={"lookup"},
    )
    assert not result.ok


@pytest.mark.parametrize("declared", ["date-time", "unsupported-format"])
def test_missing_or_unknown_format_checker_fails_closed(monkeypatch, declared):
    from jsonschema import FormatChecker

    monkeypatch.delitem(FormatChecker.checkers, declared, raising=False)
    valid, message = tool_spec.validate_schema_object(
        {"type": "object", "properties": {"value": {"type": "string", "format": declared}}},
        {"value": "arbitrary"},
    )
    assert not valid and "校验器未安装或不受支持" in message


@pytest.mark.parametrize(
    "schema,params",
    [
        (
            {
                "oneOf": [
                    {"properties": {"value": {"const": "a"}}},
                    {"properties": {"value": {"const": "b"}}},
                ]
            },
            {"value": "a"},
        ),
        (
            {"required": ["value"], "properties": {"value": {"type": ["string", "null"]}}},
            {"value": None},
        ),
        (
            {"properties": {"value": {"type": "string", "pattern": "safe"}}},
            {"value": "safe prefix"},
        ),
        (
            {"patternProperties": {"^id_": {"type": "integer"}}, "additionalProperties": False},
            {"id_one": 1},
        ),
    ],
)
def test_exact_valid_contracts_are_not_rejected_by_the_legacy_schema_subset(schema, params):
    valid, message = tool_spec.validate_schema_object({"type": "object", **schema}, params)
    assert valid, message


@pytest.mark.parametrize("value", [[], "x", 7, False])
def test_non_object_arguments_are_refused_without_coercing_or_raising(value):
    validation = tool_spec.validate_tool_call("customers", "query", value)
    assert not validation.ok and validation.error_code == "schema_validation_failed"


def test_malformed_schema_fails_closed(monkeypatch):
    contract = tool_spec.ToolActionSpecV2(
        "invalid", "execute", input_schema={"type": "nonexistent"}
    )
    monkeypatch.setattr(tool_spec, "get_tool_action_spec", lambda *_: contract)
    assert not tool_spec.validate_tool_call("invalid", "execute", {}).ok


@pytest.mark.parametrize("arguments", [{"query": float("nan")}, {"query": object()}])
def test_xiaox_invalid_json_is_a_controlled_refusal_without_claiming(arguments):
    from app.infrastructure.xiaox.binding import XiaoxBindingError
    from app.infrastructure.xiaox.tools import XiaoxToolBridge

    store = Mock()
    bridge = XiaoxToolBridge(store, orchestrator=Mock())
    with pytest.raises(XiaoxBindingError) as error:
        bridge.invoke("unused", "capability_search", arguments)
    assert error.value.code == "invalid_arguments"
    store.scope.assert_not_called()


def test_mcp_dispatch_uses_the_same_exact_schema_guard(monkeypatch):
    from app.application.tools.mcp import registry
    from app.infrastructure.mcp.config import McpServerConfig

    schema = {"type": "object", "properties": {"value": {"const": "accepted"}}}
    monkeypatch.setattr(registry, "mcp_enabled", lambda: True)
    monkeypatch.setattr(
        registry,
        "_snapshot",
        lambda: (
            {"mcp__sample": {"actions": {"submit": {"input_schema": schema}}}},
            {"mcp__sample": McpServerConfig(name="sample", command="unused")},
        ),
    )
    dispatch = Mock(side_effect=AssertionError("invalid MCP input must not leave the host"))
    monkeypatch.setattr(registry, "call_tool", dispatch)
    result = registry.call_mcp_tool("mcp__sample", "submit", {"value": "wrong"})
    assert result["error_code"] == "mcp_arguments_invalid"
    dispatch.assert_not_called()
