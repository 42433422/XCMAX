"""Tenant checks for child results and run audit access."""

from __future__ import annotations

from typing import Any


def attach_child_result(parent: Any, child: Any) -> bool:
    """Parent can read the child final result only inside the same tenant."""
    parent_tenant = str((parent.metadata.get("runtime_context") or {}).get("tenant_id") or "")
    child_context = child.metadata.get("runtime_context") or {}
    child_tenant = str(child_context.get("tenant_id") or "")
    if not parent_tenant or parent_tenant != child_tenant:
        return False
    parent.metadata.setdefault("child_results", {})[child.run_id] = {
        "status": child.status,
        "final_output": child.final_output,
        "parent_task_id": child_context.get("parent_task_id"),
        "parent_run_id": child_context.get("parent_run_id"),
        "tenant_id": child_tenant,
        "employee_id": child_context.get("employee_id"),
    }
    return True


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
