"""Planner catalog savings preserve executable contracts and the full requested scope."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from app.application.agent_orchestrator.context_window_manager import (
    ContextWindowExceeded,
    ContextWindowManager,
    estimate_messages_tokens,
)
from app.application.facades.tools_facade import get_workflow_tool_registry
from app.application.workflow import planner_prompt_profile as profile
from app.application.workflow.llm_plan_generation import _tool_specs
from app.application.workflow.planner_llm_gateway import (
    _compact_tool_registry,
    _prepare_model_messages,
    _shrink_planner_prompt,
)
from app.application.workflow.planner_prompt_profile import _slim_schema


@pytest.mark.parametrize(
    "message, needed",
    [
        ("导出销售订单", {"sales", "reports"}),
        ("查询客户七彩乐园的9803产品", {"customers", "products"}),
        ("查询客户七彩乐园产品库存", {"customers", "products", "inventory"}),
    ],
)
def test_scene_hints_do_not_remove_tools_needed_by_combined_goals(monkeypatch, message, needed):
    monkeypatch.setattr(profile, "_semantic_intents", lambda _text: set())
    registry = get_workflow_tool_registry()
    assert needed <= registry.keys()
    assert needed <= profile.select_tools_for_prompt(registry, message).keys()


def test_real_employee_inputs_and_preview_result_paths_reach_model():
    registry = get_workflow_tool_registry()
    tools = {item["tool_id"]: item for item in _tool_specs(registry)}
    employee = next(a for a in tools["employee"]["actions"] if a["action"] == "execute")
    nested = employee["input_schema"]["properties"]["input"]["properties"]
    assert nested["table_json"]["properties"]["rows"]["type"] == "array"
    preview = next(a for a in tools["elt_import"]["actions"] if a["action"] == "preview")
    assert preview["output_schema"]["properties"]["data"]["properties"]["run_id"] == {
        "type": "string"
    }


@pytest.mark.parametrize("action_name", ["quote", "create_order"])
def test_real_sales_catalog_requires_customer_through_budget_projection(action_name):
    registry = get_workflow_tool_registry()
    prompt = {"tool_registry": _tool_specs({"sales": registry["sales"]})}
    _compact_tool_registry(prompt)
    outbound = [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]
    assert _shrink_planner_prompt(outbound)
    for projected in (prompt, json.loads(outbound[-1]["content"])):
        action = next(
            item
            for item in projected["tool_registry"][0]["actions"]
            if item["action"] == action_name
        )
        schema = action.get("input_schema") or projected["tool_schemas"][action["input_schema_ref"]]
        validator = Draft202012Validator(schema)
        params = {"items": [{"model_number": "A100", "quantity": 2, "unit_price": 50}]}
        errors = list(validator.iter_errors(params))
        assert any(error.validator == "anyOf" and not error.path for error in errors)
        validator.validate({**params, "customer_id": 1})
        validator.validate({**params, "customer_name": "客户甲"})


@pytest.mark.parametrize(
    "invalid",
    [
        {"rows": [{}]},
        {"rows": [{"quantity": 0}]},
        {"rows": [{"quantity": 1, "unexpected": True}]},
        {"rows": []},
    ],
)
def test_slim_schema_keeps_local_references_nested_requirements_and_constraints(invalid):
    schema = {
        "type": "object",
        "required": ["rows"],
        "additionalProperties": False,
        "$defs": {
            "Row": {
                "type": "object",
                "required": ["quantity"],
                "additionalProperties": False,
                "properties": {"quantity": {"type": "integer", "minimum": 1}},
            }
        },
        "properties": {
            "rows": {
                "type": "array",
                "items": {"$ref": "#/$defs/Row"},
                "minItems": 1,
                "description": "A bounded list of real rows. " * 50,
            }
        },
    }
    original = copy.deepcopy(schema)
    slim = _slim_schema(schema)
    validator = Draft202012Validator(slim)
    validator.validate({"rows": [{"quantity": 1}]})
    assert list(validator.iter_errors(invalid))
    assert schema == original
    assert len(json.dumps(slim)) < len(json.dumps(schema))


def test_slim_schema_preserves_composition_boolean_schemas_and_literal_field_names():
    schema = {
        "oneOf": [
            {"type": "object", "properties": {"title": {"const": "report"}}, "required": ["title"]},
            {"type": "string", "enum": ["cancel"]},
        ],
        "properties": {"forbidden": False},
    }
    slim = _slim_schema(schema)
    validator = Draft202012Validator(slim)
    validator.validate({"title": "report"})
    validator.validate("cancel")
    assert list(validator.iter_errors({"title": "wrong"}))
    assert list(validator.iter_errors({"title": "report", "forbidden": "value"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("oversized", [None, "latest_input", "native_schema"])
async def test_real_budget_retry_preserves_tools_and_reserved_input(monkeypatch, oversized):
    schema = {
        "type": "object",
        "properties": {"quantity": {"type": "integer", "description": "数量说明" * 500}},
        "required": ["quantity"],
        "additionalProperties": False,
    }
    prompt = {
        "user_message": "中" * 3000 if oversized == "latest_input" else "核对产品库存",
        "rules": ["完整处理用户目标；字段必须符合工具契约。"],
        "tool_registry": [
            {
                "tool_id": tool,
                "description": "工具说明" * 1000,
                "actions": [
                    {
                        "action": "query",
                        "description": "查询说明" * 1000,
                        "input_schema": schema,
                        "output_schema": schema,
                    }
                ],
            }
            for tool in ("conversation", "inventory")
        ],
    }
    extra = {
        "tools": [{"type": "function", "function": {"name": "submit_plan"}}],
    }
    if oversized == "native_schema":
        extra["tools"][0]["function"]["description"] = "外部协议" * 1000
    original = copy.deepcopy(prompt)
    manager = ContextWindowManager(token_budget=1500)
    monkeypatch.setattr(
        "app.application.agent_orchestrator.context_window_manager.get_context_window_manager",
        lambda: manager,
    )
    provider = SimpleNamespace(model_name="test-model", chat_completion=AsyncMock())
    messages = [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]
    if oversized:
        with pytest.raises(ContextWindowExceeded):
            await _prepare_model_messages(provider, {}, messages, 200, extra)
    else:
        outbound = await _prepare_model_messages(provider, {}, messages, 200, extra)
        sent = json.loads(outbound[-1]["content"])
        assert sent["user_message"] == original["user_message"]
        assert sent["rules"] == original["rules"]
        assert {tool["tool_id"] for tool in sent["tool_registry"]} == {"conversation", "inventory"}
        for tool in sent["tool_registry"]:
            action = tool["actions"][0]
            assert action["action"] == "query"
            for field in ("input_schema", "output_schema"):
                contract = action.get(field) or sent["tool_schemas"][action[field + "_ref"]]
                validator = Draft202012Validator(contract)
                validator.validate({"quantity": 1})
                assert list(validator.iter_errors({}))
        reserved = 200 + estimate_messages_tokens(
            [{"role": "system", "content": json.dumps(extra, ensure_ascii=False)}]
        )
        assert estimate_messages_tokens(outbound) + reserved <= manager.token_budget
    assert json.loads(messages[-1]["content"]) == original
    provider.chat_completion.assert_not_awaited()
