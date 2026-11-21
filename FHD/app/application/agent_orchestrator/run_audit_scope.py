"""Tenant checks for child results and run audit access."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _result_scope(run: Any) -> tuple[str, str, str] | None:
    context = run.metadata.get("runtime_context") or {}
    if not isinstance(context, dict):
        return None
    binding = context.get("_mod_authorization") or {}
    if not isinstance(binding, dict):
        return None
    owner, tenant = str(run.user_id or ""), str(context.get("tenant_id") or "")
    mod = str(binding.get("mod_id") or context.get("mod_id") or "")
    if context.get("mod_id") and binding.get("mod_id") and str(context["mod_id"]) != mod:
        return None
    return (owner, tenant, mod) if owner and tenant else None


def attach_child_result(parent: Any, child: Any) -> bool:
    """Attach a snapshot only for the same authenticated owner, tenant and Mod."""
    scope = _result_scope(parent)
    child_context = child.metadata.get("runtime_context") or {}
    if scope is None or scope != _result_scope(child):
        return False
    parent.metadata.setdefault("child_results", {})[child.run_id] = {
        "status": child.status,
        "final_output": child.final_output,
        "parent_task_id": child_context.get("parent_task_id"),
        "parent_run_id": child_context.get("parent_run_id"),
        "tenant_id": scope[1],
        "user_id": scope[0],
        "mod_id": scope[2],
        "source": "snapshot",
        "employee_id": child_context.get("employee_id"),
    }
    return True


def project_child_results(parent: Any, read_run: Callable[[str], Any]) -> dict[str, Any]:
    """Refresh only already bound children; missing or out-of-scope receipts stay unknown."""
    from app.application.agent_orchestrator.trace_payloads import _payload_status
    from app.domain.task_lifecycle.results import execution_result_pending_state

    children = parent.metadata.get("child_results") or {}
    parent_scope = _result_scope(parent)
    projected: dict[str, Any] = {}
    for run_id in children if isinstance(children, dict) else ():
        unknown = {
            "status": "unknown",
            "execution_state": "unknown",
            "success": False,
            "final_output": {},
            "source": "child_run_unavailable",
            "retryable": False,
            "requires_reconciliation": True,
            "parent_run_id": parent.run_id,
        }
        projected[run_id] = unknown
        try:
            child = read_run(str(run_id))
            context = child.metadata.get("runtime_context") or {} if child is not None else {}
            child_scope = _result_scope(child) if child is not None else None
            if (
                child is None
                or child.run_id != run_id
                or parent_scope is None
                or child_scope is None
                or parent_scope != child_scope
                or context.get("parent_run_id") != parent.run_id
            ):
                continue
            outputs = {
                "final_output": child.final_output,
                "outputs": [step.output for step in child.steps],
            }
            state = execution_result_pending_state(outputs) or _payload_status(
                {"agent_status": child.status, **outputs}
            )
            recovery = child.metadata.get("recovery")
            if (
                isinstance(recovery, dict)
                and recovery.get("state") == "manual_reconciliation_required"
            ):
                state = "unknown"
            if state == "waiting_user":
                waiting = next(
                    (step for step in child.steps if step.status == "waiting_user"), None
                )
                state = (
                    "waiting_input"
                    if waiting is None or waiting.tool_id == "clarify"
                    else "waiting_approval"
                )
            projected[run_id] = {
                "status": state,
                "execution_state": state,
                "success": state == "completed",
                "final_output": child.final_output,
                "source": "child_run",
                "run_id": child.run_id,
                "parent_run_id": parent.run_id,
                "parent_task_id": context.get("parent_task_id"),
                "tenant_id": child_scope[1],
                "employee_id": context.get("employee_id"),
                **(
                    {"requires_reconciliation": True, "retryable": False}
                    if state == "unknown"
                    else {}
                ),
            }
        except RECOVERABLE_ERRORS:
            continue
    return projected


def read_run_audit(run: Any, *, reader_tenant: str) -> dict[str, Any] | None:
    """Ordinary users cannot read another tenant's tool audit."""
    owner = str((run.metadata.get("runtime_context") or {}).get("tenant_id") or "")
    if not owner or str(reader_tenant) != owner:
        return None
    return {
        "run_id": run.run_id,
        "tenant_id": owner,
        "events": [event.to_dict() for event in run.events],
    }


def mutate_run_audit(run: Any, *, reader_tenant: str, message: str) -> bool:
    """Refuse writes to another tenant's audit log."""
    if read_run_audit(run, reader_tenant=reader_tenant) is None:
        return False
    run.add_event("audit.note", message, {"tenant_id": str(reader_tenant)})
    return True
