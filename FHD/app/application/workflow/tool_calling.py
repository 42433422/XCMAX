"""LangChain/Pydantic plan transport; native calls submit a complete graph.

The function is a structured output envelope, never an executable business tool.
Both JSON and native responses pass the same schema and downstream admission.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.infrastructure.llm.response_completion import completion_is_incomplete


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class PlanBranch(_Output):
    target: str = Field(min_length=1)
    condition: dict[str, Any] = Field(default_factory=dict)


class PlanNode(_Output):
    node_id: str = ""
    tool_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    risk: Literal["low", "medium", "high"] = "low"
    idempotent: bool = False
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    next: str | None = None
    branches: list[PlanBranch] = Field(default_factory=list)


class SubmitWorkflowPlan(_Output):
    """Submit the complete reply or business graph, including every dependency.

    Use only authorized tool_registry actions. Missing facts require clarification;
    never claim that a tool was executed while constructing this plan.
    """

    mode: Literal["reply", "workflow"]
    reply: str = Field(default="", max_length=12_000)
    intent: str = ""
    todo_steps: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    nodes: list[PlanNode] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def complete_mode(self) -> SubmitWorkflowPlan:
        if self.mode == "reply" and (not self.reply or self.nodes):
            raise ValueError("reply 必须非空且不得包含 nodes")
        if self.mode == "workflow" and (not self.nodes or self.reply):
            raise ValueError("workflow 必须包含 nodes，不能混入 reply")
        json.dumps(self.model_dump(), allow_nan=False)
        return self


PLAN_PARSER = PydanticOutputParser(pydantic_object=SubmitWorkflowPlan)
PLAN_SCHEMA = SubmitWorkflowPlan.model_json_schema()


def plan_output_schema(tool_registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bind the typed transport to exact advertised tool/action pairs per request."""
    schema = deepcopy(PLAN_SCHEMA)
    if tool_registry is not None:
        # clarify.ask is the existing internal control node admitted without a
        # business registry entry. It asks a question and cannot execute a tool.
        actions = {
            tool_id: list(spec.get("actions") or {})
            for tool_id, spec in tool_registry.items()
            if spec.get("actions")
        }
        actions["clarify"] = ["ask"]
        variants = [
            {
                "properties": {
                    "tool_id": {"const": tool_id},
                    "action": {"enum": names},
                },
                "required": ["tool_id", "action"],
            }
            for tool_id, names in actions.items()
        ]
        schema["$defs"]["PlanNode"]["oneOf"] = variants
    return schema


def plan_function_tools(tool_registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    tool = convert_to_openai_tool(SubmitWorkflowPlan)
    if tool_registry is not None:
        constraint = plan_output_schema(tool_registry)["$defs"]["PlanNode"]
        node_schema = tool["function"]["parameters"]["properties"]["nodes"]["items"]
        node_schema.update({key: constraint[key] for key in ("oneOf", "not") if key in constraint})
    return [tool]


def native_plan_payload(
    response: dict[str, Any], *, allow_text_reply: bool = False
) -> dict[str, Any] | None:
    """Normalize native content or one typed call; never reinterpret rejected calls."""
    if not isinstance(response, dict):
        raise ValueError("原生计划响应必须是对象")
    if completion_is_incomplete(response):
        raise ValueError("模型输出未完整生成")
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if isinstance(message, dict) and message.get("function_call"):
        raise ValueError("原生计划不支持旧式函数信封")
    if not isinstance(message, dict):
        return None
    if not message.get("tool_calls"):
        content = message.get("content")
        raw = content.strip() if isinstance(content, str) else ""
        if not allow_text_reply or not raw:
            return None
        # Ordinary JSON is answer content too. Reserve the plan envelope's
        # discriminant/payload keys; malformed JSON stays on strict plan repair.
        structural = re.sub(r"^```(?:json)?\s*", "", raw, count=1, flags=re.I)
        if structural.startswith(("{", "[")):
            try:
                value = json.loads(structural.removesuffix("```").strip())
                json.dumps(value, allow_nan=False)
            except ValueError:
                return None
            objects = value if isinstance(value, list) else [value]
            if any(
                isinstance(item, dict) and {"mode", "nodes", "reply"}.intersection(item)
                for item in objects
            ):
                return None
        reply = SubmitWorkflowPlan(mode="reply", reply=raw)
        return {"choices": [{"message": {"content": reply.model_dump_json()}}]}
    calls = message["tool_calls"]
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("原生调用必须一次提交完整依赖图")
    call = calls[0]
    function = call.get("function") if isinstance(call, dict) else None
    call_id = call.get("id") if isinstance(call, dict) else None
    if (
        not isinstance(function, dict)
        or call.get("type") != "function"
        or function.get("name") != SubmitWorkflowPlan.__name__
        or not isinstance(function.get("arguments"), str)
        or call_id is not None
        and (not isinstance(call_id, str) or not call_id.strip())
    ):
        raise ValueError("原生调用不是授权的计划输出函数")
    # Reject truncation and non-finite values before schema parsing.
    parsed = json.loads(function["arguments"])
    json.dumps(parsed, allow_nan=False)
    validated = SubmitWorkflowPlan.model_validate(parsed)
    return {"choices": [{"message": {"content": validated.model_dump_json()}}]}


def tool_calls_enabled() -> bool:
    return str(os.environ.get("XCAGI_PLAN_TOOL_CALLS") or "").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def request_json_completion(
    complete: Callable[..., dict[str, Any] | None], **kwargs: Any
) -> dict[str, Any] | None:
    """Offer JSON mode; only a proven legacy keyword rejection may omit it."""
    try:
        return complete(**kwargs, response_format={"type": "json_object"})
    except TypeError as error:
        if not re.search(r"""unexpected keyword argument ['"]response_format['"]""", str(error)):
            raise
        return complete(**kwargs)


def unsupported_tool_parameter(error: TypeError) -> bool:
    return bool(
        re.search(
            r"""unexpected keyword argument ['"](?:tools|tool_choice|response_format)['"]""",
            str(error),
        )
    )
