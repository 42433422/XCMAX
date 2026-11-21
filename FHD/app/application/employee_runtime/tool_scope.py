"""员工能力声明只收窄当前账号的权威能力目录，不注册独立工具契约。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from app.application.employee_runtime.write_approval import invoke_employee_gate

# Gates may additionally accept the trusted per-call runtime_context keyword.
GateFn = Callable[..., dict[str, Any]]

logger = logging.getLogger(__name__)

READ_TOOLS = ("excel_analysis", "excel_toolkit", "excel_analyzer")
DOC_TOOLS = ("generate_office_document",)


def __getattr__(name: str):
    if name == "WRITE_TOOLS":
        from resources.config.risk_actions_loader import list_write_tools

        return list_write_tools()
    if name == "CODE_WRITE_TOOLS":
        from resources.config.risk_actions_loader import list_code_write_tools

        return list_code_write_tools()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_EXCEL_KW = (
    "excel",
    "表格",
    "spreadsheet",
    "数据",
    "data",
    "sheet",
    "csv",
    "汇总",
    "统计",
    "analy",
    "分析",
    "报表",
)
_CHART_KW = ("chart", "图表", "可视", "viz", "plot", "看板", "dashboard")
_DOC_KW = (
    "文档",
    "报告",
    "报表",
    "document",
    "word",
    "报价",
    "单据",
    "receipt",
    "deliver",
    "交付",
    "generate",
    "合同",
    "contract",
    "letter",
    "函",
    "ppt",
    "幻灯",
    "pdf",
)
_IMPORT_KW = ("导入", "入库", "import", "批量", "bulk", "录入", "ingest", "写库")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _explicit_allowlist(config: dict[str, Any], manifest: dict[str, Any]) -> list[str] | None:
    actions = _as_dict(config.get("actions"))
    agent = _as_dict(actions.get("agent"))
    v2 = _as_dict(manifest.get("employee_config_v2"))
    for candidate in (
        config.get("tools"),
        actions.get("tools"),
        agent.get("tools"),
        v2.get("tools"),
        manifest.get("tools"),
    ):
        if isinstance(candidate, list):
            return [x.strip() for x in candidate if isinstance(x, str) and x.strip()]
    return None


def _capability_text(manifest: dict[str, Any], config: dict[str, Any]) -> str:
    parts: list[str] = []
    emp = _as_dict(manifest.get("employee"))
    for cap in emp.get("capabilities") or []:
        if isinstance(cap, dict):
            parts.append(str(cap.get("label") or ""))
            parts.append(str(cap.get("description") or ""))
        else:
            parts.append(str(cap))
    cog = _as_dict(config.get("cognition"))
    agent = _as_dict(cog.get("agent"))
    role = _as_dict(agent.get("role"))
    for exp in role.get("expertise") or []:
        parts.append(str(exp))
    for skill in cog.get("skills") or []:
        if isinstance(skill, dict):
            parts.append(str(skill.get("name") or ""))
            parts.append(str(skill.get("brief") or ""))
        else:
            parts.append(str(skill))
    identity = _as_dict(config.get("identity"))
    for key in ("domain", "area", "description", "name"):
        if not isinstance(identity, dict):
            identity = {}
        parts.append(str(identity.get(key) or ""))
    parts.append(str(manifest.get("description") or ""))
    return " ".join(p for p in parts if p).lower()


def is_read_only(manifest: dict[str, Any], config: dict[str, Any]) -> bool:
    actions = _as_dict(config.get("actions"))
    agent = _as_dict(actions.get("agent"))
    ws = _as_dict(agent.get("workspace"))
    if bool(ws.get("read_only")) or bool(_as_dict(config.get("workspace_policy")).get("read_only")):
        return True
    v2 = _as_dict(manifest.get("employee_config_v2"))
    wp = _as_dict(v2.get("workspace_policy"))
    return bool(wp.get("read_only"))


def resolve_employee_tools(
    employee_id: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from app.application.tools.workflow import get_workflow_tool_registry

    allow = _explicit_allowlist(config, manifest)
    if allow is None:
        text = _capability_text(manifest, config)
        allow = []
        if any(word in text for word in (*_EXCEL_KW, *_CHART_KW)):
            allow.extend(READ_TOOLS)
        if any(word in text for word in _DOC_KW):
            allow.extend(DOC_TOOLS)
        if any(word in text for word in _IMPORT_KW):
            allow.extend(("elt_import", "excel_import"))
        if not allow:
            allow = [*READ_TOOLS, *DOC_TOOLS]
    return get_workflow_tool_registry(
        runtime_context,
        allowed_tools=allow,
        read_only=is_read_only(manifest, config),
        exclude_tools={"employee"},
    )


def employee_tool_names(
    employee_id: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    runtime_context: dict[str, Any] | None = None,
) -> list[str]:
    """返回实际已投影的能力动作，而不是统一传输工具名。"""
    return [
        f"{branch['properties']['tool_id']['enum'][0]}.{branch['properties']['action']['enum'][0]}"
        for spec in resolve_employee_tools(employee_id, manifest, config, runtime_context)
        for branch in spec["function"]["parameters"]["anyOf"]
    ]


__all__ = ["employee_tool_names", "is_read_only", "resolve_employee_tools"]


def host_employee_denial(
    employee_ids: list[str], payload: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any] | None:
    """Customer execution grants do not grant host-side management tools."""
    if "_actor_authorization" not in context:
        return None
    from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
    from app.mod_sdk.employee_specialized_tools_employee_map import EMPLOYEE_TOOLS

    try:
        actor = _bound_actor(context)
        if actor.role == "admin" and actor.tier == "admin" and actor.tenant_id is None:
            return None
    except AgentModAuthorizationError:
        return {
            "success": False,
            "error_code": "tool_identity_required",
            "error": "员工身份授权无效",
        }
    if str(payload.get("handler") or "").strip() == "specialized" or any(
        EMPLOYEE_TOOLS.get(name) for name in employee_ids
    ):
        return {
            "success": False,
            "error_code": "employee_host_admin_required",
            "error": "宿主管理员工和专用工具需要平台管理员权限",
        }
    return None


def _codex_employee_tool_scope(
    tools: list[dict[str, Any]],
    gate: GateFn | None,
) -> tuple[list[str], Callable[..., dict[str, Any]]]:
    """Project declared functions onto exact actions and retain the original gate.

    A name alone never grants all actions of a multi-action capability. These
    two aliases share their existing parameters with the canonical DB router;
    unrecognised aliases and action domains are deliberately unsupported.
    """
    from jsonschema import Draft202012Validator, SchemaError
    from referencing import Registry
    from referencing.exceptions import Unresolvable

    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2
    from app.application.tools.registered_capabilities import ERP_CAPABILITY_TOOL_NAME

    canonical = build_tool_specs_v2()
    aliases = {
        "business_db_read": ("business_db", "read"),
        "business_db_write": ("business_db", "write"),
    }
    bindings: dict[tuple[str, str], tuple[str, Any, bool, bool]] = {}
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            raise ValueError("员工工具缺少 function 契约")
        name = function.get("name")
        schema = function.get("parameters")
        if not isinstance(name, str) or not name or not isinstance(schema, dict):
            raise ValueError("员工工具缺少明确的名称或参数契约")
        schema = deepcopy(schema)
        properties = schema.get("properties", {})
        if schema.get("type", "object") != "object" or not isinstance(properties, dict):
            raise ValueError(f"员工工具 {name} 的参数契约无法映射")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError(f"员工工具 {name} 的参数契约无效") from exc
        validator = Draft202012Validator(schema, registry=Registry())
        has_action = "action" in properties
        is_capability = name == ERP_CAPABILITY_TOOL_NAME
        if is_capability:
            branches = schema.get("anyOf")
            if not isinstance(branches, list) or not branches:
                raise ValueError("员工 ERP 能力必须声明完整且有限的动作契约")
            keys = []
            for branch in branches:
                fields = branch.get("properties") if isinstance(branch, dict) else None
                if not isinstance(fields, dict):
                    raise ValueError("员工 ERP 能力分支缺少明确的参数契约")
                pair = []
                for field in ("tool_id", "action"):
                    domain = fields.get(field)
                    choices = domain.get("enum") if isinstance(domain, dict) else None
                    if (
                        not isinstance(choices, list)
                        or len(choices) != 1
                        or not isinstance(choices[0], str)
                        or not choices[0]
                    ):
                        raise ValueError("员工 ERP 能力分支必须绑定唯一工具和动作")
                    pair.append(choices[0])
                keys.append((pair[0], pair[1]))
        elif name in aliases:
            if has_action:
                raise ValueError(f"员工工具 {name} 的固定动作不能被参数覆盖")
            keys = [aliases[name]]
        else:
            candidates = {
                (spec.tool_id, spec.action) for spec in canonical.values() if spec.tool_id == name
            }
            if has_action:
                action_schema = properties["action"]
                if not isinstance(action_schema, dict):
                    raise ValueError(f"员工工具 {name} 的动作契约无效")
                actions = (
                    [action_schema["const"]]
                    if "const" in action_schema
                    else action_schema.get("enum")
                )
                if (
                    not isinstance(actions, list)
                    or not actions
                    or any(not isinstance(action, str) or not action for action in actions)
                ):
                    raise ValueError(f"员工工具 {name} 必须声明有限且明确的动作")
                keys = [(name, action) for action in actions]
                if not set(keys).issubset(candidates):
                    raise ValueError(f"员工工具 {name} 含未登记的动作")
            elif len(candidates) == 1:
                keys = list(candidates)
            else:
                raise ValueError(f"员工工具 {name} 无法映射到唯一的登记动作")
        for key in keys:
            if key not in canonical or key in bindings:
                raise ValueError(f"员工工具 {name} 的动作映射缺失或不唯一")
            bindings[key] = (name, validator, has_action, is_capability)

    def check(
        tool_id: str,
        action: str,
        params: dict[str, Any],
        *,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        binding = bindings.get((tool_id, action))
        if binding is None or not isinstance(params, dict):
            return {"ok": False, "reason": "工具动作不在员工授权范围内"}
        name, validator, has_action, is_capability = binding
        if is_capability:
            arguments = {"tool_id": tool_id, "action": action, "params": deepcopy(params)}
        else:
            arguments = deepcopy(params)
            if "action" in arguments and (not has_action or arguments["action"] != action):
                return {"ok": False, "reason": "工具参数与已授权动作不一致"}
            if has_action:
                arguments["action"] = action
        try:
            if next(validator.iter_errors(arguments), None) is not None:
                return {"ok": False, "reason": "工具参数不符合员工契约"}
        except Unresolvable:
            return {"ok": False, "reason": "员工工具契约的引用无法解析"}
        verdict = (
            invoke_employee_gate(gate, name, arguments, runtime_context=dict(runtime_context or {}))
            if gate is not None
            else {"ok": True}
        )
        if not isinstance(verdict, dict) or type(verdict.get("ok")) is not bool:
            return {"ok": False, "reason": "工具授权结果无效，未执行"}
        return verdict

    return sorted(f"{tool_id}.{action}" for tool_id, action in bindings), check
