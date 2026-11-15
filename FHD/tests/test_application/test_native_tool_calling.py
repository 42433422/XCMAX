"""原生 function calling：工具定义、tool_calls 转计划与生成链路。"""

from __future__ import annotations

import json

import pytest

from app.application.workflow.llm_plan_generation import LlmPlanGeneration
from app.application.workflow.tool_calling import (
    build_function_tools,
    function_name,
    plan_from_tool_calls,
    tool_calls_enabled,
)


def _registry() -> dict:
    return {
        "products": {
            "description": "产品",
            "actions": {
                "query": {"risk": "low", "idempotent": True, "required_params": ["keyword"]},
            },
        }
    }


def _tool_call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
    }


def _payload(*calls: dict) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": list(calls)}}]
    }


def test_build_function_tools_maps_names_and_schema() -> None:
    tools, lookup = build_function_tools(_registry())
    names = [item["function"]["name"] for item in tools]
    assert function_name("products", "query") in names
    assert lookup[function_name("products", "query")] == ("products", "query")
    entry = next(item for item in tools if item["function"]["name"] == "products__query")
    assert entry["type"] == "function"
    assert entry["function"]["parameters"]["type"] == "object"


def test_plan_from_tool_calls_builds_parallel_nodes() -> None:
    _tools, lookup = build_function_tools(_registry())
    plan = plan_from_tool_calls(
        _payload(
            _tool_call("products__query", {"keyword": "门"}, "a"),
            _tool_call("products__query", {"keyword": "窗"}, "b"),
        ),
        plan_id="p1",
        message="查门和窗",
        context=None,
        lookup=lookup,
    )
    assert plan is not None
    assert plan.intent == "native_tool_calls"
    assert [node.node_id for node in plan.nodes] == ["call_1", "call_2"]
    assert plan.nodes[0].params == {"keyword": "门"}
    assert all(node.depends_on == [] for node in plan.nodes)


def test_plan_from_tool_calls_ignores_unknown_function() -> None:
    _tools, lookup = build_function_tools(_registry())
    plan = plan_from_tool_calls(
        _payload(_tool_call("unknown__action", {})),
        plan_id="p1",
        message="x",
        context=None,
        lookup=lookup,
    )
    assert plan is None


@pytest.mark.parametrize("payload", [None, {}, {"choices": []}, {"choices": [{"message": {}}]}])
def test_plan_from_tool_calls_returns_none_without_calls(payload) -> None:
    assert plan_from_tool_calls(payload, plan_id="p1", message="x", context=None, lookup={}) is None


def test_tool_calls_switch(monkeypatch) -> None:
    monkeypatch.delenv("XCAGI_PLAN_TOOL_CALLS", raising=False)
    assert tool_calls_enabled() is True
    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "0")
    assert tool_calls_enabled() is False


def test_generate_uses_native_tool_calls() -> None:
    captured: dict = {}

    class Conversation:
        def get_context(self, user_id: str):
            return None

    def completion(**kwargs):
        captured.update(kwargs)
        return _payload(_tool_call("products__query", {"keyword": "门"}))

    generator = LlmPlanGeneration(Conversation(), completion, lambda: None)
    plan = generator.generate("p1", "u1", "查门", _registry(), {})

    assert plan is not None
    assert plan.intent == "native_tool_calls"
    assert plan.nodes[0].tool_id == "products"
    assert plan.nodes[0].params == {"keyword": "门"}
    assert captured["tool_choice"] == "auto"
    assert captured["tools"]


def test_generate_falls_back_when_completion_rejects_tools(monkeypatch) -> None:
    class Conversation:
        def get_context(self, user_id: str):
            return None

    calls: list[dict] = []

    def completion(**kwargs):
        calls.append(kwargs)
        if "tools" in kwargs:
            raise TypeError("unexpected keyword argument 'tools'")
        return {"choices": [{"message": {"content": '{"mode":"reply","reply":"好的"}'}}]}

    monkeypatch.setenv("XCAGI_PLAN_TOOL_CALLS", "1")
    generator = LlmPlanGeneration(Conversation(), completion, lambda: None)
    plan = generator.generate("p1", "u1", "你好", _registry(), {})

    assert plan is not None
    assert plan.metadata["response_mode"] == "reply"
    assert len(calls) == 2
    assert "tools" in calls[0] and "tools" not in calls[1]
