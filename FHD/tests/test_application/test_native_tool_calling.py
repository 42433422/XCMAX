"""Native and JSON planning share one typed, dependency-preserving envelope."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.application.workflow.llm_plan_generation import LlmPlanGeneration, _decode_completion
from app.application.workflow.tool_calling import (
    PLAN_SCHEMA,
    SubmitWorkflowPlan,
    native_plan_payload,
    plan_function_tools,
    tool_calls_enabled,
)


def _graph():
    return {
        "mode": "workflow",
        "nodes": [
            {
                "node_id": "read",
                "tool_id": "products",
                "action": "query",
                "params": {"keyword": "门"},
            },
            {
                "node_id": "export",
                "tool_id": "reports",
                "action": "export",
                "params": {"source": "{{read.data}}"},
                "depends_on": ["read"],
            },
        ],
    }


def _native(graph=None, *, name="SubmitWorkflowPlan", arguments=None):
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "envelope_1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments
                                if arguments is not None
                                else json.dumps(graph or _graph()),
                            },
                        }
                    ]
                },
            }
        ]
    }


def _generator(completion):
    return LlmPlanGeneration(Mock(get_context=Mock(return_value=None)), completion, Mock())


def test_native_envelope_retains_all_dependencies_and_result_references():
    response = native_plan_payload(_native())
    parsed, nodes = _decode_completion(response)
    assert parsed["mode"] == "workflow"
    assert [node.node_id for node in nodes] == ["read", "export"]
    assert nodes[1].depends_on == ["read"]
    assert nodes[1].params["source"] == "{{read.data}}"
    assert plan_function_tools()[0]["function"]["name"] == SubmitWorkflowPlan.__name__
    assert "depends_on" in PLAN_SCHEMA["$defs"]["PlanNode"]["properties"]


def test_native_and_json_use_identical_validation():
    graph = _graph()
    native = _decode_completion(native_plan_payload(_native(graph)))
    text = _decode_completion({"choices": [{"message": {"content": json.dumps(graph)}}]})
    assert native == text


@pytest.mark.parametrize(
    "content",
    [
        "向量表示一组数值，可以用于比较语义相似度。",
        "```python\nitems = [1, 2]\nprint(items[0])\n```",
        "春风拂过窗前，远山渐渐明亮。",
    ],
)
def test_native_auto_text_uses_typed_reply_without_shape_repair(content, monkeypatch):
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1")
    completion = Mock(
        return_value={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
    )
    plan = _generator(completion).generate("p1", "u1", "请解释并给出示例", {}, {})
    assert plan.metadata["response_mode"] == "reply"
    assert plan.metadata["reply"] == content
    assert len(plan.nodes) == 1
    assert (plan.nodes[0].tool_id, plan.nodes[0].action) == ("conversation", "reply")
    assert plan.nodes[0].params == {"response": content}
    completion.assert_called_once()
    assert completion.call_args.kwargs["tool_choice"] == "auto"


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("prefix", ["", "```json\n", "```JSON\n", "```\n"])
def test_native_text_does_not_reinterpret_structured_or_truncated_plans(
    native, prefix, monkeypatch
):
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1" if native else "0")
    completion = Mock(
        return_value={
            "choices": [{"message": {"content": prefix + '{"mode":"workflow","nodes":['}}]
        }
    )
    assert _generator(completion).generate("p1", "u1", "查询并导出", {}, {}) is None


def test_plain_text_is_not_native_when_tools_were_not_offered(monkeypatch):
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "0")
    completion = Mock(return_value={"choices": [{"message": {"content": "普通文本"}}]})
    assert _generator(completion).generate("p1", "u1", "介绍向量", {}, {}) is None
    assert "tools" not in completion.call_args.kwargs


def test_legacy_completion_without_tool_parameters_keeps_json_contract(monkeypatch):
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1")
    plain = {"choices": [{"message": {"content": "普通文本"}}]}
    completion = Mock(side_effect=[TypeError("unexpected keyword argument 'tools'"), plain, plain])
    assert _generator(completion).generate("p1", "u1", "介绍向量", {}, {}) is None
    assert completion.call_count == 3
    assert "tools" not in completion.call_args_list[1].kwargs


@pytest.mark.parametrize("finish_reason", ["length", "tool_calls", "content_filter"])
def test_incomplete_native_text_is_rejected(finish_reason, monkeypatch):
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1")
    completion = Mock(
        return_value={
            "choices": [{"finish_reason": finish_reason, "message": {"content": "未完整的回答"}}]
        }
    )
    assert _generator(completion).generate("p1", "u1", "介绍向量", {}, {}) is None
    completion.assert_called_once()


@pytest.mark.parametrize(
    "arguments",
    [
        "",
        "[]",
        "null",
        "not-json",
        '{"mode":"workflow"',
        '{"mode":"workflow","nodes":[{"tool_id":"x","action":"y","params":{"value":NaN}}]}',
    ],
)
def test_malformed_or_nonfinite_envelope_is_never_repaired_into_business_action(arguments):
    completion = Mock(return_value=_native(arguments=arguments))
    context = {}
    assert _generator(completion).generate("p1", "u1", "查询并导出", {}, context) is None
    assert completion.call_count == 1
    assert "planning_failure_reason" in context


@pytest.mark.parametrize("name", ["products__query", "unknown", ""])
def test_legacy_or_unknown_business_functions_cannot_bypass_complete_graph(name):
    with pytest.raises(ValueError):
        native_plan_payload(_native(name=name))


def test_multiple_native_envelopes_are_rejected_without_partial_execution():
    response = _native()
    response["choices"][0]["message"]["tool_calls"] *= 2
    completion = Mock(return_value=response)
    assert _generator(completion).generate("p1", "u1", "先查询再导出", {}, {}) is None
    assert completion.call_count == 1


@pytest.mark.parametrize("call_id", ["", " ", 7, [], {}])
def test_explicit_native_call_id_must_remain_a_nonempty_string(call_id):
    response = _native()
    response["choices"][0]["message"]["tool_calls"][0]["id"] = call_id
    with pytest.raises(ValueError):
        native_plan_payload(response)


@pytest.mark.parametrize("omit", [False, True])
def test_optional_native_call_id_does_not_replace_workflow_node_identity(omit):
    response = _native()
    call = response["choices"][0]["message"]["tool_calls"][0]
    if omit:
        call.pop("id")
    else:
        call["id"] = None
    _, nodes = _decode_completion(native_plan_payload(response))
    assert [node.node_id for node in nodes] == ["read", "export"]
    assert nodes[1].depends_on == ["read"]


@pytest.mark.parametrize("arguments", [None, {}, {"price": float("nan")}])
def test_native_arguments_require_json_text(arguments):
    response = _native()
    response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    completion = Mock(return_value=response)
    assert _generator(completion).generate("p1", "u1", "查询并导出", {}, {}) is None
    assert completion.call_count == 1


@pytest.mark.parametrize("transport", ["tool_calls", "function_call"])
@pytest.mark.parametrize("mode", ["full", "light", "repair"])
@pytest.mark.parametrize("plain_text", [False, True])
def test_native_actions_never_reinterpret_shadow_text_or_request_a_new_plan(
    mode, transport, plain_text
):
    response = _native(name="unknown__write")
    message = response["choices"][0]["message"]
    if transport == "function_call":
        message["function_call"] = message.pop("tool_calls")[0]["function"]
    message["content"] = "已经完成" if plain_text else json.dumps(_graph())
    completion = Mock(return_value=response)
    generator = _generator(completion)
    if mode == "repair":
        plan = generator._repair_output_shape(
            plan_id="p1", message="查询并导出", context={}, raw_content="invalid", error="invalid"
        )
    else:
        plan = generator.generate("p1", "u1", "你好" if mode == "light" else "查询并导出", {}, {})
    assert plan is None
    assert completion.call_count == 1


@pytest.mark.parametrize("mode", ["light", "repair"])
def test_valid_native_envelope_is_rejected_when_that_protocol_was_not_offered(mode):
    completion = Mock(return_value=_native())
    generator = _generator(completion)
    if mode == "repair":
        plan = generator._repair_output_shape(
            plan_id="p1", message="查询并导出", context={}, raw_content="invalid", error="invalid"
        )
    else:
        plan = generator.generate("p1", "u1", "你好", {}, {})
    assert plan is None
    assert completion.call_count == 1


@pytest.mark.parametrize("invalid", ["batch", "unknown_function", "legacy_function"])
def test_rejected_native_response_stays_rejected_through_workflow_planner(invalid, monkeypatch):
    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
    from app.application.workflow.planner import LLMWorkflowPlanner

    response = _native()
    message = response["choices"][0]["message"]
    if invalid == "batch":
        message["tool_calls"] *= 2
    elif invalid == "unknown_function":
        message["tool_calls"][0]["function"]["name"] = "unknown__write"
    else:
        message["function_call"] = message.pop("tool_calls")[0]["function"]
    message["content"] = json.dumps(_graph())
    completion = Mock(return_value=response)
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    request = "先查询再导出"
    plan = planner.plan("u1", request, {}, {})
    reason = "原生调用未提交有效的完整依赖图，本轮未执行任何操作"
    assert plan.metadata["planning_rejected"] is True
    assert plan.metadata["planning_unavailable"] is False
    assert plan.metadata["planning_failure_kind"] == "plan_format_invalid"
    assert plan.metadata["rejection_reason"] == reason
    assert all(node.tool_id == "clarify" for node in plan.nodes)
    assert completion.call_count == 1

    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry", lambda: {}
    )
    callbacks, risk_gate = Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    dispatch = PlannedWorkflowDispatch(
        {}, callbacks, Mock(plan=Mock(return_value=plan)), risk_gate, Mock()
    )
    result = dispatch.handle("u1", request, "pro", {}, request)
    assert result["data"]["error_code"] == "workflow_plan_rejected"
    assert result["data"]["reason"] == reason
    assert result["data"]["execution_started"] is False
    assert "格式校验" in result["response"]
    risk_gate.evaluate.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("params", []),
        ("depends_on", "read"),
        ("idempotent", "false"),
        ("branches", [{"target": "n", "condition": []}]),
    ],
)
def test_successful_json_responses_cannot_skip_type_validation(field, value):
    graph = _graph()
    graph["nodes"][0][field] = value
    assert _decode_completion({"choices": [{"message": {"content": json.dumps(graph)}}]}) is None


def test_tool_prefilter_is_the_authoritative_catalog_for_both_transports(monkeypatch):
    from app.application.workflow import llm_plan_generation as generation

    registry = {"products": {"actions": {"query": {}}}, "dangerous": {"actions": {"delete": {}}}}
    monkeypatch.setattr(
        generation,
        "select_tools_for_prompt",
        lambda registry, *_: {"products": registry["products"]},
    )
    completion = Mock(return_value=_native())
    plan = _generator(completion).generate("p1", "u1", "查询产品并导出", registry, {})
    assert plan and plan.nodes[1].depends_on == ["read"]
    request = json.loads(completion.call_args.kwargs["messages"][1]["content"])
    assert [spec["tool_id"] for spec in request["tool_registry"]] == ["products"]
    assert completion.call_args.kwargs["tools"] == plan_function_tools()
    assert request["output_schema"] == PLAN_SCHEMA
    # The generated graph is still untrusted here; planner admission checks actions.


def test_old_completion_transport_can_use_same_json_schema_without_tools():
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if "tools" in kwargs:
            raise TypeError("unexpected keyword argument 'tools'")
        return {"choices": [{"message": {"content": json.dumps(_graph())}}]}

    plan = _generator(completion).generate("p1", "u1", "先查询再导出", {}, {})
    assert plan and plan.nodes[1].depends_on == ["read"]
    assert len(calls) == 2 and "tools" not in calls[-1]


def test_unrelated_type_error_is_not_retried_as_legacy_transport():
    completion = Mock(side_effect=TypeError("invalid business input"))
    assert _generator(completion).generate("p1", "u1", "查询产品", {}, {}) is None
    assert completion.call_count == 1


def test_default_gateway_legacy_provider_signature_really_falls_back(monkeypatch):
    from app.application.workflow.planner_llm_gateway import request_planner_completion

    provider_calls = []

    class Provider:
        async def chat_completion(self, *, messages, temperature, max_tokens):
            provider_calls.append(messages)
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(_graph())}}]
            }

    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1")
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **kwargs: Provider()
    )
    meter = Mock()
    monkeypatch.setattr(
        "app.application.workflow.planner_llm_gateway._meter_planner_completion", meter
    )
    gateway = Mock(wraps=request_planner_completion)
    plan = _generator(gateway).generate("p1", "u1", "先查询再导出", {}, {})
    assert plan is not None
    assert plan.nodes[1].depends_on == ["read"]
    assert gateway.call_count == 2
    assert gateway.call_args_list[0].kwargs["tools"] == plan_function_tools()
    assert "tools" not in gateway.call_args_list[1].kwargs
    assert len(provider_calls) == 1
    meter.assert_called_once()


def test_tool_calls_switch(monkeypatch):
    monkeypatch.delenv("XCAGI_PLAN_TOOL_CALLS", raising=False)
    assert tool_calls_enabled()
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "0")
    assert not tool_calls_enabled()


def test_semantic_replan_expands_catalog_without_reviving_retired_tools():
    registry = {
        "customers": {"actions": {"query": {}}},
        "excel_toolkit": {"actions": {"view": {}}},
        "import_excel_to_database": {"actions": {"execute": {}}},
    }
    completion = Mock(return_value=_native())
    generator = _generator(completion)
    generator.generate(
        "p1", "u1", "查询客户", registry, {}, coverage_feedback={"error": "遗漏附件核对"}
    )
    prompt = json.loads(completion.call_args.kwargs["messages"][1]["content"])
    assert {spec["tool_id"] for spec in prompt["tool_registry"]} == {"customers", "excel_toolkit"}


def _expanded_tool_specs(prompt):
    registry = copy.deepcopy(prompt["tool_registry"])
    for tool in registry:
        for action in tool["actions"]:
            action.setdefault("description", tool["description"])
            for field in ("input_schema", "output_schema"):
                reference = action.pop(f"{field}_ref", None)
                if reference is not None:
                    action[field] = prompt["tool_schemas"][reference]
    return registry


def test_catalog_compaction_preserves_independent_local_schema_references():
    from app.application.workflow.planner_llm_gateway import _compact_tool_registry

    schema = {
        "$defs": {"name": {"type": "string", "minLength": 2}},
        "type": "object",
        "properties": {"name": {"$ref": "#/$defs/name"}},
        "required": ["name"],
        "additionalProperties": False,
    }
    prompt = {
        "tool_registry": [
            {
                "tool_id": "customers",
                "description": "Customer records",
                "actions": [
                    {
                        "action": action,
                        "description": description,
                        "input_schema": schema,
                        "output_schema": {"type": "object"},
                        "risk": "high",
                        "idempotent": False,
                        "required_params": ["name"],
                    }
                    for action, description in (
                        ("create", "Customer records"),
                        ("update", "Update only"),
                    )
                ],
            }
        ]
    }
    original = copy.deepcopy(prompt["tool_registry"])
    _compact_tool_registry(prompt)
    assert prompt["tool_schemas"]
    assert _expanded_tool_specs(prompt) == original
    compacted = copy.deepcopy(prompt)
    _compact_tool_registry(prompt)
    assert prompt == compacted


def test_catalog_omits_only_duplicate_required_annotation(monkeypatch):
    from jsonschema import Draft202012Validator

    from app.application.workflow.llm_plan_generation import _tool_specs
    from app.application.workflow.planner_llm_gateway import _compact_tool_registry

    schema = {
        "$defs": {
            "row": {
                "type": "object",
                "properties": {"quantity": {"type": "integer", "minimum": 1}},
                "required": ["quantity"],
                "additionalProperties": False,
            }
        },
        "type": "object",
        "properties": {
            "rows": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/row"}},
            "warehouse_id": {"type": "integer"},
            "warehouse_name": {"type": "string", "minLength": 1},
        },
        "required": ["rows"],
        "anyOf": [{"required": ["warehouse_id"]}, {"required": ["warehouse_name"]}],
        "additionalProperties": False,
    }
    contract = SimpleNamespace(input_schema=schema, output_schema=copy.deepcopy(schema))
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_spec.build_tool_specs_v2",
        lambda: {("inventory", action): contract for action in ("create", "update")},
    )
    registry = {
        "inventory": {
            "description": "Inventory",
            "actions": {
                "create": {"required_params": ["rows"]},
                "update": {"required_params": ["rows", "warehouse_id"]},
            },
        }
    }
    original_schema = copy.deepcopy(schema)
    prompt = {"tool_registry": _tool_specs(registry)}
    _compact_tool_registry(prompt)
    actions = _expanded_tool_specs(prompt)[0]["actions"]
    assert "required_params" not in actions[0]
    assert actions[1]["required_params"] == ["rows", "warehouse_id"]
    for action in actions:
        for field in ("input_schema", "output_schema"):
            assert action[field] == original_schema
            validator = Draft202012Validator(action[field])
            assert validator.is_valid({"rows": [{"quantity": 1}], "warehouse_name": "主仓"})
            assert not validator.is_valid({"rows": [{}], "warehouse_name": "主仓"})
            assert not validator.is_valid({"rows": [{"quantity": 0}], "warehouse_id": 1})
            assert not validator.is_valid({"rows": [{"quantity": 1}]})
    assert contract.input_schema == contract.output_schema == original_schema


def test_real_catalog_remains_losslessly_reconstructable_with_smaller_budget():
    from app.application.agent_orchestrator.context_window_manager import estimate_messages_tokens
    from app.application.facades.tools_facade import get_workflow_tool_registry
    from app.application.workflow.llm_plan_generation import _tool_specs
    from app.application.workflow.planner_llm_gateway import _compact_tool_registry

    registry = get_workflow_tool_registry()
    projected = _tool_specs(registry)
    original = copy.deepcopy(projected)
    for tool in original:
        for action in tool["actions"]:
            action["required_params"] = registry[tool["tool_id"]]["actions"][action["action"]].get(
                "required_params", []
            )
    previous = {"tool_registry": copy.deepcopy(original)}
    prompt = {"tool_registry": projected}
    for value in (previous, prompt):
        _compact_tool_registry(value)
    restored = _expanded_tool_specs(prompt)
    for tool in restored:
        for action in tool["actions"]:
            action.setdefault("required_params", action["input_schema"].get("required", []))
    assert restored == original  # Includes every tool, action, schema and execution annotation.
    encoded = [
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) for value in (previous, prompt)
    ]
    assert len(encoded[1].encode()) < len(encoded[0].encode())
    assert estimate_messages_tokens(
        [{"role": "user", "content": encoded[1]}]
    ) < estimate_messages_tokens([{"role": "user", "content": encoded[0]}])


@pytest.mark.parametrize("profile", ["normal", "pro_default"])
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("replanning", [False, True])
def test_full_catalog_reaches_real_budget_gateway_without_losing_contracts(
    monkeypatch, profile, native, replanning
):
    from app.application.agent_orchestrator.context_window_manager import estimate_messages_tokens
    from app.application.facades.tools_facade import get_workflow_tool_registry
    from app.application.workflow.llm_plan_generation import _tool_specs
    from app.application.workflow.planner_llm_gateway import request_planner_completion
    from app.application.workflow.planning_graph_policy import filter_registry_for_profile
    from app.infrastructure.llm.model_context_windows import resolve_token_budget

    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1" if native else "0")
    payload = {"mode": "reply", "reply": "已读取"}
    response = (
        _native(payload) if native else {"choices": [{"message": {"content": json.dumps(payload)}}]}
    )
    response["choices"][0]["finish_reason"] = "tool_calls" if native else "stop"
    provider = SimpleNamespace(
        _adapter=SimpleNamespace(model_name="gpt-4o"),
        chat_completion=AsyncMock(return_value=response),
    )
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **kwargs: provider
    )
    registry = filter_registry_for_profile(get_workflow_tool_registry(), profile)
    plan = _generator(request_planner_completion).generate(
        "p1",
        "u1",
        "说明工作方式",
        registry,
        {},
        coverage_feedback={"error": "核对全部可用工具"} if replanning else None,
    )
    assert plan is not None
    provider.chat_completion.assert_awaited_once()
    sent = provider.chat_completion.call_args.kwargs
    prompt = json.loads(sent["messages"][-1]["content"])
    assert _expanded_tool_specs(prompt) == _tool_specs(registry)
    assert prompt["user_message"] == "说明工作方式"
    schema_tokens = 0
    if native:
        assert sent["tools"] == plan_function_tools()
        schema_tokens = estimate_messages_tokens(
            [
                {
                    "role": "system",
                    "content": json.dumps({"tools": sent["tools"]}, ensure_ascii=False),
                }
            ]
        )
    else:
        assert "tools" not in sent
    assert estimate_messages_tokens(sent["messages"]) + sent[
        "max_tokens"
    ] + schema_tokens <= resolve_token_budget("gpt-4o")
