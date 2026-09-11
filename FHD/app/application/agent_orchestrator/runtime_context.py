"""Merge continuation options without changing persisted data ownership."""

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun


class RuntimeContextOwnershipError(ValueError):
    """A continuation attempted to change the task's authenticated data scope."""


def merge_runtime_context(run: AgentRun, updates: dict[str, Any] | None) -> dict[str, Any]:
    context = dict(run.metadata.get("runtime_context") or {})
    updates = dict(updates or {})
    if "_mod_authorization" in updates:
        if updates["_mod_authorization"] != context.get("_mod_authorization"):
            raise RuntimeContextOwnershipError("不能更改任务的 Mod 授权范围")
        updates.pop("_mod_authorization")
    if "tenant_id" in updates:
        if str(updates["tenant_id"] or "") != str(context.get("tenant_id") or ""):
            raise RuntimeContextOwnershipError("不能更改任务的租户范围")
        # Preserve the authenticated original's representation as well as value.
        updates.pop("tenant_id")
    return {**context, **updates}
