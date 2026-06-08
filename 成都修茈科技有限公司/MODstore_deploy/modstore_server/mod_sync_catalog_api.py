"""Mod 库与 XCAGI ``mods/`` 同步的公网 API（挂载在 ``/v1/mod-sync``）。

与已登录工作台调用的 ``POST /api/sync/push``、``POST /api/sync/pull`` 行为一致，
但认证改为修茈账号体系：

- Web 登录态：``Authorization: Bearer <JWT>``；
- 机器/本地同步：``Authorization: Bearer pat_xxx``，且必须包含 ``mod:sync`` scope。

普通用户只能同步自己拥有的 Mod；管理员可同步全部。

另提供 ``GET /v1/mod-sync/mods`` 与 ``GET /v1/mod-sync/export-zip/{mod_id}``：
供本机运行 ``modman remote-deploy`` 从线上库拉 zip 写入本机 ``XCAGI/mods/``（跨机场景）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from modman.repo_config import resolved_xcagi
from modman.store import build_mod_zip_bytes, deploy_to_xcagi, list_mods, pull_from_xcagi
from modstore_server.auth_service import (
    PAT_PREFIX,
    decode_access_token,
    get_user_by_id,
    resolve_pat_identity,
)
from modstore_server.models import User, get_user_mod_ids, user_owns_mod

router = APIRouter(prefix="/v1/mod-sync", tags=["catalog-mod-sync"])


REQUIRED_SCOPE = "mod:sync"


@dataclass(frozen=True)
class SyncAuthContext:
    user: User
    auth_type: str
    scopes: tuple[str, ...] = ()


def _lib() -> Path:
    """与 ``modstore_server.app._lib`` 一致，便于测试 monkeypatch ``load_config`` 生效。"""
    from modstore_server import app as app_module

    return app_module._lib()


class ModSyncDTO(BaseModel):
    """``mod_ids`` 为空或 ``null`` 表示全部符合条件的 Mod。"""

    mod_ids: Optional[List[str]] = Field(
        default=None, description="要同步的 manifest id 列表；省略则全部"
    )


def _normalize_mod_ids(mod_ids: Optional[List[str]]) -> Optional[List[str]]:
    if mod_ids is None:
        return None
    out: list[str] = []
    seen: set[str] = set()
    for x in mod_ids:
        mid = (x or "").strip()
        if not mid:
            continue
        if "/" in mid or "\\" in mid:
            raise HTTPException(400, f"非法 mod id: {mid}")
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out


def _require_mod_sync_auth(authorization: Optional[str]) -> SyncAuthContext:
    raw = (authorization or "").strip()
    if not raw.startswith("Bearer "):
        raise HTTPException(401, "缺少认证凭证，请使用修茈登录 JWT 或 Developer Token")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(401, "缺少认证凭证")

    if token.startswith(PAT_PREFIX):
        ident = resolve_pat_identity(token)
        if not ident:
            raise HTTPException(401, "Developer Token 无效、已吊销或已过期")
        if REQUIRED_SCOPE not in ident.scopes:
            raise HTTPException(403, f"Developer Token 缺少 {REQUIRED_SCOPE} 权限")
        return SyncAuthContext(user=ident.user, auth_type="pat", scopes=ident.scopes)

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(401, "登录凭证无效或已过期")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(401, "登录凭证无效或已过期") from exc
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "用户不存在")
    return SyncAuthContext(user=user, auth_type="jwt")


def _authorized_mod_ids(
    ctx: SyncAuthContext, requested: Optional[List[str]]
) -> Optional[List[str]]:
    """返回可传给 store 层的 mod_ids；``None`` 仅表示管理员全部。"""
    req = _normalize_mod_ids(requested)
    if ctx.user.is_admin:
        return req if req else None

    if not req:
        return sorted(get_user_mod_ids(ctx.user.id))

    for mod_id in req:
        if not user_owns_mod(ctx.user.id, mod_id):
            raise HTTPException(403, f"您无权同步此 Mod: {mod_id}")
    return req


@router.post("/push", summary="库 → XCAGI/mods（账号/PAT）")
def api_v1_mod_sync_push(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    body: ModSyncDTO = Body(default_factory=ModSyncDTO),
):
    auth = _require_mod_sync_auth(authorization)
    from modstore_server import app as app_module

    cfg = app_module._cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        raise HTTPException(
            400, "未配置有效的 XCAGI 根目录（Mod 源码库「路径与同步」或环境变量 XCAGI_ROOT）"
        )
    lib = _lib()
    allowed_ids = _authorized_mod_ids(auth, body.mod_ids)
    if allowed_ids == []:
        return {"ok": True, "deployed": [], "auth_type": auth.auth_type}
    try:
        done = deploy_to_xcagi(allowed_ids, lib, xc, replace=True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "deployed": done, "auth_type": auth.auth_type}


@router.post("/pull", summary="XCAGI/mods → 库（账号/PAT）")
def api_v1_mod_sync_pull(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    body: ModSyncDTO = Body(default_factory=ModSyncDTO),
):
    auth = _require_mod_sync_auth(authorization)
    from modstore_server import app as app_module

    cfg = app_module._cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        raise HTTPException(400, "未配置有效的 XCAGI 根目录")
    lib = _lib()
    allowed_ids = _authorized_mod_ids(auth, body.mod_ids)
    if allowed_ids == []:
        return {"ok": True, "pulled": [], "auth_type": auth.auth_type}
    try:
        done = pull_from_xcagi(allowed_ids, lib, xc, replace=True)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "pulled": done, "auth_type": auth.auth_type}


def _assert_sync_can_read_mod(ctx: SyncAuthContext, mod_id: str) -> str:
    mid = (mod_id or "").strip()
    if not mid or "/" in mid or "\\" in mid:
        raise HTTPException(400, "非法 mod id")
    if not ctx.user.is_admin and not user_owns_mod(ctx.user.id, mid):
        raise HTTPException(403, f"您无权访问此 Mod: {mid}")
    return mid


@router.get("/mods", summary="列出当前账号可同步的 Mod（与 /api/mods 范围一致）")
def api_v1_mod_sync_list_mods(authorization: Optional[str] = Header(None, alias="Authorization")):
    auth = _require_mod_sync_auth(authorization)
    lib = _lib()
    if auth.user.is_admin:
        rows = list_mods(lib)
    else:
        allowed = set(get_user_mod_ids(auth.user.id))
        rows = [r for r in list_mods(lib) if r.get("id") in allowed]
    return {"data": rows}


@router.get("/export-zip/{mod_id}", summary="下载 Mod zip（供本机 modman remote-deploy）")
def api_v1_mod_sync_export_zip(
    mod_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    auth = _require_mod_sync_auth(authorization)
    mid = _assert_sync_can_read_mod(auth, mod_id)
    d = _lib() / mid
    if not d.is_dir():
        raise HTTPException(404, f"Mod 不存在: {mid}")
    buf = build_mod_zip_bytes(d)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{mid}.zip"'},
    )
