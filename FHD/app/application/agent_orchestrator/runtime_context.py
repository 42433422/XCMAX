"""Merge continuation options without changing persisted data ownership."""

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun


class RuntimeContextOwnershipError(ValueError):
    """A continuation attempted to change the task's authenticated data scope."""


def merge_runtime_context(run: AgentRun, updates: dict[str, Any] | None) -> dict[str, Any]:
    context = dict(run.metadata.get("runtime_context") or {})
    updates = dict(updates or {})
    for key in (
        "_mod_authorization",
        "_actor_authorization",
        "mod_id",
        "active_mod_id",
        "user_id",
        "actor_id",
        "tenant_id",
        "business_action_id",
        "task_id",
    ):
        if key not in updates:
            continue
        original, requested = context.get(key), updates.pop(key)
        matches = (
            original == requested
            if key.startswith("_")
            else str(original or "") == str(requested or "")
        )
        if not matches:
            raise RuntimeContextOwnershipError("不能更改任务的身份、租户或 Mod 授权范围")
    return {**context, **updates}
