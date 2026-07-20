"""工作流定义 REST API 路由。

端点前缀：``/api/workflow-definitions``。

提供：
- 定义 CRUD：``POST /`` / ``GET /{id}`` / ``GET /`` / ``PUT /{id}`` / ``DELETE /{id}``
- 启停：``POST /{id}/activate`` / ``POST /{id}/deactivate``
- 运行管理：``POST /{id}/runs`` / ``GET /{id}/runs`` / ``GET /runs/{run_id}`` /
  ``POST /runs/{run_id}/cancel``

参考 ``app/fastapi_routes/rbac.py`` 的路由风格：使用 ``require_permission`` 依赖、
``AppError`` 转 JSONResponse 统一错误处理。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.application.workflow_definition_app_service import (
    get_workflow_definition_app_service,
)
from app.db.models.workflow import (
    WorkflowTriggerSource,
    WorkflowTriggerType,
)
from app.errors import AppError
from app.infrastructure.auth.dependencies import require_permission
from app.infrastructure.auth.tenant_context import resolve_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow-definitions", tags=["workflow-definitions"])

# 复用全局 RBAC：要求登录用户具备 admin.manage_users 权限
# （工作流定义是平台级配置，未引入独立 permission code，避免 RBAC 扩张）
_require_admin = require_permission("admin.manage_users")


def _handle_app_error(err: AppError) -> JSONResponse:
    return JSONResponse(
        {"success": False, "message": err.message, "error_code": err.code.value},
        status_code=err.status_code,
    )


# ── Pydantic 模型 ────────────────────────────────────────────


class WorkflowDefinitionCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None
    trigger_type: str = Field(default=WorkflowTriggerType.MANUAL.value)
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    created_by: int | None = None


class WorkflowDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_config: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    is_active: bool | None = None


class WorkflowRunStart(BaseModel):
    triggered_by: str = Field(default=WorkflowTriggerSource.USER.value)
    trigger_payload: dict[str, Any] = Field(default_factory=dict)


# ── 定义 CRUD ────────────────────────────────────────────────


@router.post("")
def create_definition(
    body: WorkflowDefinitionCreate,
    request: Request,
    _user=Depends(_require_admin),
):
    """创建工作流定义。"""
    try:
        data = get_workflow_definition_app_service().create_definition(
            tenant_id=resolve_tenant_id(request),
            name=body.name,
            description=body.description,
            trigger_type=body.trigger_type,
            trigger_config=body.trigger_config,
            nodes=body.nodes,
            edges=body.edges,
            created_by=body.created_by,
        )
        return JSONResponse({"success": True, "data": data}, status_code=201)
    except AppError as exc:
        return _handle_app_error(exc)


@router.get("")
def list_definitions(
    request: Request,
    _user=Depends(_require_admin),
    active_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
):
    """列出工作流定义（可按租户与启用状态过滤）。"""
    tenant_id = resolve_tenant_id(request)
    data = get_workflow_definition_app_service().list_definitions(
        tenant_id=tenant_id,
        active_only=active_only,
        limit=limit,
    )
    return {"success": True, "data": data}


@router.get("/{definition_id}")
def get_definition(definition_id: int, _user=Depends(_require_admin)):
    try:
        return {"success": True, "data": get_workflow_definition_app_service().get_definition(definition_id)}
    except AppError as exc:
        return _handle_app_error(exc)


@router.put("/{definition_id}")
def update_definition(
    definition_id: int,
    body: WorkflowDefinitionUpdate,
    _user=Depends(_require_admin),
):
    """更新工作流定义；version 自增。"""
    try:
        data = get_workflow_definition_app_service().update_definition(
            definition_id,
            name=body.name,
            description=body.description,
            trigger_type=body.trigger_type,
            trigger_config=body.trigger_config,
            nodes=body.nodes,
            edges=body.edges,
            is_active=body.is_active,
        )
        return {"success": True, "data": data}
    except AppError as exc:
        return _handle_app_error(exc)


@router.delete("/{definition_id}")
def delete_definition(definition_id: int, _user=Depends(_require_admin)):
    try:
        get_workflow_definition_app_service().delete_definition(definition_id)
        return {"success": True, "message": "工作流定义已删除"}
    except AppError as exc:
        return _handle_app_error(exc)


@router.post("/{definition_id}/activate")
def activate_definition(definition_id: int, _user=Depends(_require_admin)):
    try:
        return {"success": True, "data": get_workflow_definition_app_service().activate_definition(definition_id)}
    except AppError as exc:
        return _handle_app_error(exc)


@router.post("/{definition_id}/deactivate")
def deactivate_definition(definition_id: int, _user=Depends(_require_admin)):
    try:
        return {"success": True, "data": get_workflow_definition_app_service().deactivate_definition(definition_id)}
    except AppError as exc:
        return _handle_app_error(exc)


# ── 运行管理 ─────────────────────────────────────────────────


@router.post("/{definition_id}/runs")
def start_run(
    definition_id: int,
    body: WorkflowRunStart,
    _user=Depends(_require_admin),
):
    """启动一次工作流运行。"""
    try:
        data = get_workflow_definition_app_service().start_run(
            definition_id,
            triggered_by=body.triggered_by,
            trigger_payload=body.trigger_payload,
        )
        return JSONResponse({"success": True, "data": data}, status_code=201)
    except AppError as exc:
        return _handle_app_error(exc)


@router.get("/{definition_id}/runs")
def list_runs(
    definition_id: int,
    _user=Depends(_require_admin),
    limit: int = Query(default=20, ge=1, le=200),
):
    data = get_workflow_definition_app_service().list_runs(definition_id, limit=limit)
    return {"success": True, "data": data}


@router.get("/runs/{run_id}")
def get_run(run_id: int, _user=Depends(_require_admin)):
    try:
        return {"success": True, "data": get_workflow_definition_app_service().get_run(run_id)}
    except AppError as exc:
        return _handle_app_error(exc)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, _user=Depends(_require_admin)):
    try:
        return {"success": True, "data": get_workflow_definition_app_service().cancel_run(run_id)}
    except AppError as exc:
        return _handle_app_error(exc)
