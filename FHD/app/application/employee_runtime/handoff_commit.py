"""Registered handoff_commit. It starts the existing employee handoff run."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    SQLAlchemyAgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.task_context import apply_task_context, task_context_of
from app.application.agent_orchestrator.tool_permission import (
    _idempotency_path,
    actor_tool_denial,
    begin_idempotent_replay,
    finish_idempotent_replay,
)
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.employee_runtime.handoff_identity import load_identity_card
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.domain.task_lifecycle.results import (
    execution_result_error,
    execution_result_requires_reconciliation,
    execution_result_wait_reason,
)
from app.infrastructure.auth.agent_mod_scope import validate_actor_context
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def commit_registered_handoff(
    args: dict[str, Any] | None,
    workspace: str | None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authorize from the runtime context and parent task, then start the child run."""
    body = dict(args or {})
    context = dict(runtime_context or {})
    identity_ids, rejection = _handoff_identity_ids(body, context)
    if rejection is not None:
        return rejection
    assert identity_ids is not None
    parent = _parent_task(workspace, identity_ids["task_id"])
    if parent is None:
        return _rejected("handoff_unauthorized", "父任务记录不存在")
    if str(parent.get("tenant_id") or "") != identity_ids["tenant_id"]:
        return _rejected("handoff_cross_tenant", "父任务不属于当前企业")
    if str(parent.get("user_id") or "") != identity_ids["user_id"]:
        return _rejected("handoff_unauthorized", "父任务不属于当前用户")
    owner = str(parent.get("owner_employee") or "")
    authorized = {str(item) for item in parent.get("authorized_employees") or []}
    if identity_ids["employee_id"] not in {owner, *authorized}:
        return _rejected("handoff_unauthorized", "父员工与任务记录不一致")
    target = body.get("target")
    permissions = body.get("permissions")
    if (
        type(target) is not str
        or not target.strip()
        or not isinstance(permissions, list)
        or not permissions
    ):
        return _rejected("handoff_context_missing", "交接缺少目标员工或工具范围")
    target = target.strip()
    card, card_error = _employee_card(workspace, target)
    if card_error:
        return _rejected(card_error, "目标员工身份不可核验")
    assert card is not None
    forged_tenant = str(body.get("target_tenant_id") or "").strip()
    if forged_tenant and forged_tenant != card["tenant_id"]:
        return _rejected("handoff_cross_tenant", "不能用请求里的企业字段替换员工档案")
    if card["tenant_id"] != identity_ids["tenant_id"]:
        return _rejected("handoff_cross_tenant", "不能把任务交给其他企业的员工")
    delegated = _delegated_call(body)
    if isinstance(delegated, dict):
        return delegated
    tool_id, action, params = delegated
    bindings = {"workspace_path": str(Path(workspace).resolve())}
    for key in ("_actor_authorization", "_mod_authorization", "workspace_id"):
        if context.get(key) is not None:
            bindings[key] = copy.deepcopy(context[key])
    if (
        context.get("_actor_authorization") is not None
        or context.get("_mod_authorization") is not None
        or context.get("mod_id")
        or context.get("active_mod_id")
    ):
        denied = validate_actor_context({**context, **identity_ids})
        if denied is not None:
            return denied
    scope, denial = _authorized_scope(
        permissions,
        _task_grant(parent, identity_ids["employee_id"]),
        tool_id=tool_id,
        action=action,
        tenant_id=identity_ids["tenant_id"],
        user_id=identity_ids["user_id"],
        task_id=identity_ids["task_id"],
        employee_id=target,
        bindings=bindings,
    )
    if denial is not None:
        return denial
    return _persistent_handoff(
        body, context, identity_ids, parent, target, scope, tool_id, action, params, bindings
    )


def _persistent_handoff(
    body, context, identity, task, target, scope, tool_id, action, params, bindings
):
    run = None
    try:
        repository = get_agent_run_repository()
        if not isinstance(repository, SQLAlchemyAgentRunRepository) or _idempotency_path() is None:
            return _rejected("handoff_durability_required", "交接需要持久任务记录与幂等声明")
        run, denial = _parent_run(repository, identity, context, task, bindings)
        if denial is not None:
            return denial
        assert run is not None
        for field in ("run_id", "parent_run_id"):
            if body.get(field) and str(body[field]) != run.run_id:
                return _rejected("handoff_unauthorized", "交接请求与原父运行不一致")
        key = str(
            body.get("idempotency_key")
            or context.get("idempotency_key")
            or f"{identity['task_id']}:handoff:{identity['employee_id']}:{target}"
        ).strip()
        request = {
            "idempotency_key": key,
            "identity": identity,
            "bindings": bindings,
            "parent_run_id": run.run_id,
            "target": target,
            "permissions": sorted(set(scope)),
            "tool_id": tool_id,
            "action": action,
            "params": copy.deepcopy(params),
            "goal": str(body.get("goal") or task.get("goal") or "员工交接"),
        }
        claim, replay = begin_idempotent_replay(
            identity, "employee_handoff", "commit", {"idempotency_key": key, "request": request}
        )
        if not claim:
            return _rejected("handoff_context_missing", "交接缺少稳定幂等标识")
        fingerprint = canonical_hash(request)
        if replay is not None:
            if replay.get("error_code") == "idempotency_conflict":
                return replay
            # A reply can be recovered only by reading the exact persisted child and parent.
            # Never release an unfinished claim or dispatch a replacement child here.
            return _read_handoff(repository, run.run_id, request, fingerprint)
        repository.save(run)
        plan = _plan(tool_id, action, request["params"], identity["task_id"], request["goal"])
        plan.metadata["handoff_request"] = fingerprint
        AgentOrchestrator(repository=repository).start_employee_handoff(
            run,
            employee_id=target,
            allowlist=request["permissions"],
            message=request["goal"],
            plan=plan,
        )
        receipt = _read_handoff(repository, run.run_id, request, fingerprint)
        # Generic claims cannot retain a known failure: settle a readback gate,
        # while the persisted Run remains the source of the precise business result.
        retained = (
            receipt
            if receipt.get("success")
            else _unknown_handoff(
                identity["task_id"], run.run_id, str(receipt.get("child_run_id") or "")
            )
        )
        finish_idempotent_replay(claim, retained)
        return receipt
    except RECOVERABLE_ERRORS + (IntegrityError,):
        logger.warning("employee handoff requires reconciliation", exc_info=True)
        # Retain the original claim across every uncertain persistence/execution window.
        return _unknown_handoff(identity["task_id"], run.run_id if run is not None else "")


def _parent_run(repository, identity, context, task, bindings):
    supplied = {str(context.get(key) or "").strip() for key in ("run_id", "agent_run_id")} - {""}
    if len(supplied) > 1:
        return None, _rejected("handoff_unauthorized", "可信上下文中的父运行不一致")
    if supplied:
        run = repository.get(supplied.pop())
        if run is None or not _same_parent(run, identity, bindings):
            return None, _rejected("handoff_unauthorized", "原父运行与交接身份不一致")
        return run, None
    # A previous completed handoff already records this employee's real child run.
    for prior in reversed(task.get("prior_results") or []):
        receipt = prior.get("result") if isinstance(prior, dict) else None
        if (
            not isinstance(receipt, dict)
            or prior.get("employee") != identity["employee_id"]
            or prior.get("confirmed") is not True
        ):
            continue
        child_id = str(receipt.get("child_run_id") or "")
        if not child_id:
            continue
        run = repository.get(child_id)
        if run is None or not _same_parent(run, identity, bindings):
            return None, _unknown_handoff(identity["task_id"], child_id)
        return run, None
    existing = repository.get_task(
        user_id=identity["user_id"],
        tenant_id=identity["tenant_id"],
        task_id=identity["task_id"],
    )
    if existing is not None:
        for run_id in (existing.root_run_id, existing.active_run_id):
            run = repository.get(run_id) if run_id else None
            if run is not None and _same_parent(run, identity, bindings):
                return run, None
    # Stable bridge for an existing continuity task; save() maintains AgentTask's mapping.
    run_id = "handoff_parent_" + canonical_hash([identity, bindings])
    run = repository.get(run_id)
    if run is not None:
        return (
            (run, None)
            if _same_parent(run, identity, bindings)
            else (None, _rejected("handoff_unauthorized", "父任务映射与交接身份不一致"))
        )
    run = AgentRun(
        user_id=identity["user_id"],
        message=str(task.get("goal") or "员工交接"),
        run_id=run_id,
        status="running",
    )
    run.created_at = str(task.get("created_at") or run.created_at)
    run.metadata["runtime_context"] = {
        **identity,
        **bindings,
        "source": "employee_continuity",
        "task_type": "employee",
    }
    run.metadata["runtime_context"]["root_run_id"] = run.run_id
    apply_task_context(run, run.metadata["runtime_context"])
    return run, None


def _same_parent(run: AgentRun, identity: dict[str, str], bindings: dict[str, Any]) -> bool:
    context = run.metadata.get("runtime_context") or {}
    return (
        run.user_id == identity["user_id"]
        and task_context_of(run).get("task_id") == identity["task_id"]
        and task_context_of(run).get("workspace_path") == bindings["workspace_path"]
        and all(
            context.get(key) == bindings.get(key)
            for key in ("_actor_authorization", "_mod_authorization", "workspace_id")
        )
        and all(
            str(context.get(key) or "") == identity[key]
            for key in ("tenant_id", "user_id", "employee_id")
        )
    )


def _read_handoff(
    repository: AgentRunRepository, parent_id: str, request: dict, fingerprint: str
) -> dict:
    identity = request["identity"]
    parent = repository.get(parent_id)
    children = [
        run
        for run in repository.list_task_runs(
            user_id=identity["user_id"], task_id=identity["task_id"]
        )
        if (run.metadata.get("runtime_context") or {}).get("parent_run_id") == parent_id
        and ((run.metadata.get("plan") or {}).get("metadata") or {}).get("handoff_request")
        == fingerprint
    ]
    if (
        parent is None
        or not _same_parent(parent, identity, request["bindings"])
        or len(children) != 1
    ):
        return _unknown_handoff(identity["task_id"], parent_id)
    child = children[0]
    receipt = _child_receipt(
        parent,
        child,
        task_id=identity["task_id"],
        tenant_id=identity["tenant_id"],
        user_id=identity["user_id"],
        target=request["target"],
        delegated=request["permissions"],
        tool_id=request["tool_id"],
        action=request["action"],
        params=request["params"],
    )
    if receipt.get("success") or (
        receipt.get("error_code") == "handoff_child_failed"
        and (
            child.status in {"failed", "cancelled", "rejected"}
            or (
                child.status == "blocked"
                and all(
                    step.status == "failed" and step.output.get("success") is False
                    for step in child.steps
                )
            )
        )
        and not execution_result_requires_reconciliation(child.final_output)
        and not execution_result_wait_reason(child.final_output)
        and all(
            not execution_result_requires_reconciliation(step.output)
            and not execution_result_wait_reason(step.output)
            for step in child.steps
        )
    ):
        return {
            **receipt,
            "parent_run_id": parent_id,
            "child_run_id": child.run_id,
            "retryable": False,
        }
    return _unknown_handoff(identity["task_id"], parent_id, child.run_id)


def _unknown_handoff(task_id: str, parent_id: str, child_id: str = "") -> dict[str, Any]:
    return _rejected("handoff_reconciliation_required", "交接原任务结果待核对，未重新执行") | {
        "parent_task_id": task_id,
        "parent_run_id": parent_id,
        "child_run_id": child_id,
        "outcome": "unknown",
        "retryable": False,
        "reconciliation_required": True,
    }


def _handoff_identity_ids(
    body: dict[str, Any], context: dict[str, Any]
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Project only the four identity IDs; credentials stay outside the handoff metadata."""
    tenant_id = str(context.get("tenant_id") or "").strip()
    user_id = str(context.get("user_id") or "").strip()
    employee_id = str(context.get("employee_id") or "").strip()
    task_id = str(context.get("task_id") or "").strip()
    if not tenant_id or not user_id or not employee_id or not task_id:
        return None, _rejected("handoff_context_missing", "交接缺少可信运行上下文")
    for key, expected_id in (
        ("tenant_id", tenant_id),
        ("user_id", user_id),
        ("source", employee_id),
        ("task_id", task_id),
    ):
        supplied = str(body.get(key) or "").strip()
        if supplied and supplied != expected_id:
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
    card, error = load_identity_card(workspace, target)
    if error:
        return None, error
    assert card is not None
    if not card["available"]:
        return None, "handoff_unknown_employee"
    return {"employee_id": card["employee_id"], "tenant_id": card["tenant_id"]}, ""


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
    bindings: dict[str, Any],
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
        if parsed is None or (
            not wildcard and token not in grant_set and parsed[0] not in grant_set
        ):
            return [], _rejected("handoff_unauthorized", "父员工不能委托该工具")
        allowed.append(token)
    if delegated not in allowed:
        return [], _rejected("handoff_unauthorized", "要执行的工具不在本次委托范围内")
    context = {
        **bindings,
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


def _plan(tool_id: str, action: str, params: dict[str, Any], task_id: str, goal: str) -> PlanGraph:
    return PlanGraph(
        plan_id=f"handoff-{task_id}",
        intent=goal or "员工交接",
        nodes=[
            WorkflowNode(
                node_id="handoff-work",
                tool_id=tool_id,
                action=action,
                params=copy.deepcopy(params),
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
        len(child.steps) == 1
        and step is not None
        and step.tool_id == tool_id
        and step.action == action
        and executed == params
    )
    same_tenant = str(context.get("tenant_id") or "") == tenant_id
    same_user = child.user_id == user_id and str(context.get("user_id") or "") == user_id
    same_parent = (
        str(context.get("parent_task_id") or "") == task_id
        and context.get("parent_run_id") == parent.run_id
    )
    same_employee = str(context.get("employee_id") or "") == target
    same_tools = list(context.get("employee_tool_allowlist") or []) == list(delegated)
    if (
        step is None
        or child.run_id == parent.run_id
        or not isinstance(linked, dict)
        or linked.get("status") != child.status
        or linked.get("final_output") != child.final_output
        or any(
            linked.get(key) != context.get(key)
            for key in ("parent_task_id", "parent_run_id", "tenant_id", "employee_id")
        )
        or not same_call
        or not same_user
        or not same_tenant
        or not same_parent
        or not same_employee
        or not same_tools
        or any(
            context.get(key) != (parent.metadata.get("runtime_context") or {}).get(key)
            for key in (
                "_actor_authorization",
                "_mod_authorization",
                "workspace_path",
                "workspace_id",
            )
        )
    ):
        return _rejected("handoff_receipt_mismatch", "子员工交接回执与原任务不一致") | {
            "parent_task_id": task_id,
            "child_task_id": child.run_id,
            "execution_status": child.status,
        }
    if (
        child.status != "completed"
        or step.status != "completed"
        or execution_result_error(child.final_output)
        or execution_result_error(step.output)
    ):
        return _rejected("handoff_child_failed", "子员工尚未成功完成委托任务") | {
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
