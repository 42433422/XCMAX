"""Config-driven ERP capability tool for model-facing agents.

The product's workflow registry is the source of truth for user-facing ERP
capabilities and their risk policies.  This module exposes that registry to an
LLM through one typed function call, while keeping execution on the existing
approval-gated workflow path.  It deliberately does *not* expose raw internal
HTTP endpoints, authentication, or configuration internals as model tools.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.application.workflow.types import normalize_workflow_risk
from app.utils.operational_errors import RECOVERABLE_ERRORS

ERP_CAPABILITY_TOOL_NAME = "execute_erp_capability"
ERP_DISCOVERY_TOOL_NAME = "discover_erp_capabilities"


def discover_registered_capabilities(args: dict[str, Any] | None = None) -> str:
    """Inspect contracts without executing business operations or returning secrets."""
    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

    payload = dict(args or {})
    query = str(payload.get("query") or "").strip().casefold()
    tool_id = str(payload.get("tool_id") or "").strip()
    registry = _workflow_registry()
    specs = build_tool_specs_v2()
    rows = []
    for registered_id, tool in sorted(registry.items()):
        if tool_id and registered_id != tool_id:
            continue
        for action, meta in sorted(tool.get("actions", {}).items()):
            description = str(tool.get("description") or "")
            if query and query not in f"{registered_id} {action} {description}".casefold():
                continue
            spec = specs.get((registered_id, action))
            rows.append(
                {
                    "tool_id": registered_id,
                    "action": action,
                    "description": description,
                    "risk": meta.get("risk", "medium"),
                    "idempotent": bool(meta.get("idempotent", False)),
                    "input_schema": spec.input_schema if spec else {},
                    "output_schema": spec.output_schema if spec else {},
                    "permission": spec.permission if spec else "",
                    "availability": spec.availability if spec else "unknown",
                }
            )
    return json.dumps(
        {"success": True, "action_count": len(rows), "actions": rows}, ensure_ascii=False
    )


def build_capability_discovery_definition() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": ERP_DISCOVERY_TOOL_NAME,
            "description": "检索软件能力及完整参数、返回值、权限协议。执行能力前先查询其 tool_id；缺少业务参数时询问用户，不得编造 ID、文件路径或业务数据。空参数列出全部已登记动作，登记不代表已通过业务验收。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "能力名称、动作或描述的子串。"},
                    "tool_id": {
                        "type": "string",
                        "description": "精确能力 ID；返回其全部动作协议。",
                    },
                },
                "additionalProperties": False,
            },
        },
    }


def _workflow_registry() -> dict[str, Any]:
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    registry = get_workflow_tools_from_registry()
    return registry if isinstance(registry, dict) else {}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _capability_catalog_lines(registry: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for tool_id in sorted(registry):
        tool = registry.get(tool_id)
        tool_data: dict[str, Any] = tool if isinstance(tool, dict) else {}
        actions = tool_data.get("actions")
        if not isinstance(actions, dict):
            continue
        action_bits = []
        for action, spec in sorted(actions.items()):
            risk = str((spec or {}).get("risk") or "low").lower()
            action_bits.append(f"{action}({risk})")
        description = str(tool_data.get("description") or "").strip()
        suffix = f" — {description}" if description else ""
        lines.append(f"{tool_id}: {', '.join(action_bits)}{suffix}")
    return lines


def registered_capability_catalog() -> dict[str, Any]:
    """Return a compact, model-safe view of every registered product capability."""

    registry = _workflow_registry()
    capabilities: list[dict[str, Any]] = []
    for tool_id in sorted(registry):
        tool = registry.get(tool_id)
        tool_data: dict[str, Any] = tool if isinstance(tool, dict) else {}
        actions = tool_data.get("actions")
        if not isinstance(actions, dict):
            continue
        capabilities.append(
            {
                "tool_id": tool_id,
                "description": str(tool_data.get("description") or ""),
                "actions": {
                    str(action): {
                        "risk": str((spec or {}).get("risk") or "low").lower(),
                        "required_params": list((spec or {}).get("required_params") or []),
                        "idempotent": bool((spec or {}).get("idempotent", False)),
                    }
                    for action, spec in sorted(actions.items())
                    if isinstance(spec, dict)
                },
            }
        )
    return {
        "capability_count": len(capabilities),
        "capability_ids": [row["tool_id"] for row in capabilities],
        "capabilities": capabilities,
    }


def build_registered_capability_tool_definition() -> dict[str, Any]:
    """Build the single model tool which covers all registered ERP functions."""

    registry = _workflow_registry()
    catalog = _capability_catalog_lines(registry)
    catalog_text = "\n".join(catalog)
    return {
        "type": "function",
        "function": {
            "name": ERP_CAPABILITY_TOOL_NAME,
            "description": (
                "执行已登记的 ERP 产品能力。只能使用下方 capability catalog 中的 "
                "tool_id 与 action；params 必须只包含该动作需要的业务参数。低风险动作会执行，"
                "中高风险动作会沿用产品审批流；不得把内部 HTTP、账号鉴权、权限管理或系统密钥 "
                "当作 capability 调用。调用前要确认用户意图，执行后依据返回的 success 与 approval "
                "结果如实回复。\n\nCapability catalog:\n"
                f"{catalog_text}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "enum": sorted(registry),
                        "description": "ERP 产品能力 ID。",
                    },
                    "action": {
                        "type": "string",
                        "description": "所选 tool_id 支持的动作；精确名称见 capability catalog。",
                    },
                    "params": {
                        "type": "object",
                        "description": "该动作的业务参数。不会接受 _runtime_context 或鉴权注入字段。",
                        "additionalProperties": True,
                    },
                    "scheduled_at": {
                        "type": "string",
                        "description": "用户要求定时执行时提供带时区 ISO 8601 时间；仅创建一次性任务，须在任务中心审批，不会立即执行。时间或时区不明确时先询问。",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "定时任务必填的稳定请求标识，重复调用必须保持相同 ID；不能含 /。",
                    },
                    "recurrence": {
                        "type": "object",
                        "description": "周期执行：interval 使用 seconds（至少 60）；daily 使用 hour、minute 和 IANA timezone。必须同时提供首次 scheduled_at 与稳定 task_id。每次生成任务仍须审批。",
                        "properties": {
                            "kind": {"type": "string", "enum": ["interval", "daily"]},
                            "seconds": {"type": "integer", "minimum": 60},
                            "hour": {"type": "integer", "minimum": 0, "maximum": 23},
                            "minute": {"type": "integer", "minimum": 0, "maximum": 59},
                            "timezone": {"type": "string"},
                        },
                        "required": ["kind"],
                    },
                },
                "required": ["tool_id", "action"],
            },
        },
    }


def extend_workflow_tool_registry(registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append the product capability tool without making a second hard-coded catalog."""

    try:
        from app.application.tools.scheduled_capability import schedule_management_definition

        return [
            *registry,
            schedule_management_definition(),
            build_capability_discovery_definition(),
            build_registered_capability_tool_definition(),
        ]
    except RECOVERABLE_ERRORS:
        return registry


def resolve_registered_capability_call(args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize one model tool call against the SSOT registry."""

    payload = dict(args or {})
    tool_id = str(payload.get("tool_id") or payload.get("capability_id") or "").strip()
    params = payload.get("params", {})
    if not isinstance(params, dict):
        return {"success": False, "error": "params 必须是 JSON 对象"}
    params = dict(params)
    # Runtime context and authorization are injected only by the host workflow,
    # never accepted from a model-generated tool argument.
    params.pop("_runtime_context", None)
    registry = _workflow_registry()
    tool = registry.get(tool_id)
    if not isinstance(tool, dict):
        return {
            "success": False,
            "error": f"未登记的 ERP capability: {tool_id or '(empty)'}",
            "available_tool_ids": sorted(registry),
        }

    from app.services.tools_execution.registry import _normalize_action

    action = _normalize_action(str(payload.get("action") or ""), params)
    actions = tool.get("actions")
    spec = actions.get(action) if isinstance(actions, dict) else None
    if not isinstance(spec, dict):
        return {
            "success": False,
            "error": f"未登记的 capability action: {tool_id}.{action or '(empty)'}",
            "available_actions": sorted(actions) if isinstance(actions, dict) else [],
        }
    required = [str(key) for key in spec.get("required_params") or [] if str(key)]
    # Clearing a text field or a multiple-select is an intentional empty value.
    empty_screen_fields = {"type": "text", "select": "values"}
    missing = [
        key
        for key in required
        if not _has_value(params.get(key))
        and not (
            tool_id == "software"
            and empty_screen_fields.get(action) == key
            and (params.get(key) == "" or params.get(key) == [])
        )
    ]
    if missing:
        return {
            "success": False,
            "error": f"缺少参数：{', '.join(missing)}",
            "tool_id": tool_id,
            "action": action,
            "required_params": required,
        }
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    validation = validate_tool_call(tool_id, action, params)
    if not validation.ok:
        return {
            "success": False,
            "error": validation.message,
            "error_code": validation.error_code,
            "tool_id": tool_id,
            "action": action,
        }
    return {
        "success": True,
        "tool_id": tool_id,
        "action": action,
        "params": params,
        "risk": str(spec.get("risk") or "low").lower(),
        "idempotent": bool(spec.get("idempotent", False)),
        "required_params": required,
        "description": str(tool.get("description") or ""),
    }


def _dispatch_registered_tool(
    *, tool_id: str, action: str, params: dict[str, Any]
) -> dict[str, Any]:
    from app.application.facades.tools_facade import execute_registered_workflow_tool

    return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)


def execute_registered_capability(
    args: dict[str, Any] | None,
    *,
    workspace_root: str | None = None,
) -> str:
    """Execute a registered product operation through risk and approval gates."""

    resolved = resolve_registered_capability_call(args)
    if not resolved.get("success"):
        return json.dumps(resolved, ensure_ascii=False)

    if args is not None and ("scheduled_at" in args or "recurrence" in args):
        from fastapi import HTTPException

        from app.application.tools.scheduled_capability import create_scheduled_capability

        try:
            scheduled = create_scheduled_capability(args, resolved)
        except HTTPException:
            scheduled = {"success": False, "message": "创建定时任务需要有效登录会话"}
        except RECOVERABLE_ERRORS:
            scheduled = {
                "success": False,
                "message": "定时任务创建失败，请检查登录状态、任务 ID 和执行时间",
            }
        return json.dumps(scheduled, ensure_ascii=False)

    from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
    from app.application.workflow.engine import WorkflowEngine
    from app.application.workflow.types import PlanGraph, WorkflowNode

    tool_id = str(resolved["tool_id"])
    action = str(resolved["action"])
    params = dict(resolved["params"])
    plan_id = f"erp-capability-{tool_id}-{action}-{uuid.uuid4().hex[:12]}"
    plan = PlanGraph(
        plan_id=plan_id,
        intent=f"ERP Agent 请求执行 {tool_id}.{action}",
        todo_steps=[f"执行已登记产品能力 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id="registered_capability",
                tool_id=tool_id,
                action=action,
                params=params,
                risk=normalize_workflow_risk(str(resolved["risk"])),
                idempotent=bool(resolved["idempotent"]),
                description=str(resolved["description"]),
            )
        ],
        risk_level=normalize_workflow_risk(str(resolved["risk"])),
        metadata={"source": "erp_agent_capability_tool"},
    )
    runtime_context = {
        "source": "erp_agent_capability_tool",
        "workspace_root": workspace_root,
        "message": str(params.get("user_request") or params.get("message") or ""),
    }
    from app.application.aiopen.software_control import request_screen_owner
    from app.infrastructure.request_context import get_current_request

    owner = request_screen_owner(get_current_request())
    if owner:
        runtime_context.update(
            user_id=owner["owner_id"],
            local_user_id=owner["owner_id"],
            actor_id=owner["owner_id"],
            tenant_id=owner["tenant_id"],
        )
    try:
        decision, run_result = ApprovalGatedEngine(
            WorkflowEngine(tool_dispatcher=_dispatch_registered_tool)
        ).run(plan, runtime_context=runtime_context, strategy="interactive")
    except RECOVERABLE_ERRORS:
        return json.dumps(
            {
                "success": False,
                "error": "ERP capability 风险门检查失败，未执行",
                "tool_id": tool_id,
                "action": action,
            },
            ensure_ascii=False,
        )

    capability = {
        key: resolved[key] for key in ("tool_id", "action", "risk", "idempotent", "required_params")
    }
    approval = decision.to_dict()
    if decision.pending_approval:
        return json.dumps(
            {
                "success": False,
                "pending_approval": True,
                "message": "该 ERP 操作已创建审批请求，审批前不会执行。",
                "capability": capability,
                "approval": approval,
            },
            ensure_ascii=False,
        )
    if decision.any_rejected or run_result is None:
        return json.dumps(
            {
                "success": False,
                "message": "该 ERP 操作未获风险门批准，未执行。",
                "capability": capability,
                "approval": approval,
            },
            ensure_ascii=False,
        )

    node_result = run_result.node_results[0] if run_result.node_results else None
    output = dict(getattr(node_result, "output", {}) or {})
    return json.dumps(
        {
            "success": bool(run_result.success and output.get("success")),
            "message": str(output.get("message") or run_result.message or ""),
            "capability": capability,
            "approval": approval,
            "result": output,
        },
        ensure_ascii=False,
    )


__all__ = [
    "ERP_CAPABILITY_TOOL_NAME",
    "build_registered_capability_tool_definition",
    "execute_registered_capability",
    "extend_workflow_tool_registry",
    "registered_capability_catalog",
    "resolve_registered_capability_call",
]
