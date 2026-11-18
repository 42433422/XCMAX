"""模型原生 function calling 到 PlanGraph 的转换。

只在「模型返回 tool_calls」时生效；结果仍然作为普通计划进入现有校验、风险门、
审批与执行链，不直接执行，也不绕过任何治理边界。模型未返回 tool_calls 时，
调用方继续走原有 JSON 计划解析。
"""

from __future__ import annotations

import hashlib
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
    raw = f"{_slug(tool_id)}__{_slug(action)}"
    if (
        len(raw) <= 64
        and _slug(tool_id) == tool_id
        and _slug(action) == action
        and "__" not in tool_id
        and "__" not in action
    ):
        return raw
    digest = hashlib.sha256(json.dumps([tool_id, action], ensure_ascii=False).encode()).hexdigest()[
        :12
    ]
    return f"{raw[:51]}_{digest}"


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
            if name in lookup and lookup[name] != (tool_id, action_name):
                raise ValueError("原生工具函数名冲突，拒绝含糊映射")
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


def _parse_arguments(raw: Any) -> dict[str, Any] | None:
    """Invalid or non-finite arguments must never turn into an empty write filter."""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            return None
        json.dumps(parsed, allow_nan=False)
        return parsed
    except (ValueError, TypeError):
        return None


def plan_from_tool_calls(
    payload: dict[str, Any] | None,
    *,
    plan_id: str,
    message: str,
    context: dict[str, Any] | None,
    lookup: dict[str, tuple[str, str]],
) -> PlanGraph | None:
    """Convert a single native tool call; reject batches without explicit dependencies."""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message_obj = choices[0].get("message")
    if not isinstance(message_obj, dict):
        return None
    calls = message_obj.get("tool_calls")
    if not isinstance(calls, list) or not calls or len(calls) > _MAX_NATIVE_CALLS:
        return None
    # Native tool_calls contain no dependency graph.  Executing multiple calls
    # as independent nodes can violate explicit "first X, then Y" user intent.
    # Until the planner emits a validated dependency graph, accept only one call.
    if len(calls) != 1:
        logger.warning("Rejecting multi-tool native batch without dependency graph")
        return None

    nodes: list[WorkflowNode] = []
    seen_call_ids: set[str] = set()
    for index, call in enumerate(calls, start=1):
        if not isinstance(call, dict) or call.get("type") != "function":
            return None
        call_id = call.get("id")
        if call_id is not None:
            if not isinstance(call_id, str) or not call_id.strip() or call_id in seen_call_ids:
                return None
            seen_call_ids.add(call_id)
        function = call.get("function")
        if not isinstance(function, dict):
            return None
        target = lookup.get(str(function.get("name") or ""))
        if target is None:
            logger.warning("原生工具调用未匹配到已授权动作，回退文本计划")
            return None
        params = _parse_arguments(function.get("arguments"))
        if params is None:
            return None
        tool_id, action = target
        nodes.append(
            WorkflowNode(
                node_id=f"call_{index}",
                tool_id=tool_id,
                action=action,
                params=params,
                risk="low",
                idempotent=False,
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


def unsupported_tool_parameter(error: TypeError) -> bool:
    return bool(
        re.search(r"""unexpected keyword argument ['"](?:tools|tool_choice)['"]""", str(error))
    )
