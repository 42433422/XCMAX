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


def commit_registered_handoff(
    args: dict[str, Any] | None,
    workspace: str | None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authorize from the runtime context and parent task, then start the child run."""
    body = dict(args or {})
    context = dict(runtime_context or {})
    trusted, rejection = _trusted_identity(body, context)
    if rejection is not None:
        return rejection
    assert trusted is not None
    parent = _parent_task(workspace, trusted["task_id"])
    if parent is None:
        return _rejected("handoff_unauthorized", "父任务记录不存在")
    if str(parent.get("tenant_id") or "") != trusted["tenant_id"]:
        return _rejected("handoff_cross_tenant", "父任务不属于当前企业")
    if str(parent.get("user_id") or "") != trusted["user_id"]:
        return _rejected("handoff_unauthorized", "父任务不属于当前用户")
    owner = str(parent.get("owner_employee") or "")
    authorized = {str(item) for item in parent.get("authorized_employees") or []}
    if trusted["employee_id"] not in {owner, *authorized}:
        return _rejected("handoff_unauthorized", "父员工与任务记录不一致")
    target = str(body.get("target") or "").strip()
    permissions = body.get("permissions")
    if not target or not isinstance(permissions, list) or not permissions:
        return _rejected("handoff_context_missing", "交接缺少目标员工或工具范围")
    card, card_error = _employee_card(workspace, target)
    if card_error:
        return _rejected(card_error, "目标员工身份不可核验")
    assert card is not None
    forged_tenant = str(body.get("target_tenant_id") or "").strip()
    if forged_tenant and forged_tenant != card["tenant_id"]:
        return _rejected("handoff_cross_tenant", "不能用请求里的企业字段替换员工档案")
    if card["tenant_id"] != trusted["tenant_id"]:
        return _rejected("handoff_cross_tenant", "不能把任务交给其他企业的员工")
    delegated = _delegated_call(body)
    if isinstance(delegated, dict):
        return delegated
    tool_id, action, params = delegated
    scope, denial = _authorized_scope(
        permissions,
        _task_grant(parent, trusted["employee_id"]),
        tool_id=tool_id,
        action=action,
        tenant_id=trusted["tenant_id"],
        user_id=trusted["user_id"],
        task_id=trusted["task_id"],
        employee_id=target,
    )
    if denial is not None:
        return denial
    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id=trusted["user_id"], message=str(body.get("goal") or "员工交接"))
    run.metadata["runtime_context"] = {
        "tenant_id": trusted["tenant_id"],
        "user_id": trusted["user_id"],
        "task_id": trusted["task_id"],
        "employee_id": trusted["employee_id"],
    }
    run.metadata["task_context"] = {"task_id": trusted["task_id"]}
    repository.save(run)
    child = AgentOrchestrator(repository=repository).start_employee_handoff(
        run,
        employee_id=target,
        allowlist=list(scope),
        message=str(body.get("goal") or "员工交接"),
        plan=_plan(tool_id, action, params, trusted["task_id"], str(body.get("goal") or "")),
    )
    return _child_receipt(
        run,
        child,
        task_id=trusted["task_id"],
        tenant_id=trusted["tenant_id"],
        user_id=trusted["user_id"],
        target=target,
        delegated=scope,
        tool_id=tool_id,
        action=action,
        params=params,
    )


def _trusted_identity(
    body: dict[str, Any], context: dict[str, Any]
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    tenant_id = str(context.get("tenant_id") or "").strip()
    user_id = str(context.get("user_id") or "").strip()
    employee_id = str(context.get("employee_id") or "").strip()
    task_id = str(context.get("task_id") or "").strip()
    if not tenant_id or not user_id or not employee_id or not task_id:
        return None, _rejected("handoff_context_missing", "交接缺少可信运行上下文")
    for key, trusted in (
        ("tenant_id", tenant_id),
        ("user_id", user_id),
        ("source", employee_id),
        ("task_id", task_id),
    ):
        supplied = str(body.get(key) or "").strip()
        if supplied and supplied != trusted:
            return None, _rejected("handoff_unauthorized", "交接请求与可信上下文不一致")
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "employee_id": employee_id,
        "task_id": task_id,
    }, None


def _parent_task(workspace: str | None, task_id: str) -> dict[str, Any] | None:
    if not workspace:
        return None
    from app.application.employee_runtime.task_continuity import load_employee_task_ledger

    state = load_employee_task_ledger(workspace)
    tasks = state.get("tasks") if isinstance(state, dict) else None
    task = tasks.get(task_id) if isinstance(tasks, dict) else None
    if not isinstance(task, dict) or not str(task.get("tenant_id") or "").strip():
        return None
    return task


def _employee_card(workspace: str | None, target: str) -> tuple[dict[str, str] | None, str]:
    if not target or target in {".", ".."} or "/" in target or "\\" in target:
        return None, "handoff_unknown_employee"
    root = Path(workspace) if workspace else None
    folder = None if root is None else root / "employees"
    cards = sorted(folder.glob("*.json")) if folder is not None and folder.is_dir() else []
    if not cards:
        return None, "handoff_identity_unverified"
    path = folder / f"{target}.json" if folder is not None else None
    if path is None or not path.is_file():
        return None, "handoff_unknown_employee"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "handoff_identity_unverified"
    if not isinstance(loaded, dict):
        return None, "handoff_identity_unverified"
    if loaded.get("available") is False:
        return None, "handoff_unknown_employee"
    named = str(loaded.get("employee_id") or "").strip()
    tenant_id = str(loaded.get("tenant_id") or "").strip()
    if not named or named != target or not tenant_id:
        return None, "handoff_identity_unverified"
    return {"employee_id": named, "tenant_id": tenant_id}, ""


def _task_grant(task: dict[str, Any], employee_id: str) -> list[str]:
    grants = task.get("grants")
    if not isinstance(grants, dict):
        return []
    raw = grants.get(employee_id)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _delegated_call(
    body: dict[str, Any],
) -> tuple[str, str, dict[str, Any]] | dict[str, Any]:
    tool_id = str(body.get("delegated_tool") or "").strip()
    action = str(body.get("delegated_action") or "").strip()
    params = body.get("delegated_params")
    if not tool_id or not action or not isinstance(params, dict):
        return _rejected("handoff_context_missing", "交接缺少要执行的工具、动作和参数")
    return tool_id, action, dict(params)


def _authorized_scope(
    permissions: list[Any],
    grant: list[str],
    *,
    tool_id: str,
    action: str,
    tenant_id: str,
    user_id: str,
    task_id: str,
    employee_id: str,
) -> tuple[list[str], dict[str, Any] | None]:
    if not grant:
        return [], _rejected("handoff_unauthorized", "父任务没有可委托的工具范围")
    grant_set = set(grant)
    wildcard = "*" in grant_set
    delegated = f"{tool_id}.{action}"
    allowed: list[str] = []
    for raw in permissions:
        token = str(raw or "").strip()
        parsed = _split_tool(token)
        if parsed is None or (not wildcard and token not in grant_set and parsed[0] not in grant_set):
            return [], _rejected("handoff_unauthorized", "父员工不能委托该工具")
        allowed.append(token)
    if delegated not in allowed:
        return [], _rejected("handoff_unauthorized", "要执行的工具不在本次委托范围内")
    context = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "task_id": task_id,
        "employee_id": employee_id,
        "employee_tool_allowlist": list(allowed),
    }
    for token in allowed:
        parsed = _split_tool(token)
        if parsed is None:
            return [], _rejected("handoff_unauthorized", "父员工不能委托该工具")
        denial = actor_tool_denial(parsed[0], parsed[1], context)
        if denial is not None:
            return [], _rejected(
                str(denial.get("error_code") or "handoff_unauthorized"),
                str(denial.get("message") or "工具授权被拒绝"),
            )
    spec = get_tool_action_spec(tool_id, action)
    if spec is None or spec.risk != "low" or not spec.idempotent:
        return [], _rejected("handoff_unauthorized", "委托任务不是可自动执行的低风险工具")
    return allowed, None


def _split_tool(token: str) -> tuple[str, str] | None:
    tool_id, separator, action = str(token).strip().partition(".")
    if not separator or not tool_id or not action or "." in action:
        return None
    return tool_id, action


def _plan(
    tool_id: str, action: str, params: dict[str, Any], task_id: str, goal: str
) -> PlanGraph:
    return PlanGraph(
        plan_id=f"handoff-{task_id}",
        intent=goal or "员工交接",
        nodes=[
            WorkflowNode(
                node_id="handoff-work",
                tool_id=tool_id,
                action=action,
                params=dict(params),
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
    tool_id: str,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    context = dict(child.metadata.get("runtime_context") or {})
    linked = (parent.metadata.get("child_results") or {}).get(child.run_id)
    step = child.steps[0] if child.steps else None
    executed = {} if step is None else dict(step.params or {})
    same_call = (
        step is not None and step.tool_id == tool_id and step.action == action and executed == params
    )
    same_tenant = str(context.get("tenant_id") or "") == tenant_id
    same_parent = str(context.get("parent_task_id") or "") == task_id
    same_employee = str(context.get("employee_id") or "") == target
    same_tools = list(context.get("employee_tool_allowlist") or []) == list(delegated)
    if (
        child.run_id == parent.run_id
        or child.status != "completed"
        or not isinstance(linked, dict)
        or not same_call
        or not same_tenant
        or not same_parent
        or not same_employee
        or not same_tools
    ):
        return _rejected("handoff_child_failed", "子员工没有按委托任务完成交接") | {
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
        "tool_id": step.tool_id,
        "action": step.action,
        "params": executed,
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


def _rejected(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "ok": False, "error_code": code, "error_message": message}
