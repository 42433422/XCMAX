"""Merge continuation options without changing persisted data ownership."""

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun


class RuntimeContextOwnershipError(ValueError):
    """A continuation attempted to change the task's authenticated data scope."""


CONVERSATION_CONTEXT_FIELDS = (
    "conversation_id",
    "session_id",
    "_conversation_revision",
    "local_user_id",
    "workspace_id",
)


def validate_conversation_context(stored: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in CONVERSATION_CONTEXT_FIELDS:
        if key in incoming and stored.get(key) != incoming[key]:
            raise RuntimeContextOwnershipError("不能更改任务绑定的会话、历史版本或持久用户")


def merge_runtime_context(run: AgentRun, updates: dict[str, Any] | None) -> dict[str, Any]:
    context = dict(run.metadata.get("runtime_context") or {})
    updates = dict(updates or {})
    validate_conversation_context(context, updates)
    for key in (
        *CONVERSATION_CONTEXT_FIELDS,
        "_mod_authorization",
        "_actor_authorization",
        "_tool_approval_scope",
        "_bulk_preview_scope",
        "_bulk_preview_scopes",
        "mutation_policy",
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
