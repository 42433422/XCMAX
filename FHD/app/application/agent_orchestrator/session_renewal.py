"""Renew an authenticated session during explicit approval without changing ownership."""

from typing import Any

from app.application.agent_orchestrator.approval_grant import ApprovalGrantError
from app.application.agent_orchestrator.run_models import AgentRun


def renew_approval_session(
    run: AgentRun,
    *,
    principal_id: str,
    authenticated_binding: dict[str, Any] | None,
    authenticated_actor_binding: dict[str, Any] | None = None,
    operation: str = "approval",
) -> None:
    if operation not in {"approval", "resume", "retry"}:
        raise ApprovalGrantError("无效的会话续期操作")
    context = dict(run.metadata.get("runtime_context") or {})
    previous = context.get("_mod_authorization")
    previous_actor = context.get("_actor_authorization")
    if (
        previous_actor is not None
        and authenticated_actor_binding is None
        and previous != authenticated_binding
    ):
        raise ApprovalGrantError("会话续期缺少当前账号身份，需要重新登录")
    updated = dict(context)
    for key, old, new, fields in (
        (
            "_mod_authorization",
            previous,
            authenticated_binding,
            ("user_id", "mod_id", "account_tenant_id", "account_role"),
        ),
        (
            "_actor_authorization",
            previous_actor,
            authenticated_actor_binding,
            ("user_id", "tenant_id", "execution_tenant_id", "role", "tier", "mod_id"),
        ),
    ):
        if key == "_actor_authorization" and new is None:
            continue
        if old is None and new is None:
            continue
        if not isinstance(old, dict) or not isinstance(new, dict):
            raise ApprovalGrantError("任务授权不完整，需要人工核对")
        if (
            run.user_id != principal_id
            or new.get("user_id") != principal_id
            or any(
                not isinstance(old.get(field), str) or old[field] != new.get(field)
                for field in fields
            )
            or (key == "_mod_authorization" and not old.get("mod_id"))
        ):
            raise ApprovalGrantError("不能通过会话续期更改任务账号范围")
        if any(
            type(binding.get("session_row_id")) is not int or binding["session_row_id"] <= 0
            for binding in (old, new)
        ):
            raise ApprovalGrantError("任务会话绑定无效")
        updated[key] = dict(new)
    if authenticated_actor_binding is not None:
        from app.infrastructure.auth.agent_mod_scope import validate_actor_context

        # Validate the new live session, not the expired session it replaces.
        # This also proves that actor and Mod bindings refer to the same row.
        if validate_actor_context(updated) is not None:
            raise ApprovalGrantError("新的登录会话授权无效，请重新登录")
    if updated == context:
        return
    expected = {"approval": {"waiting_user"}, "resume": {"paused"}, "retry": {"failed", "blocked"}}
    from app.application.agent_orchestrator.run_lifecycle import safe_continuation_error

    unsettled = any(step.status == "running" for step in run.steps)
    if run.status not in expected[operation] or (
        unsettled and (operation != "retry" or safe_continuation_error(run))
    ):
        raise ApprovalGrantError("任务执行状态不允许更新会话")
    run.metadata["runtime_context"] = updated
    run.add_event(
        "task.session_renewed",
        "更新了同一账号范围的登录会话",
        {"requested_by": principal_id},
    )
