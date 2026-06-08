"""XCAGI sync routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException

from modman.manifest_util import read_manifest
from modman.repo_config import resolved_xcagi
from modman.store import deploy_to_xcagi, iter_mod_dirs, pull_from_xcagi
from modstore_server.api.auth_deps import assert_user_owns_mod, require_user
from modstore_server.api.dto import SyncDTO
from modstore_server.infrastructure import library_paths
from modstore_server.models import User, get_session_factory
from modstore_server.quota_middleware import consume_quota, get_quota, require_quota

router = APIRouter(tags=["sync"])


@router.post("/api/sync/push")
def api_sync_push(body: SyncDTO, user: User = Depends(require_user)):
    cfg = library_paths.cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        raise HTTPException(
            400, "未配置有效的 XCAGI 根目录（Mod 源码库页「路径与同步」或环境变量 XCAGI_ROOT）"
        )
    if not user.is_admin and body.mod_ids:
        for mod_id in body.mod_ids:
            assert_user_owns_mod(user, mod_id)
    enforce_sync_quota = (os.environ.get("MODSTORE_ENFORCE_SYNC_QUOTA") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if enforce_sync_quota:
        sf = get_session_factory()
        with sf() as qdb:
            # 未给用户配置 sync_operations 配额时不阻断同步（避免默认环境误开开关）
            if get_quota(qdb, user.id, "sync_operations") is None:
                enforce_sync_quota = False
            else:
                require_quota(qdb, user.id, "sync_operations", 1)
    lib = library_paths.lib()
    try:
        done = deploy_to_xcagi(body.mod_ids, lib, xc, replace=True)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if enforce_sync_quota:
        sf = get_session_factory()
        with sf() as qdb2:
            consume_quota(qdb2, user.id, "sync_operations", 1)
    return {"ok": True, "deployed": done}


@router.post("/api/sync/pull")
def api_sync_pull(body: SyncDTO, user: User = Depends(require_user)):
    cfg = library_paths.cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        raise HTTPException(400, "未配置有效的 XCAGI 根目录")
    lib = library_paths.lib()
    try:
        done = pull_from_xcagi(body.mod_ids, lib, xc, replace=True)
    except FileNotFoundError as e:
        raise HTTPException(400, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "pulled": done}


@router.get("/api/xcagi/installed-mods")
def api_xcagi_installed_mods():
    cfg = library_paths.cfg()
    xc = resolved_xcagi(cfg)
    if not xc:
        return {
            "ok": False,
            "error": "未配置有效的 XCAGI 根目录（「路径与同步」或环境变量）",
            "mods_path": "",
            "mods": [],
            "primary_mod": None,
            "primary_mod_count": 0,
        }
    mods_dir = (xc / "mods").resolve()
    if not mods_dir.is_dir():
        return {
            "ok": True,
            "mods_path": str(mods_dir),
            "mods": [],
            "note": "XCAGI/mods 目录尚不存在",
            "primary_mod": None,
            "primary_mod_count": 0,
        }
    rows: list[dict] = []
    for d in iter_mod_dirs(mods_dir):
        data, err = read_manifest(d)
        if err or not data:
            rows.append(
                {
                    "id": d.name,
                    "name": "",
                    "version": "",
                    "primary": False,
                    "ok": False,
                    "error": err or "manifest 无效",
                }
            )
            continue
        rows.append(
            {
                "id": str(data.get("id") or d.name).strip() or d.name,
                "name": str(data.get("name") or "").strip(),
                "version": str(data.get("version") or "").strip(),
                "primary": bool(data.get("primary")),
                "ok": True,
            }
        )
    rows.sort(key=lambda r: str(r.get("id") or ""))
    primary_rows = [r for r in rows if r.get("primary") and r.get("ok") is not False]
    primary_mod = primary_rows[0] if len(primary_rows) == 1 else None
    return {
        "ok": True,
        "mods_path": str(mods_dir),
        "mods": rows,
        "primary_mod": primary_mod,
        "primary_mod_count": len(primary_rows),
    }
