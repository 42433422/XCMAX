"""Registered handoff_commit. It starts the existing employee handoff run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

_REQUIRED = ("tenant_id", "user_id", "task_id", "source", "target", "permissions")


def commit_registered_handoff(args: dict[str, Any] | None, workspace: str | None) -> dict[str, Any]:
    """Create a child run through start_employee_handoff and return its real result."""
    body = dict(args or {})
    missing = _missing_context(body)
    if missing:
        return _rejected("handoff_context_missing", f"交接缺少上下文: {missing}")
    tenant_id = str(body["tenant_id"]).strip()
    user_id = str(body["user_id"]).strip()
    task_id = str(body["task_id"]).strip()
    source = str(body["source"]).strip()
    target = str(body["target"]).strip()
    permissions = body["permissions"]
    if not isinstance(permissions, list) or not permissions:
        return _rejected("handoff_context_missing", "交接缺少可委托的工具范围")
    target_tenant = str(body.get("target_tenant_id") or "").strip()
    if target_tenant and target_tenant != tenant_id:
        return _rejected("handoff_cross_tenant", "不能把任务交给其他企业的员工")
    unknown = _unknown_target(workspace, target)
    if unknown:
        return _rejected("handoff_unknown_employee", unknown)
    grant = body.get("parent_grant")
    if not isinstance(grant, list) or not grant:
        return _rejected("handoff_unauthorized", "缺少父员工可委托的工具范围")
    delegated, denial = _delegated_tools(
        permissions,
        [str(item) for item in grant],
        tenant_id=tenant_id,
        user_id=user_id,
        task_id=task_id,
        employee_id=target,
    )
    if denial is not None:
        return denial
    chosen = _auto_tool(delegated)
    if chosen is None:
        return _rejected("handoff_no_auto_tool", "委托范围内没有可自动执行的低风险工具")
    tool_id, action = chosen
    repository = InMemoryAgentRunRepository()
    parent = AgentRun(user_id=user_id, message=str(body.get("goal") or "员工交接"))
    parent.metadata["runtime_context"] = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "task_id": task_id,
        "employee_id": source,
    }
    parent.metadata["task_context"] = {"task_id": task_id}
    repository.save(parent)
    child = AgentOrchestrator(repository=repository).start_employee_handoff(
        parent,
        employee_id=target,
        allowlist=list(delegated),
        message=str(body.get("goal") or "员工交接"),
        plan=_plan(tool_id, action, body),
    )
    return _child_receipt(
        parent,
        child,
        task_id=task_id,
        tenant_id=tenant_id,
        user_id=user_id,
        target=target,
        delegated=delegated,
    )


def _missing_context(body: dict[str, Any]) -> str:
    for key in _REQUIRED:
        value = body.get(key)
        if key == "permissions":
            continue
        if not str(value or "").strip():
            return key
    return ""


def _rejected(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "ok": False, "error_code": code, "error_message": message}


def _unknown_target(workspace: str | None, target: str) -> str:
    if not target or target in {".", ".."} or "/" in target or "\\" in target:
        return "目标员工不存在"
    root = Path(workspace) if workspace else None
    folder = None if root is None else root / "employees"
    cards = sorted(folder.glob("*.json")) if folder is not None and folder.is_dir() else []
    if not cards:
        return ""
    path = folder / f"{target}.json" if folder is not None else None
    if path is None or not path.is_file():
        return "目标员工不在当前花名册"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "目标员工档案不可读"
    if isinstance(loaded, dict) and loaded.get("available") is False:
        return "目标员工不能接收任务"
    return ""


def _split_tool(token: str) -> tuple[str, str] | None:
    tool_id, separator, action = str(token).strip().partition(".")
    if not separator or not tool_id or not action or "." in action:
        return None
    return tool_id, action


def _delegated_tools(
    permissions: list[Any],
    grant: list[str],
    *,
    tenant_id: str,
    user_id: str,
    task_id: str,
    employee_id: str,
) -> tuple[list[str], dict[str, Any] | None]:
    grant_set = set(grant)
    wildcard = "*" in grant_set
    delegated: list[str] = []
    for raw in permissions:
        token = str(raw or "").strip()
        parsed = _split_tool(token)
        if parsed is None or (not wildcard and token not in grant_set and parsed[0] not in grant_set):
            return [], _rejected("handoff_unauthorized", "父员工不能委托该工具")
        delegated.append(token)
    context = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "task_id": task_id,
        "employee_id": employee_id,
        "employee_tool_allowlist": list(delegated),
    }
    for token in delegated:
        tool_id, action = _split_tool(token) or ("", "")
        denial = actor_tool_denial(tool_id, action, context)
        if denial is not None:
            return [], _rejected(
                str(denial.get("error_code") or "handoff_unauthorized"),
                str(denial.get("message") or "工具授权被拒绝"),
            )
    return delegated, None


def _auto_tool(delegated: list[str]) -> tuple[str, str] | None:
    for token in delegated:
        parsed = _split_tool(token)
        if parsed is None:
            continue
        spec = get_tool_action_spec(*parsed)
        if spec is not None and spec.risk == "low" and spec.idempotent:
            return parsed
    return None


def _plan(tool_id: str, action: str, body: dict[str, Any]) -> PlanGraph:
    effect = body.get("effect") if isinstance(body.get("effect"), dict) else {}
    params: dict[str, Any] = {}
    keyword = str(effect.get("keyword") or "").strip()
    if keyword:
        params["keyword"] = keyword
    return PlanGraph(
        plan_id=f"handoff-{body.get('task_id')}",
        intent=str(body.get("goal") or "员工交接"),
        nodes=[
            WorkflowNode(
                node_id="handoff-work",
                tool_id=tool_id,
                action=action,
                params=params,
                risk="low",
                idempotent=True,
            )
        ],
        risk_level="low",
    )


def _child_receipt(
    parent: AgentRun,
    child: AgentRun,
    *,
    task_id: str,
    tenant_id: str,
    user_id: str,
    target: str,
    delegated: list[str],
) -> dict[str, Any]:
    context = dict(child.metadata.get("runtime_context") or {})
    linked = (parent.metadata.get("child_results") or {}).get(child.run_id)
    same_tenant = str(context.get("tenant_id") or "") == tenant_id
    same_parent = str(context.get("parent_task_id") or "") == task_id
    same_employee = str(context.get("employee_id") or "") == target
    same_tools = list(context.get("employee_tool_allowlist") or []) == list(delegated)
    if (
        child.run_id == parent.run_id
        or child.status != "completed"
        or not isinstance(linked, dict)
        or not same_tenant
        or not same_parent
        or not same_employee
        or not same_tools
    ):
        return _rejected("handoff_child_failed", "子员工没有完成交接任务") | {
            "parent_task_id": task_id,
            "child_task_id": child.run_id,
            "execution_status": child.status,
        }
    result = {
        "final_output": child.final_output,
        "parent_task_id": task_id,
        "child_task_id": child.run_id,
        "status": child.status,
        "employee_id": target,
    }
    return {
        "success": True,
        "parent_task_id": task_id,
        "child_task_id": child.run_id,
        "child_run_id": child.run_id,
        "parent_run_id": parent.run_id,
        "target_employee": target,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "employee_id": target,
        "execution_status": child.status,
        "delegated_tools": list(delegated),
        "result": result,
    }
