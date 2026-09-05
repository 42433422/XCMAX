"""Authenticated template creation on the default application route graph."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.domains.system.agent_handlers import run_document_template_agent
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.tenant_scope import tenant_scope

router = APIRouter()


@router.post("/api/templates/create", summary="创建当前租户的模板")
def templates_create(
    request: Request,
    body: dict = Body(default_factory=dict),
    user: Any = Depends(get_logged_in_user),
) -> JSONResponse:
    tenant_id = getattr(user, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=403, detail="缺少租户上下文，无法创建模板")
    # The account is the source of truth even if a caller supplies identity
    # fields or the caller's surrounding context carries a different tenant.
    with tenant_scope(int(tenant_id)):
        data, code = run_document_template_agent(
            request=request,
            body=body,
            action="create",
            route_path="/api/templates/create",
            authenticated_actor_id=str(user.id),
        )
    return JSONResponse(data, status_code=code)
