"""Verify original employee completion through its ledger and registered child Runs.

Only the existing handoff consumer has durable, independently verifiable child
receipts here. Arbitrary workspace scripts remain unverified even when they say ok.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.verification_readback import _report
from app.application.employee_runtime.task_continuity import (
    SOURCE,
    _public_task,
    bound_task_children,
    load_employee_task_ledger,
    task_admission_origin,
)

OPERATIONS = frozenset({"run_tools", "child_return", "chain"})


def employee_payload(params: dict[str, Any]) -> dict[str, Any]:
    payload = dict(params["input"]) if isinstance(params.get("input"), dict) else {}
    for key, value in params.items():
        if key not in {
            "employee_id",
            "pack_id",
            "tool_name",
            "id",
            "task",
            "user_request",
            "input",
        }:
            payload.setdefault(key, value)
    return payload


class Unavailable(ValueError):
    pass


def _scope(node: dict, user: str, tenant: str) -> None:
    if (
        node.get("user_id") != user
        or node.get("tenant_id") != tenant
        or node.get("status") != "completed"
        or node.get("error_code")
    ):
        raise Unavailable("employee_original_task_incomplete")


def _original_handoff(task, body, receipt, context, workspace, *, source="") -> tuple[str, list]:
    from app.application.agent_orchestrator.result_verification import (
        latest_step_call,
        summarize_verification,
        verify_step_result,
    )
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.task_background import task_execution_context
    from app.application.employee_runtime import handoff_commit as handoff

    repository = handoff.get_agent_run_repository()
    if not isinstance(repository, SQLAlchemyAgentRunRepository) or not isinstance(receipt, dict):
        raise Unavailable("employee_original_run_unavailable")
    parent = repository.get(str(receipt.get("parent_run_id") or ""))
    child = repository.get(str(receipt.get("child_run_id") or ""))
    if parent is None or child is None or parent.run_id == child.run_id:
        raise Unavailable("employee_original_run_unavailable")
    saved = parent.metadata.get("runtime_context") or {}
    source = source or str(saved.get("employee_id") or "")
    identity = {
        "user_id": task["user_id"],
        "tenant_id": task["tenant_id"],
        "task_id": task["task_id"],
        "employee_id": source,
    }
    bindings = {
        "workspace_path": str(workspace.resolve()),
        **{
            key: saved[key]
            for key in ("_actor_authorization", "_mod_authorization", "workspace_id")
            if saved.get(key) is not None
        },
    }
    original_mod = (
        (saved.get("_mod_authorization") or {}).get("mod_id")
        or saved.get("mod_id")
        or saved.get("active_mod_id")
        or ""
    )
    current_mod = (
        (context.get("_mod_authorization") or {}).get("mod_id")
        or context.get("mod_id")
        or context.get("active_mod_id")
        or ""
    )
    if (
        original_mod != current_mod
        or not handoff._same_parent(parent, identity, bindings)
        or source not in {task["owner_employee"], *task.get("authorized_employees", [])}
    ):
        raise Unavailable("employee_original_scope_changed")
    delegated = handoff._delegated_call(body)
    if isinstance(delegated, dict):
        raise Unavailable("employee_original_call_unavailable")
    tool, action, params = delegated
    if tool == "employee":
        raise Unavailable("result_verifier_unavailable")
    target = str(body.get("target") or "")
    card, error = handoff._employee_card(str(workspace), target)
    if error or card is None or card["tenant_id"] != task["tenant_id"]:
        raise Unavailable("employee_original_scope_changed")
    current_bindings = {
        **bindings,
        **{
            key: context[key]
            for key in ("_actor_authorization", "_mod_authorization")
            if key in context
        },
    }
    permissions, denial = handoff._authorized_scope(
        body.get("permissions") or [],
        handoff._task_grant(task, source),
        tool_id=tool,
        action=action,
        tenant_id=task["tenant_id"],
        user_id=task["user_id"],
        task_id=task["task_id"],
        employee_id=target,
        bindings=current_bindings,
    )
    if denial:
        raise Unavailable("result_read_permission_unavailable")
    request = {
        "idempotency_key": str(
            body.get("idempotency_key") or context.get("idempotency_key") or ""
        ).strip(),
        "identity": identity,
        "bindings": bindings,
        "parent_run_id": parent.run_id,
        "target": target,
        "permissions": sorted(set(permissions)),
        "tool_id": tool,
        "action": action,
        "params": params,
        "goal": str(body.get("goal") or task.get("goal") or "员工交接"),
    }
    expected = handoff._read_handoff(repository, parent.run_id, request, canonical_hash(request))
    if expected.get("success") is not True or receipt != {**expected, "ok": True}:
        raise Unavailable("employee_original_receipt_changed")
    if not summarize_verification(child)["accepted"]:
        raise Unavailable("employee_child_verification_unavailable")
    checks = []
    # Read again under current permissions; never persist or execute the child.
    for step in child.steps:
        call = latest_step_call(child, step)
        if call is None:
            raise Unavailable("employee_child_verification_unavailable")
        observed = {
            **(child.metadata.get("runtime_context") or {}),
            **task_execution_context(child, step),
            **{
                key: current_bindings[key]
                for key in ("_actor_authorization", "_mod_authorization")
                if key in current_bindings
            },
            "run_id": child.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
        }
        report = verify_step_result(run=child, step=step, call=call, context=observed)
        if report.get("accepted") is not True:
            raise Unavailable("employee_child_verification_unavailable")
        checks.extend(report["checks"])
    return child.run_id, checks


def _step_receipts(ledger, task, context, workspace):
    for step in task.get("steps") or []:
        if step.get("tool") != "handoff_commit":
            raise Unavailable("result_verifier_unavailable")
        result = step.get("result_payload")
        call = ledger["tool_calls"].get(step.get("tool_call_id")) or {}
        side = ledger["side_effects"].get(step.get("idempotency_key")) or {}
        if (
            step.get("status") != "success"
            or call.get("status") != "success"
            or call.get("tool_call_id") != step.get("tool_call_id")
            or call.get("step_id") != step.get("step_id")
            or call.get("idempotency_key") != step.get("idempotency_key")
            or call.get("task_id") != task["task_id"]
            or side.get("task_id") != task["task_id"]
            or side.get("invocations") != 1
            or side.get("result") != result
            or call.get("result_payload") != result
        ):
            raise Unavailable("employee_original_receipt_changed")
        yield _original_handoff(task, step["params"], result, context, workspace)


def _chain_receipts(ledger, task, context, workspace):
    from app.application.agent_orchestrator.param_references import resolve_references

    chain = task.get("chain")
    if not chain:
        return
    employees, steps, completed = (chain.get(key) for key in ("employees", "steps", "completed"))
    if (
        not isinstance(employees, list)
        or len(employees) != 4
        or len(set(employees)) != 4
        or not isinstance(steps, list)
        or len(steps) != 4
        or not isinstance(completed, dict)
        or set(completed) != {step["step_id"] for step in steps}
    ):
        raise Unavailable("employee_original_chain_incomplete")
    outputs = {}
    previous_child = ""
    for index, step in enumerate(steps):
        record = ledger["handoffs"].get(completed[step["step_id"]]) or {}
        problems: list[str] = []
        params = resolve_references(copy.deepcopy(step["params"]), outputs, problems)
        source, target = employees[max(index - 1, 0)], employees[index]
        key = f"{task['task_id']}:chain:{step['step_id']}"
        expected = {
            "task_id": task["task_id"],
            "source_employee": source,
            "target_employee": target,
            "chain_step_id": step["step_id"],
            "delegated_tool": step["tool"],
            "delegated_action": step["action"],
            "delegated_params": params,
            "permissions": chain["permissions"],
            "idempotency_key": key,
            "status": "completed",
        }
        receipt = record.get("result_payload") or {}
        side = ledger["side_effects"].get(key) or {}
        if (
            problems
            or any(record.get(key) != value for key, value in expected.items())
            or record.get("handoff_id") != completed[step["step_id"]]
            or record.get("handoff_id") not in task["handoff_ids"]
            or side != {"task_id": task["task_id"], "invocations": 1, "result": receipt}
            or (previous_child and receipt.get("parent_run_id") != previous_child)
        ):
            raise Unavailable("employee_original_chain_changed")
        child_id, checks = _original_handoff(
            task,
            {
                "target": target,
                "permissions": chain["permissions"],
                "idempotency_key": key,
                "delegated_tool": step["tool"],
                "delegated_action": step["action"],
                "delegated_params": params,
            },
            receipt,
            context,
            workspace,
            source=source,
        )
        outputs[step["step_id"]] = receipt["result"]["final_output"]["node_outputs"]["handoff-work"]
        previous_child = child_id
        yield child_id, checks


def verify_employee_completion(run, step, call, output, context, employee) -> dict[str, Any]:
    from app.infrastructure.workspace import workspace_root

    source = "employee_task_ledger"
    try:
        payload = employee_payload(step.params)
        operation = str(payload.get("continuity_action") or "").strip()
        workspace = workspace_root()
        origin = task_admission_origin(context, workspace)
        if (
            operation not in OPERATIONS
            or not payload.get("task_id")
            or origin["workspace_sha256"]
            != (call.metadata.get("verification_contract") or {}).get("workspace_sha256")
            or Path(str(context.get("workspace_root") or workspace)).resolve()
            != workspace.resolve()
        ):
            raise Unavailable("result_verifier_unavailable")
        ledger = load_employee_task_ledger(workspace)
        task_id = str(payload["task_id"])
        task = ledger["tasks"].get(task_id)
        data = output.get("data") or {}
        if (
            not isinstance(task, dict)
            or task.get("task_id") != task_id
            or employee not in {task.get("owner_employee"), *task.get("authorized_employees", [])}
            or data.get("source") != SOURCE
            or data.get("task_id") != task_id
            or data.get("task") != _public_task(task)
            or data.get("business_success") is not True
            or data.get("events")
            != [item for item in ledger["events"] if item.get("task_id") == task_id]
        ):
            raise Unavailable("employee_original_task_changed")
        _scope(task, origin["user_id"], origin["tenant_id"])
        if operation == "chain":
            definition = {key: payload.get(key) for key in ("employees", "permissions", "steps")}
            definition["steps"] = [
                dict(item, step_id=str(item.get("step_id") or f"s{index + 1}"))
                for index, item in enumerate(definition["steps"] or [])
            ]
            if any(
                (task.get("chain") or {}).get(key) != value for key, value in definition.items()
            ):
                raise Unavailable("employee_original_chain_changed")
        root = task
        if operation == "child_return":
            root = ledger["tasks"].get(task.get("parent_task_id"))
            if not isinstance(root, dict) or task_id not in root.get("child_task_ids", []):
                raise Unavailable("employee_original_parent_unavailable")
        pending, visited, proofs, projections, checks = [root], set(), {}, [], []
        while pending:
            node = pending.pop()
            _scope(node, origin["user_id"], origin["tenant_id"])
            if node["task_id"] in visited or ledger["tasks"].get(node["task_id"]) is not node:
                raise Unavailable("employee_original_child_set_changed")
            visited.add(node["task_id"])
            children, unavailable = bound_task_children(ledger, node)
            if unavailable:
                raise Unavailable("employee_original_child_set_changed")
            pending.extend(children)
            receipts = list(_step_receipts(ledger, node, context, workspace))
            receipts.extend(_chain_receipts(ledger, node, context, workspace))
            for child_id, observed in receipts:
                if child_id in proofs:
                    raise Unavailable("employee_original_child_reused")
                proofs[child_id] = node["task_id"]
                checks.extend(observed)
            if not receipts and not children:
                projections.append(node)
        for node in projections:
            if (
                proofs.get(node["task_id"]) != node.get("parent_task_id")
                or (node.get("result_payload") or {}).get("child_run_id") != node["task_id"]
            ):
                raise Unavailable("employee_original_run_unavailable")
        if not proofs:
            raise Unavailable("result_verifier_unavailable")
        report = _report(
            "verified",
            "result_verified",
            source,
            scope="task_completion",
            task_id=root["task_id"],
            business_effect_verified=True,
            child_run_ids=sorted(proofs),
            required_task_ids=sorted(visited),
            task_sha256=canonical_hash(root),
        )
        report["checks"].extend(checks)
        return report
    except Unavailable as exc:
        return _report("inconclusive", str(exc), source)
