"""Authenticated product hint lookup used by compatibility routes."""

from fastapi import HTTPException, Request


def resolve_authenticated_product_hints(request: Request, hints: list[str]) -> dict:
    from app.application.agent_orchestrator.task_mod_scope import (
        TaskModScopeError,
        capture_task_mod_scope,
    )
    from app.application.product_name_hints import resolve_product_name_hints
    from app.infrastructure.auth.dependencies import get_logged_in_user
    from app.infrastructure.request_context import reset_current_request, set_current_request

    user = get_logged_in_user(request)
    tenant = getattr(user, "tenant_id", None)
    if type(tenant) is not int or tenant < 1:
        raise HTTPException(403, "登录账号缺少租户归属")
    token = set_current_request(request)
    try:
        capture_task_mod_scope(str(user.id), str(tenant))
        return {"success": True, "data": resolve_product_name_hints(tenant, hints)}
    except TaskModScopeError as exc:
        raise HTTPException(403, str(exc)) from exc
    finally:
        reset_current_request(token)
