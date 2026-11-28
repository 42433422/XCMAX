"""工作区偏好 API — 租户级跨设备同步。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from anyio import CapacityLimiter
from anyio.lowlevel import RunVar
from anyio.to_thread import run_sync
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.application.tenant_workspace_prefs import (
    ENTERPRISE_LEVEL_KEY,
    ENTERPRISE_MODEL_KEY,
    WorkspacePrefsVersionConflict,
    bind_selected_industry_for_user,
    enterprise_intelligence_scope,
    get_workspace_prefs,
    patch_workspace_prefs,
    resolve_workspace_owner_id,
    workspace_intelligence_level,
    workspace_model_choice,
    workspace_prefs_revision,
)
from app.infrastructure.auth.dependencies import (
    get_logged_in_user,
    resolve_session_user,
    session_id_from_request,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
_PREFS_WRITES: RunVar[CapacityLimiter] = RunVar("workspace_prefs_writes")
_PREFS_JOBS: set[asyncio.Task[Any]] = set()


class WorkspacePrefsPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Optional during the rolling client upgrade; clients that supply it get
    # explicit compare-and-swap protection against another device's changes.
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    expected_owner_id: str | None = Field(default=None, min_length=1, max_length=160)

    selected_industry_id: str | None = Field(default=None, max_length=32)
    industry_mod_id: str | None = None
    workflow_ai_employees: dict[str, bool] | None = None
    product_flow_completed: bool | None = None
    host_pack_acknowledged: bool | None = None


class EnterprisePreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_owner_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0, strict=True)


class IntelligenceUpdate(EnterprisePreferenceUpdate):
    level: int = Field(ge=1, le=6, strict=True)


class ModelUpdate(EnterprisePreferenceUpdate):
    provider: str | None = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    model: str | None = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_./:@+\-]{0,255}$")


def _enterprise_scope(request: Request) -> tuple[Any, str, bool]:
    actor = get_logged_in_user(request)
    scope = enterprise_intelligence_scope(actor)
    if scope is None:
        raise HTTPException(status_code=403, detail="缺少有效的企业身份")
    return actor, *scope


def _intelligence_snapshot(owner: str, editable: bool, prefs: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner_id": owner,
        "editable": editable,
        "level": workspace_intelligence_level(prefs),
        "revision": workspace_prefs_revision(prefs),
    }


@router.get("/intelligence")
def get_enterprise_intelligence(request: Request, response: Response):
    _, owner, editable = _enterprise_scope(request)
    response.headers["Cache-Control"] = "private, no-store"
    return _intelligence_snapshot(owner, editable, get_workspace_prefs(owner, strict=True))


@router.put("/intelligence")
def set_enterprise_intelligence(body: IntelligenceUpdate, request: Request):
    _, owner, editable = _enterprise_scope(request)
    if not editable:
        raise HTTPException(status_code=403, detail="仅本企业主账号可修改智能等级")
    if body.expected_owner_id != owner:
        raise HTTPException(status_code=409, detail="企业登录范围已变化，请重新读取智能等级")
    try:
        prefs = patch_workspace_prefs(
            owner, {ENTERPRISE_LEVEL_KEY: body.level}, expected_revision=body.expected_revision
        )
    except WorkspacePrefsVersionConflict as exc:
        raise HTTPException(status_code=409, detail="企业设置已变化，请重新读取智能等级") from exc
    return _intelligence_snapshot(owner, editable, prefs)


def _model_snapshot(owner: str, editable: bool, prefs: dict[str, Any]) -> dict[str, Any]:
    provider, model, _ = workspace_model_choice(prefs) or (None, None, None)
    return {
        "owner_id": owner,
        "editable": editable,
        "provider": provider,
        "model": model,
        "revision": workspace_prefs_revision(prefs),
    }


@router.get("/model")
def get_enterprise_model(request: Request, response: Response):
    _, owner, editable = _enterprise_scope(request)
    response.headers["Cache-Control"] = "private, no-store"
    editable = editable and not os.environ.get("XCAGI_AGENT_RUNTIME_CONFIG", "").strip()
    return _model_snapshot(owner, editable, get_workspace_prefs(owner, strict=True))


@router.put("/model")
def set_enterprise_model(body: ModelUpdate, request: Request):
    from app.application.agent_runtime.configuration import (
        RuntimeSetupError,
        validate_account_model_choice,
    )
    from app.application.modstore_conversation_app import request_model_scope

    actor, owner, editable = _enterprise_scope(request)
    if not editable:
        raise HTTPException(403, "仅本企业主账号可修改默认模型")
    if os.environ.get("XCAGI_AGENT_RUNTIME_CONFIG", "").strip():
        raise HTTPException(403, "模型由部署配置管理")
    conflict = HTTPException(409, "企业设置已变化，请重新读取默认模型")
    if body.expected_owner_id != owner or body.expected_revision != workspace_prefs_revision(
        get_workspace_prefs(owner, strict=True)
    ):
        raise conflict
    if (body.provider is None) != (body.model is None):
        raise HTTPException(422, "请同时选择供应商和模型")
    choice = None
    if body.provider and body.model:
        try:
            with request_model_scope(request):
                key_source = validate_account_model_choice(
                    str(actor.id), (body.provider, body.model)
                )
        except RuntimeSetupError as exc:
            status = 503 if exc.code == "runtime_platform_unavailable" else 422
            raise HTTPException(status, {"code": exc.code, "message": exc.public_message}) from None
        choice = {"provider": body.provider, "model": body.model, "key_source": key_source}
        current, current_owner, editable = _enterprise_scope(request)
        if current.id != actor.id or current_owner != owner or not editable:
            raise conflict
    try:
        prefs = patch_workspace_prefs(
            owner, {ENTERPRISE_MODEL_KEY: choice}, expected_revision=body.expected_revision
        )
    except WorkspacePrefsVersionConflict:
        raise conflict from None
    return _model_snapshot(owner, True, prefs)


async def _try_grant_market_entitlements(
    session_id: str,
    selected_industry_id: str,
) -> dict[str, Any] | None:
    industry_id = str(selected_industry_id or "").strip()
    if not industry_id:
        return None
    try:
        from app.fastapi_routes.market_account import (
            grant_market_enterprise_entitlements_for_session,
        )

        result = await grant_market_enterprise_entitlements_for_session(session_id, industry_id)
    except RECOVERABLE_ERRORS as exc:
        logger.exception("workspace prefs market entitlement sync failed")
        result = {"success": False, "message": str(exc)}
    if not result.get("success"):
        logger.warning(
            "workspace prefs saved while market entitlement sync failed: industry=%s message=%s",
            industry_id,
            result.get("message"),
        )
    return result


@router.get("/prefs")
def get_workspace_prefs_endpoint(request: Request):
    """读取当前登录用户所属租户/会话的工作区偏好。"""
    try:
        user = resolve_session_user(request)
        if user is None:
            return {"success": True, "data": {}, "owner_id": None, "revision": 0}
        owner_id = resolve_workspace_owner_id(request, user)
        prefs = get_workspace_prefs(owner_id) if owner_id else {}
        return {
            "success": True,
            "data": prefs,
            "owner_id": owner_id,
            "revision": workspace_prefs_revision(prefs),
        }
    except RECOVERABLE_ERRORS:
        logger.exception("get_workspace_prefs_endpoint failed")
        return {"success": True, "data": {}, "owner_id": None}


def _patch_local_prefs(body: WorkspacePrefsPatch, request: Request):
    user = get_logged_in_user(request)
    owner_id = resolve_workspace_owner_id(request, user)
    if not owner_id:
        raise HTTPException(status_code=400, detail="无法解析工作区归属，请先完成企业登录")
    if body.expected_owner_id is not None and body.expected_owner_id != owner_id:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "workspace_prefs_owner_changed"},
        )

    partial: dict[str, Any] = body.model_dump(
        exclude_none=True, exclude={"expected_revision", "expected_owner_id"}
    )
    selected_industry_id = str(partial.get("selected_industry_id") or "").strip()
    if body.expected_revision is None:
        prefs = patch_workspace_prefs(owner_id, partial)
    else:
        prefs = patch_workspace_prefs(owner_id, partial, expected_revision=body.expected_revision)
    if selected_industry_id:
        industry_mod_id = str(partial.get("industry_mod_id") or "").strip()
        if body.expected_revision is not None:
            # Keep the CAS write a single preference revision. Legacy callers
            # retain their prior industry-binding behavior during rollout.
            bind_selected_industry_for_user(
                user,
                selected_industry_id,
                industry_mod_id=industry_mod_id,
                owner_id=owner_id,
                persist_workspace_prefs=False,
            )
        else:
            prefs = (
                bind_selected_industry_for_user(
                    user, selected_industry_id, industry_mod_id=industry_mod_id, owner_id=owner_id
                )
                or prefs
            )
    return prefs, owner_id, selected_industry_id, session_id_from_request(request)


async def _run_local_write(body, request, limiter, token):
    try:
        return await run_sync(_patch_local_prefs, body, request)
    finally:
        limiter.release_on_behalf_of(token)


def _forget_local_write(job):
    _PREFS_JOBS.discard(job)
    if not job.cancelled():
        job.exception()  # Observe errors even when the requesting connection has gone away.


@router.patch("/prefs")
async def patch_workspace_prefs_endpoint(body: WorkspacePrefsPatch, request: Request):
    """合并更新工作区偏好（跨设备同步）。"""
    try:
        limiter = _PREFS_WRITES.get(None)
        if limiter is None:
            limiter = CapacityLimiter(1)  # Preserve per-loop write order without blocking it.
            _PREFS_WRITES.set(limiter)
        token = asyncio.current_task()
        await limiter.acquire()
        job = asyncio.create_task(_run_local_write(body, request, limiter, token))
        _PREFS_JOBS.add(job)
        job.add_done_callback(_forget_local_write)
        prefs, owner_id, selected_industry_id, session_id = await asyncio.shield(job)
        market_entitlements = await _try_grant_market_entitlements(
            session_id,
            selected_industry_id,
        )
        return {
            "success": True,
            "data": prefs,
            "owner_id": owner_id,
            "revision": workspace_prefs_revision(prefs),
            "market_entitlements": market_entitlements,
        }
    except HTTPException:
        raise
    except WorkspacePrefsVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "workspace_prefs_version_conflict", "message": str(exc)},
        ) from exc
    except RECOVERABLE_ERRORS as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
