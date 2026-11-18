"""LangChain/Pydantic plan transport; native calls submit a complete graph.

The function is a structured output envelope, never an executable business tool.
Both JSON and native responses pass the same schema and downstream admission.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


def plan_function_tools() -> list[dict[str, Any]]:
    return [convert_to_openai_tool(SubmitWorkflowPlan)]


def native_plan_payload(response: dict[str, Any]) -> dict[str, Any] | None:
    """Unwrap exactly one full-graph call; reject unordered action batches."""
    if not isinstance(response, dict):
        raise ValueError("原生计划响应必须是对象")
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict) or not message.get("tool_calls"):
        return None
    calls = message["tool_calls"]
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("原生调用必须一次提交完整依赖图")
    call = calls[0]
    function = call.get("function") if isinstance(call, dict) else None
    if (
        not isinstance(function, dict)
        or call.get("type") != "function"
        or function.get("name") != SubmitWorkflowPlan.__name__
        or not isinstance(function.get("arguments"), str)
        or message.get("function_call")
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


def unsupported_tool_parameter(error: TypeError) -> bool:
    return bool(
        re.search(r"""unexpected keyword argument ['"](?:tools|tool_choice)['"]""", str(error))
    )
