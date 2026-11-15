"""模型原生 function calling 到 PlanGraph 的转换。

只在「模型返回 tool_calls」时生效；结果仍然作为普通计划进入现有校验、风险门、
审批与执行链，不直接执行，也不绕过任何治理边界。模型未返回 tool_calls 时，
调用方继续走原有 JSON 计划解析。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from app.application.workflow.llm_plan_generation import _tool_specs
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

logger = logging.getLogger(__name__)

_ENV_TOOL_CALLS = "XCAGI_PLAN_TOOL_CALLS"
_MAX_NATIVE_CALLS = 12
_NAME_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def tool_calls_enabled() -> bool:
    raw = str(os.environ.get(_ENV_TOOL_CALLS) or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _slug(value: str) -> str:
    return _NAME_SAFE.sub("_", str(value or "")).strip("_") or "tool"


def function_name(tool_id: str, action: str) -> str:
    return f"{_slug(tool_id)}__{_slug(action)}"[:64]


def build_function_tools(
    tool_registry: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """把注册表转换为 OpenAI 兼容的 function 定义与反查表。"""
    tools: list[dict[str, Any]] = []
    lookup: dict[str, tuple[str, str]] = {}
    for spec in _tool_specs(tool_registry):
        tool_id = str(spec.get("tool_id") or "")
        if not tool_id:
            continue
        for action in spec.get("actions") or []:
            if not isinstance(action, dict):
                continue
            action_name = str(action.get("action") or "")
            if not action_name:
                continue
            name = function_name(tool_id, action_name)
            schema = action.get("input_schema")
            parameters = (
                schema
                if isinstance(schema, dict) and schema.get("type") == "object"
                else {"type": "object", "properties": {}}
            )
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(action.get("description") or "")[:240],
                        "parameters": parameters,
                    },
                }
            )
            lookup[name] = (tool_id, action_name)
    return tools, lookup


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def plan_from_tool_calls(
    payload: dict[str, Any] | None,
    *,
    plan_id: str,
    message: str,
    context: dict[str, Any] | None,
    lookup: dict[str, tuple[str, str]],
) -> PlanGraph | None:
    """把 ``tool_calls`` 转成无依赖的并行计划节点；无可用调用时返回 None。"""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message_obj = choices[0].get("message")
    if not isinstance(message_obj, dict):
        return None
    calls = message_obj.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return None

    nodes: list[WorkflowNode] = []
    for index, call in enumerate(calls[:_MAX_NATIVE_CALLS], start=1):
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        target = lookup.get(str(function.get("name") or ""))
        if target is None:
            logger.warning("原生工具调用未匹配到已授权动作，回退文本计划")
            return None
        tool_id, action = target
        nodes.append(
            WorkflowNode(
                node_id=f"call_{index}",
                tool_id=tool_id,
                action=action,
                params=_parse_arguments(function.get("arguments")),
                risk="low",
                idempotent=True,
                description="模型原生工具调用",
            )
        )
    if not nodes:
        return None
    from app.application.workflow.workflow_types import normalize_workflow_risk

    return PlanGraph(
        plan_id=plan_id,
        intent="native_tool_calls",
        todo_steps=[],
        nodes=nodes,
        risk_level=normalize_workflow_risk("low"),
        metadata={
            "planner": "native_tool_calls",
            "response_mode": "workflow",
            "message": message,
        },
    )


__all__ = [
    "build_function_tools",
    "function_name",
    "plan_from_tool_calls",
    "tool_calls_enabled",
]
