"""Debug / sandbox / XCAGI proxy routes."""

from __future__ import annotations

import os
import shutil
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException

from modman.manifest_util import read_manifest, write_manifest
from modman.store import iter_mod_dirs
from modstore_server.api.auth_deps import assert_user_owns_mod, require_user
from modstore_server.api.dto import FocusPrimaryDTO, SandboxDTO
from modstore_server.infrastructure import library_paths
from modstore_server.models import User

router = APIRouter(tags=["debug"])


@router.post("/api/debug/sandbox")
def api_debug_sandbox(body: SandboxDTO, user: User = Depends(require_user)):
    assert_user_owns_mod(user, body.mod_id)
    mod_id = body.mod_id.strip()
    try:
        library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    lib = library_paths.lib()
    src = (lib / mod_id).resolve()
    root = library_paths.project_root()
    sand = root / "debug_sandbox"
    sand.mkdir(parents=True, exist_ok=True)
    session = uuid.uuid4().hex[:12]
    mods_root = (sand / session / "mods").resolve()
    mods_root.mkdir(parents=True, exist_ok=True)
    dst = mods_root / mod_id
    if dst.exists():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    try:
        if body.mode == "symlink":
            try:
                os.symlink(src, dst, target_is_directory=True)
            except OSError:
                shutil.copytree(src, dst)
        else:
            shutil.copytree(src, dst)
    except OSError as e:
        raise HTTPException(500, f"创建沙箱失败: {e}") from e
    path_str = str(mods_root)
    library_paths.save_state(
        {
            "last_sandbox_mods_root": path_str,
            "last_sandbox_mod_id": mod_id,
            "last_sandbox_session": session,
        }
    )
    return {
        "ok": True,
        "session": session,
        "mods_root": path_str,
        "mod_id": mod_id,
        "xcagi_mods_root_env": f"XCAGI_MODS_ROOT={path_str}",
        "hint": "重启 XCAGI 后端后，仅会从此目录加载 Mod。",
    }


@router.post("/api/debug/focus-primary")
def api_debug_focus_primary(body: FocusPrimaryDTO, user: User = Depends(require_user)):
    assert_user_owns_mod(user, body.mod_id)
    target = body.mod_id.strip()
    try:
        library_paths.mod_dir(target)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    lib = library_paths.lib()
    updated: list[str] = []
    for d in iter_mod_dirs(lib):
        data, err = read_manifest(d)
        if err or not data:
            continue
        mid = (data.get("id") or d.name).strip()
        data["primary"] = mid == target
        try:
            write_manifest(d, data)
            updated.append(mid)
        except OSError as e:
            raise HTTPException(500, f"写入失败 {d.name}: {e}") from e
    library_paths.save_state({"focus_mod_id": target})
    return {"ok": True, "primary_mod_id": target, "updated_manifests": updated}


@router.get("/api/fhd/db-tokens/status")
def api_fhd_db_tokens_status():
    cfg = library_paths.cfg()
    base = library_paths.resolved_xcagi_backend_url(cfg).rstrip("/")
    url = f"{base}/api/fhd/db-tokens/status"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
    except httpx.RequestError as e:
        return {
            "ok": False,
            "error": str(e),
            "url": url,
            "data": None,
        }
    try:
        payload = r.json()
    except ValueError:
        payload = {"raw": r.text[:2000]}
    ok = 200 <= r.status_code < 300
    return {
        "ok": ok,
        "status_code": r.status_code,
        "url": url,
        "data": payload if ok else None,
        "error": None if ok else (r.text or str(payload))[:500],
    }


@router.get("/api/xcagi/loading-status")
def api_xcagi_loading_status():
    cfg = library_paths.cfg()
    base = library_paths.resolved_xcagi_backend_url(cfg)
    url = f"{base}/api/mods/loading-status"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
    except httpx.RequestError as e:
        return {
            "ok": False,
            "error": str(e),
            "url": url,
            "data": None,
        }
    try:
        payload = r.json()
    except ValueError:
        payload = {"raw": r.text[:2000]}
    ok = 200 <= r.status_code < 300
    return {
        "ok": ok,
        "status_code": r.status_code,
        "url": url,
        "data": payload,
    }
