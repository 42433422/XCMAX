"""Renew an authenticated session during explicit approval without changing ownership."""

from typing import Any

from app.application.agent_orchestrator.approval_grant import ApprovalGrantError
from app.application.agent_orchestrator.run_models import AgentRun


def renew_approval_session(
    run: AgentRun, *, principal_id: str, authenticated_binding: dict[str, Any] | None
) -> None:
    context = dict(run.metadata.get("runtime_context") or {})
    previous = context.get("_mod_authorization")
    if not previous and not authenticated_binding:
        return
    if not isinstance(previous, dict) or not isinstance(authenticated_binding, dict):
        raise ApprovalGrantError("任务授权不完整，需要人工核对")
    identity_fields = ("user_id", "mod_id", "account_tenant_id", "account_role")
    if (
        run.user_id != principal_id
        or authenticated_binding.get("user_id") != principal_id
        or any(
            not isinstance(previous.get(key), str)
            or previous[key] != authenticated_binding.get(key)
            for key in identity_fields
        )
        or not previous.get("mod_id")
    ):
        raise ApprovalGrantError("不能通过会话续期更改任务账号范围")
    for binding in (previous, authenticated_binding):
        row_id = binding.get("session_row_id")
        if type(row_id) is not int or row_id <= 0:
            raise ApprovalGrantError("任务会话绑定无效")
    if previous == authenticated_binding:
        return
    if run.status != "waiting_user" or any(step.status == "running" for step in run.steps):
        raise ApprovalGrantError("任务执行状态不允许更新会话")
    context["_mod_authorization"] = dict(authenticated_binding)
    run.metadata["runtime_context"] = context
    run.add_event(
        "task.session_renewed",
        "确认步骤时更新了同一账号范围的登录会话",
        {"requested_by": principal_id},
    )
