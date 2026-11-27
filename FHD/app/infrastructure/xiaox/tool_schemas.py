"""MCP schemas and safe validation feedback from the existing tool catalog."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2
from app.infrastructure.xiaox.tool_names import DIRECT_ACTION_TOOLS, XIAOX_TOOL_NAMES

if TYPE_CHECKING:
    from jsonschema import ValidationError
    from mcp.types import Tool


def schema_violation(error: ValidationError) -> dict[str, str | int | float | list[str]]:
    """Show the matching variant's bad field without exposing its instance or message."""
    while error.validator == "oneOf" and error.context and isinstance(error.instance, dict):
        matching = []
        for index, branch in enumerate(error.validator_value):
            if not isinstance(branch, dict):
                continue
            checks = {
                name: field["const"]
                for name, field in (branch.get("properties") or {}).items()
                if isinstance(field, dict) and "const" in field
            }
            if checks and all(
                name in error.instance and error.instance[name] == value
                for name, value in checks.items()
            ):
                matching.append(index)
        if len(matching) != 1:
            break
        child = next(
            (
                item
                for item in error.context
                if item.schema_path and item.schema_path[0] == matching[0]
            ),
            None,
        )
        if child is None:
            break
        error = child
    schema_path = list(error.absolute_schema_path)
    fields = {
        name
        for keyword, name in zip(schema_path, schema_path[1:], strict=False)
        if keyword == "properties"
    }
    path = "$" + "".join(
        f"[{part}]"
        if isinstance(part, int)
        else f".{part}"
        if part in fields and part.isidentifier()
        else ".*"
        for part in list(error.absolute_path)[:12]
    )
    violation: dict[str, str | int | float | list[str]] = {
        "path": path[:180],
        "validator": str(error.validator or "schema")[:32],
    }
    if error.validator == "type":
        from jsonschema import Draft202012Validator

        expected = error.validator_value
        violation["expected"] = expected if isinstance(expected, list) else str(expected)
        violation["received"] = next(
            (
                name
                for name in ("null", "boolean", "string", "array", "object", "integer", "number")
                if Draft202012Validator.TYPE_CHECKER.is_type(error.instance, name)
            ),
            "unknown",
        )
    if (error.validator == "pattern" and len(error.validator_value) <= 256) or error.validator in {
        "maximum",
        "minimum",
        "maxLength",
        "minLength",
        "maxItems",
        "minItems",
    }:
        violation["expected"] = error.validator_value
    if error.validator == "additionalProperties" and not error.schema.get("patternProperties"):
        properties = error.schema.get("properties", {})
        if isinstance(properties, dict) and len(properties) <= 24:
            violation["allowed"] = list(properties)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [
            name
            for name in error.validator_value
            if name not in error.instance and len(name) <= 48 and name.isidentifier()
        ][:4]
        if missing:
            violation["missing"] = missing
    return violation


def action_schema_violation(
    spec: ToolActionSpecV2, params: dict[str, Any]
) -> dict[str, str | int | float | list[str]]:
    from jsonschema import Draft202012Validator, SchemaError
    from referencing import Registry
    from referencing.exceptions import Unresolvable

    try:
        validator = Draft202012Validator(spec.input_schema, registry=Registry())
        error = next(validator.iter_errors(params), None)
    except (SchemaError, Unresolvable):
        return {"path": "$", "validator": "schema"}
    return schema_violation(error) if error is not None else {}


def mcp_tool_definitions(
    visible_actions: Iterable[tuple[str, str]] | None = None,
) -> list[Tool]:
    """Use MCP SDK types; schema is glue around the existing capability catalog."""
    from mcp.types import Tool

    fields: dict[str, dict[str, str | list[str]]] = {
        "tool_id": {"type": "string"},
        "action": {"type": "string"},
    }
    visible = list(visible_actions) if visible_actions is not None else None
    if visible:
        # Keep the schema linear in catalog size. The bridge enforces valid pairs
        # and current permission on every call.
        fields = {
            "tool_id": {"type": "string", "enum": sorted({tool_id for tool_id, _ in visible})},
            "action": {"type": "string", "enum": sorted({action for _, action in visible})},
        }
    definitions = [
        (
            "capability_search",
            "检索当前账号获授权的企业工具，以及本轮桌面提供的可见页面和手动操作入口。query 留空可分页浏览。",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
                "offset": {"type": "integer", "minimum": 0},
            },
            [],
        ),
        (
            "capability_describe",
            "读取当前能力的精确参数和结果契约、风险及 schema_digest；执行动作必须使用此摘要。",
            fields,
            ["tool_id", "action"],
        ),
        (
            "execute_action",
            "提交企业动作到受控任务链。待审批或未知结果不是完成，不可更换调用标识重复提交。",
            {
                **fields,
                "call_id": {"type": "string"},
                "schema_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "params": {"type": "object"},
            },
            ["tool_id", "action", "call_id", "schema_digest", "params"],
        ),
        (
            "task_evidence",
            "读取本次运行已提交动作的真实任务状态和证据。",
            {"call_id": {"type": "string"}},
            ["call_id"],
        ),
        (
            "request_input",
            "仅当缺失信息确实阻断当前交付或业务操作缺关键参数时登记问题并等待；"
            "可在对话内完成的草案和修订应先直接交付，不得为对话内修订索要任务或目标内部 ID。"
            "提问不等于任务完成，也不构成审批或执行授权。",
            {"question": {"type": "string"}},
            ["question"],
        ),
    ]
    definitions_by_name = {
        name: (description, props, required) for name, description, props, required in definitions
    }
    tools = [
        Tool(
            name=name,
            description=description,
            input_schema={
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        )
        for name in XIAOX_TOOL_NAMES
        if name not in {"execute_employee", *DIRECT_ACTION_TOOLS}
        if visible != [] or name not in {"capability_describe", "execute_action"}
        for description, props, required in [definitions_by_name[name]]
    ]
    if visible is None or ("employee", "execute") in visible:
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        employee = get_tool_action_spec("employee", "execute")
        if employee is not None:
            action = next(tool for tool in tools if tool.name == "execute_action")
            action.input_schema["allOf"] = [
                {
                    "if": {
                        "required": ["tool_id", "action"],
                        "properties": {
                            "tool_id": {"const": "employee"},
                            "action": {"const": "execute"},
                        },
                    },
                    "then": {"properties": {"params": employee.input_schema}},
                }
            ]
            direct_schema = copy.deepcopy(employee.input_schema)
            direct_schema["properties"].update(
                {
                    "call_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "schema_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                }
            )
            direct_schema["required"] = [
                *direct_schema.get("required", []),
                "call_id",
                "schema_digest",
            ]
            tools.append(
                Tool(
                    name="execute_employee",
                    description=(
                        "直接执行已授权 AI 员工。参数使用 employee.execute 的原生对象契约；"
                        "先从 capability_describe 读取 schema_digest。写入仍走原审批与独立质检。"
                    ),
                    input_schema=direct_schema,
                )
            )
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    for name, (tool_id, action_name) in DIRECT_ACTION_TOOLS.items():
        if visible is not None and (tool_id, action_name) not in visible:
            continue
        spec = get_tool_action_spec(tool_id, action_name)
        if spec is None:
            continue
        generic = next(tool for tool in tools if tool.name == "execute_action")
        generic.input_schema.setdefault("allOf", []).append(
            {
                "if": {
                    "required": ["tool_id", "action"],
                    "properties": {"tool_id": {"const": tool_id}, "action": {"const": action_name}},
                },
                "then": {"properties": {"params": spec.input_schema}},
            }
        )
        direct_schema = copy.deepcopy(spec.input_schema)
        direct_schema["properties"].update(
            {
                "call_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "schema_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            }
        )
        direct_schema["required"] = [
            *direct_schema.get("required", []),
            "call_id",
            "schema_digest",
        ]
        tools.append(
            Tool(
                name=name,
                description=f"执行已授权的 {tool_id}.{action_name}；参数直接使用原能力契约，先读取 schema_digest。",
                input_schema=direct_schema,
            )
        )
    return tools
