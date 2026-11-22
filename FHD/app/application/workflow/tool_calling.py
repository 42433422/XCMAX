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


def slim_schema(schema: Any) -> Any:
    """只保留规划所需结构：字段名、类型、枚举、必填与简短说明。输出 schema、执行元数据与长描述不进入规划 prompt，避免工具目录挤占上下文。"""
    if not isinstance(schema, dict):
        return {}
    slim: dict[str, Any] = {}
    for key in ("type", "required", "enum", "additionalProperties"):
        if key in schema:
            slim[key] = schema[key]
    properties = schema.get("properties")
    if isinstance(properties, dict):
        slim_props: dict[str, Any] = {}
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                slim_props[name] = prop
                continue
            item: dict[str, Any] = {}
            for key in ("type", "enum", "items"):
                if key in prop:
                    item[key] = prop[key]
            description = str(prop.get("description") or "").strip()
            if description:
                item["description"] = description[:80]
            slim_props[name] = item
        slim["properties"] = slim_props
    if isinstance(schema.get("items"), dict):
        slim["items"] = slim_schema(schema["items"])
    return slim


def tool_specs(tool_registry: dict[str, Any]) -> list[dict[str, Any]]:
    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

    contracts = build_tool_specs_v2()
    result = []
    # 固定顺序保证 system 前缀稳定，命中供应商的 prompt 缓存。
    for tool_id in sorted(tool_registry, key=str):
        spec = tool_registry[tool_id]
        actions = spec.get("actions", {})
        action_specs = []
        for name, metadata in actions.items():
            contract = contracts.get((str(tool_id), str(name)))
            raw_schema = getattr(contract, "input_schema", {})
            action_spec = {
                "action": name,
                "description": str(
                    getattr(contract, "description", "") or spec.get("description") or ""
                )[:160],
                "risk": metadata.get("risk", "low"),
                "idempotent": bool(metadata.get("idempotent", False)),
                "input_schema": slim_schema(raw_schema),
            }
            # Keep differing legacy requirements; never rewrite nested schemas. Slim catalog omits output_schema.
            required = metadata.get("required_params", [])
            if required != raw_schema.get("required", []):
                action_spec["required_params"] = required
            action_specs.append(action_spec)
        result.append(
            {
                "tool_id": tool_id,
                "description": spec.get("description", ""),
                "actions": action_specs,
            }
        )
    return result


def plan_function_tools() -> list[dict[str, Any]]:
    return [convert_to_openai_tool(SubmitWorkflowPlan)]


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
        # JSON envelopes, including truncated ones, retain the existing strict
        # parser/repair contract. Native tool_choice=auto also permits plain text.
        structural = re.sub(r"^```(?:json)?\s*", "", raw, count=1, flags=re.I)
        if not allow_text_reply or not raw or structural.startswith(("{", "[")):
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


def unsupported_tool_parameter(error: TypeError) -> bool:
    return bool(
        re.search(r"""unexpected keyword argument ['"](?:tools|tool_choice)['"]""", str(error))
    )
