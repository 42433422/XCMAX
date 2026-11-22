"""员工 Agent 的固定 Codex 入口；宿主保留工具作用域、授权和调用期限。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from app.application.tool_execution_deadline import (
    invocation_deadline,
    remaining_invocation_seconds,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.infrastructure.codex.policy import RuntimeSettings

# gate 签名：(tool_name, args) -> {"ok": bool, "reason": str}
GateFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def _runtime_entry_error(code: str, message: str) -> dict[str, Any]:
    return {
        "handler": "agent",
        "runtime": "codex",
        "ok": False,
        "error_code": code,
        "error": message,
        "output": "",
        "rounds": 0,
        "tool_calls": [],
        "trajectory": [],
        "exit_status": "unsupported",
        "retryable": False,
        "legacy_fallback_allowed": False,
    }


def _codex_employee_tool_scope(
    tools: list[dict[str, Any]],
    gate: GateFn | None,
) -> tuple[list[str], Callable[[str, str, dict[str, Any]], dict[str, Any]]]:
    """Project declared functions onto exact actions and retain the original gate.

    A name alone never grants all actions of a multi-action capability. Fixed
    aliases share their parameters with the canonical DB/workbook routers;
    unrecognised aliases and action domains are deliberately unsupported.
    """
    from jsonschema import Draft202012Validator, SchemaError
    from referencing import Registry
    from referencing.exceptions import Unresolvable

    from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

    canonical = build_tool_specs_v2()
    aliases = {
        "business_db_read": ("business_db", "read"),
        "business_db_write": ("business_db", "write"),
        "excel_schema_understand": ("excel_analysis", "structure"),
    }
    bindings: dict[tuple[str, str], tuple[str, Any, bool]] = {}
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
        if name in aliases:
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
            bindings[key] = (name, validator, has_action)

    def check(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        binding = bindings.get((tool_id, action))
        if binding is None or not isinstance(params, dict):
            return {"ok": False, "reason": "工具动作不在员工授权范围内"}
        name, validator, has_action = binding
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
        verdict = gate(name, arguments) if gate is not None else {"ok": True}
        if not isinstance(verdict, dict) or type(verdict.get("ok")) is not bool:
            return {"ok": False, "reason": "工具授权结果无效，未执行"}
        return verdict

    return sorted(f"{tool_id}.{action}" for tool_id, action in bindings), check


def _employee_runtime_context(
    employee_id: str,
    runtime_context: dict[str, Any] | None,
    workspace_root: str | None,
) -> dict[str, Any]:
    """Use only host context for identity and stable request correlation."""
    import hashlib

    context = dict(runtime_context or {})
    context.update(employee_id=employee_id, source="employee_runtime")
    if workspace_root is not None:
        context["workspace_root"] = workspace_root
    node = context.get("step_id") or context.get("node_id")
    if node and context.get("run_id"):
        # StepExecution supplies its current durable run, which is this nested
        # employee runtime's immediate parent. The gateway verifies ownership.
        context["parent_run_id"] = context["run_id"]
    if context.get("parent_run_id") and node:
        identity = [context["parent_run_id"], employee_id, node]
        context["turn_id"] = (
            "employee_"
            + hashlib.sha256(
                json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
        )
    elif not context.get("turn_id") and context.get("client_request_id"):
        context["turn_id"] = context["client_request_id"]
    return context


def default_employee_tools() -> list[dict[str, Any]]:
    """员工默认可用工具：工作流基础工具，剔除「员工包工具」本身以避免递归调用。"""
    try:
        from app.application.tools.workflow import get_workflow_tool_registry
        from app.mod_sdk.employee_tool_registry import is_employee_tool

        reg = get_workflow_tool_registry() or []
        out: list[dict[str, Any]] = []
        for spec in reg:
            name = ""
            if isinstance(spec, dict):
                name = str((spec.get("function") or {}).get("name") or "")
            if name and is_employee_tool(name):
                continue
            out.append(spec)
        return out
    except RECOVERABLE_ERRORS:
        logger.debug("default_employee_tools fallback to empty", exc_info=True)
        return []


def run_employee_agent_loop(
    *,
    employee_id: str,
    system_prompt: str,
    task: str,
    input_data: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
    workspace_root: str | None = None,
    wall_time_limit_sec: float = 300.0,
    gate: GateFn | None = None,
    history: list[dict[str, Any]] | None = None,
    runtime_context: dict[str, Any] | None = None,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    settings: RuntimeSettings | None = None,
) -> dict[str, Any]:
    """Delegate the sole model/tool loop to Codex without a native fallback."""
    from app.application.agent_runtime.gateway import run_runtime_task
    from app.infrastructure.codex import policy

    deadline = time.monotonic() + remaining_invocation_seconds(max(0.001, wall_time_limit_sec))
    try:
        selected = settings if settings is not None else policy.runtime_settings()
        if selected.engine != "codex" or "employee" not in selected.surfaces:
            raise policy.RuntimePolicyError("员工 Agent 必须启用固定 Codex 执行器")
    except policy.RuntimePolicyError:
        return _runtime_entry_error("runtime_configuration_invalid", "员工运行时配置无效")
    if gate is None:
        return _runtime_entry_error("gate_required", "员工工作空间和风险授权门尚未恢复，未执行")
    try:
        allowed_actions, runtime_gate = _codex_employee_tool_scope(
            tools if tools is not None else default_employee_tools(),
            gate,
        )
    except ValueError as exc:
        return _runtime_entry_error("employee_runtime_tools_unsupported", str(exc))
    with invocation_deadline(deadline):
        return run_runtime_task(
            task=task,
            system_prompt=system_prompt,
            runtime_context=_employee_runtime_context(employee_id, runtime_context, workspace_root),
            history=history,
            input_data=input_data,
            completion_mode="auto",
            admit_goal=True,
            allowed_actions=allowed_actions,
            gate=runtime_gate,
            on_event=on_event,
            settings=selected,
        )


__all__ = ["GateFn", "default_employee_tools", "run_employee_agent_loop"]
