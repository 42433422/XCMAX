"""Read-only projections of the execution contract and live account authority.

ToolActionSpecV2 owns the contract. This module never registers another tool,
executes a capability, or treats installation as an account permission.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2
from app.application.workflow.tool_profile import RETIRED_PLANNER_TOOLS
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _project_registry() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for (tool_id, action), spec in sorted(build_tool_specs_v2().items()):
        if tool_id in RETIRED_PLANNER_TOOLS or spec.availability == "aiopen":
            continue
        tool = result.setdefault(
            tool_id,
            {"description": spec.description, "availability": "shared", "actions": {}},
        )
        tool["actions"][action] = deepcopy(spec.to_dict())
    return result


def _approval_required_actions(registry: dict[str, Any]) -> set[tuple[str, str]]:
    from app.application.tools.registered_capabilities import capability_approval_node_ids
    from app.application.workflow.workflow_types import (
        PlanGraph,
        WorkflowNode,
        normalize_workflow_risk,
    )

    nodes = [
        WorkflowNode(
            node_id=f"{tool_id}.{action}",
            tool_id=tool_id,
            action=action,
            risk=normalize_workflow_risk(spec["risk"]),
            idempotent=spec["idempotent"],
        )
        for tool_id, tool in registry.items()
        for action, spec in tool["actions"].items()
    ]
    approvals = set(
        capability_approval_node_ids(
            PlanGraph(
                plan_id="capability_discovery",
                intent="Read current capability admission policy",
                nodes=nodes,
            )
        )
    )
    return {(node.tool_id, node.action) for node in nodes if node.node_id in approvals}


def _authorized_registry(registry: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.workflow.planning_graph_policy import filter_registry_for_profile
    from app.application.workflow.tool_profile import resolve_tool_execution_profile
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    _bound_actor(context)
    trusted = {key: value for key, value in context.items() if key != "_tool_approval_scope"}
    visible: dict[str, Any] = {}
    for tool_id, tool in filter_registry_for_profile(
        registry, resolve_tool_execution_profile(context)
    ).items():
        actions: dict[str, Any] = {}
        for action, metadata in tool["actions"].items():
            if tool_id == "kellai":
                from app.application.tools.kellai import connection_scope

                if connection_scope(trusted, action).get("available") is not True:
                    continue
            owner_mod = metadata.get("owner_mod_id")
            if owner_mod and owner_mod != (context.get("_mod_authorization") or {}).get("mod_id"):
                continue
            params: dict[str, Any] = {}
            projected = deepcopy(metadata)
            if (tool_id, action) == ("business_db", "read"):
                entity_schema = projected["input_schema"].get("properties", {}).get("entity", {})
                entities = [
                    str(entity)
                    for entity in entity_schema.get("enum", [])
                    if actor_tool_denial(tool_id, action, trusted, {"entity": entity}) is None
                ]
                if not entities:
                    continue
                entity_schema["enum"] = entities
                params["entity"] = entities[0]
            if actor_tool_denial(tool_id, action, trusted, params) is None:
                actions[action] = projected
        if actions:
            visible[tool_id] = {**tool, "actions": actions}
    if not trusted.get("tenant_id"):
        approvals = _approval_required_actions(visible)
        for tool_id in list(visible):
            visible[tool_id]["actions"] = {
                action: spec
                for action, spec in visible[tool_id]["actions"].items()
                if (tool_id, action) not in approvals
            }
            if not visible[tool_id]["actions"]:
                del visible[tool_id]
    return visible


def workflow_registry(runtime_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Internal metadata without context; live authorized projection with context."""
    registry = _project_registry()
    if runtime_context is None:
        return registry
    try:
        return _authorized_registry(registry, dict(runtime_context))
    except RECOVERABLE_ERRORS:
        return {}


def available_employees(context: dict[str, Any]) -> list[dict[str, Any]]:
    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.employee_runtime.loader import (
        candidate_pack_ids,
        pack_has_direct_python_runtime,
        resolve_pack_dir,
        verify_direct_python_pack_trust,
    )
    from app.application.employee_runtime.tool_scope import host_employee_denial
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.mod_sdk.employee_directory import build_employee_directory

    _bound_actor(context)
    employee_actions = (workflow_registry(context).get("employee") or {}).get("actions") or {}
    if not {"list", "execute"}.issubset(employee_actions):
        return []
    if any(actor_tool_denial("employee", action, context) for action in ("list", "execute")):
        return []
    return [
        {"employee_id": row["pack_id"], **row}
        for row in build_employee_directory(include_management=True)
        if row.get("runtime_ok") is True
        and row.get("enabled") is not False
        and (pack_dir := resolve_pack_dir(str(row["pack_id"]))) is not None
        and pack_has_direct_python_runtime(pack_dir)
        and verify_direct_python_pack_trust(pack_dir)[0]
        and host_employee_denial(candidate_pack_ids(str(row["pack_id"])), {}, context) is None
    ]


def capability_entries(runtime_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """AIOPEN and planner views retain the same capability identity and schemas."""
    entries: list[dict[str, Any]] = []
    registry = workflow_registry(runtime_context)
    approvals = _approval_required_actions(registry)
    for tool_id, tool in registry.items():
        for action, spec in tool["actions"].items():
            identity = f"{tool_id}.{action}"
            entries.append(
                {
                    **spec,
                    "kind": "capability",
                    "capability_id": identity,
                    "operation_id": f"capability.{identity}",
                    "scope": f"capability.{identity}",
                    "method": "CAPABILITY",
                    "path": "",
                    "domain": tool_id,
                    "toolset": tool_id,
                    "summary": spec["description"],
                    "executable": True,
                    "approval_required": (tool_id, action) in approvals,
                }
            )
    return entries


def discover_capabilities(
    context: dict[str, Any], *, query: str = "", limit: int = 200
) -> dict[str, Any]:
    """Discover current account grants; revocation and tenant changes are rechecked."""
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    try:
        _bound_actor(context)
        entries = capability_entries(context)
        employees = available_employees(context)
        term = str(query or "").strip().casefold()
        if term:
            entries = [
                entry
                for entry in entries
                if term in (entry["capability_id"] + " " + entry["description"]).casefold()
            ]
            employees = [
                row
                for row in employees
                if term
                in (
                    str(row["employee_id"])
                    + " "
                    + str(row.get("label", ""))
                    + " "
                    + str(row.get("description", ""))
                ).casefold()
            ]
        size = min(500, max(1, int(limit)))
        return {
            "success": True,
            "authority": "ToolActionSpecV2",
            "version": "2",
            "capability_count": len(entries),
            "capabilities": entries[:size],
            "truncated": len(entries) > size,
            "employees": employees[:size],
        }
    except RECOVERABLE_ERRORS:
        return {
            "success": False,
            "error_code": "capability_discovery_denied",
            "message": "无法读取当前账号可用能力，请重新登录或检查授权。",
            "capabilities": [],
            "employees": [],
        }
