"""本机文件（只读）授权 API。

仅桌面端可用：授权记录按当前登录用户与租户隔离，撤销后立即停止读取。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.application.local_file_access import (
    LocalFileAccessError,
    create_grant,
    detect_full_disk_access,
    list_grants,
    request_sync,
    revoke_grant,
    status_snapshot,
)
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.deployment import is_desktop_mode
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/local-files", tags=["local-file-access"])


class GrantCreate(BaseModel):
    mode: str = Field(default="folder", max_length=16)
    root_path: str = Field(min_length=1, max_length=2000)
    device_id: str = Field(default="", max_length=128)


def _require_actor(request: Request) -> tuple[int, int]:
    if not is_desktop_mode():
        raise HTTPException(status_code=403, detail="本机文件读取仅在桌面端可用")
    user = get_logged_in_user(request)
    owner_id = getattr(user, "id", None)
    if owner_id is None:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        tenant = int(tenant_id_for_write())
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(status_code=403, detail="缺少租户上下文") from exc
    return int(owner_id), tenant


def _fail(exc: LocalFileAccessError) -> HTTPException:
    status = 404 if exc.code.endswith("not_found") else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.get("/status")
def local_file_status(request: Request) -> dict[str, Any]:
    owner_id, tenant = _require_actor(request)
    return {
        "success": True,
        "data": {
            "desktop": True,
            "full_disk_access": detect_full_disk_access(),
            "grants": list_grants(owner_id=owner_id, tenant=tenant),
        },
    }


@router.get("/grants")
def local_file_grants(request: Request) -> dict[str, Any]:
    owner_id, tenant = _require_actor(request)
    return {"success": True, "data": list_grants(owner_id=owner_id, tenant=tenant)}


@router.post("/grants")
def local_file_create_grant(body: GrantCreate, request: Request) -> dict[str, Any]:
    owner_id, tenant = _require_actor(request)
    try:
        grant = create_grant(
            owner_id=owner_id,
            tenant=tenant,
            mode=body.mode,
            root_path=body.root_path,
            device_id=body.device_id,
        )
    except LocalFileAccessError as exc:
        raise _fail(exc) from exc
    request_sync(grant["id"], owner_id, tenant)
    return {"success": True, "data": grant}


@router.post("/grants/{grant_id}/revoke")
def local_file_revoke(grant_id: int, request: Request) -> dict[str, Any]:
    owner_id, tenant = _require_actor(request)
    try:
        grant = revoke_grant(owner_id=owner_id, tenant=tenant, grant_id=grant_id)
    except LocalFileAccessError as exc:
        raise _fail(exc) from exc
    return {"success": True, "data": grant}


@router.post("/grants/{grant_id}/sync")
def local_file_sync(grant_id: int, request: Request) -> dict[str, Any]:
    owner_id, tenant = _require_actor(request)
    from app.application.local_file_access import get_grant

    try:
        grant = get_grant(owner_id=owner_id, tenant=tenant, grant_id=grant_id)
    except LocalFileAccessError as exc:
        raise _fail(exc) from exc
    if not grant.is_active:
        raise HTTPException(status_code=409, detail="授权已撤销，不能重新同步")
    queued = request_sync(grant_id, owner_id, tenant)
    return {"success": True, "data": {"queued": queued, **status_snapshot(grant_id, owner_id, tenant)}}


@router.get("/grants/{grant_id}")
def local_file_grant_detail(grant_id: int, request: Request) -> dict[str, Any]:
    owner_id, tenant = _require_actor(request)
    try:
        snapshot = status_snapshot(grant_id, owner_id, tenant)
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not snapshot:
        raise HTTPException(status_code=404, detail="授权不存在或不属于当前账号")
    return {"success": True, "data": snapshot}
