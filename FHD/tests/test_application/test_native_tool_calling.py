"""Native and JSON planning share one typed, dependency-preserving envelope."""

import json
from unittest.mock import Mock

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
                }
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
def test_native_actions_never_reinterpret_shadow_text_or_request_a_new_plan(mode, transport):
    response = _native(name="unknown__write")
    message = response["choices"][0]["message"]
    if transport == "function_call":
        message["function_call"] = message.pop("tool_calls")[0]["function"]
    message["content"] = json.dumps(_graph())
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
def test_rejected_native_response_stays_rejected_through_workflow_planner(invalid):
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
    plan = planner.plan("u1", "先查询再导出", {}, {})
    assert plan.metadata["planning_rejected"] is True
    assert plan.metadata["planning_unavailable"] is True
    assert all(node.tool_id == "clarify" for node in plan.nodes)
    assert completion.call_count == 1


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
            return {"choices": [{"message": {"content": json.dumps(_graph())}}]}

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
