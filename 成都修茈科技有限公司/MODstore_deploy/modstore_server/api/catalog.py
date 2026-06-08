"""Mod library CRUD and shell UI routes."""

from __future__ import annotations

import io
import os
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

from modman.industry_presets import apply_industry_to_mod_dir
from modman.manifest_util import (
    folder_name_must_match_id,
    read_manifest,
    save_manifest_validated,
    validate_manifest_dict,
)
from modman.scaffold import create_mod
from modman.store import import_zip, list_mod_relative_files, list_mods, remove_mod_by_manifest_id
from modstore_server.api.auth_deps import (
    assert_user_owns_mod,
    get_optional_user,
    require_user,
)
from modstore_server.api.dto import CreateModDTO, ManifestPutDTO, ModFilePutDTO
from modstore_server.application.catalog import CatalogShellService
from modstore_server.file_safe import read_text_file, resolve_under_mod, write_text_file
from modstore_server.infrastructure import library_paths
from modstore_server.models import (
    User,
    add_user_mod,
    get_session_factory,
    get_user_mod_ids,
    remove_user_mod,
)

router = APIRouter(tags=["mods"])


def _list_row_disk_folder(row: dict) -> str:
    """与 modman 库目录名一致；用于与 user_mods.mod_id（登记时多为目录名）对齐。"""
    raw = str(row.get("path") or "").strip().replace("\\", "/").rstrip("/")
    if raw:
        seg = raw.split("/")[-1]
        if seg:
            return seg
    return str(row.get("id") or "").strip()


@router.get("/api/mods")
def api_list_mods(response: Response, user: Optional[User] = Depends(get_optional_user)):
    lib = library_paths.lib()
    if user is None:
        rows = []
    elif user.is_admin:
        rows = list_mods(lib)
    else:
        user_mod_ids = set(get_user_mod_ids(user.id))
        all_rows = list_mods(lib)
        rows = [
            r
            for r in all_rows
            if str(r.get("id") or "").strip() in user_mod_ids
            or _list_row_disk_folder(r) in user_mod_ids
        ]
    # 避免 CDN/浏览器缓存「删库后仍显示旧列表」；与前端 listMods(cacheBust) 互补
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return {"data": rows}


@router.get("/api/mods/shell-ui")
def api_mods_shell_ui(mod_id: str = ""):
    return CatalogShellService.mods_shell_ui_payload(library_paths.lib(), mod_id)


@router.get("/api/mods/{mod_id}")
def api_get_mod(mod_id: str, user: User = Depends(require_user)):
    assert_user_owns_mod(user, mod_id)
    try:
        d = library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    data, err = read_manifest(d)
    if err or not data:
        raise HTTPException(400, err or "manifest 无效")
    ve = validate_manifest_dict(data)
    fn = folder_name_must_match_id(d, data)
    if fn:
        ve = list(ve) + [fn]
    files = list_mod_relative_files(d)
    from modstore_server.mod_scaffold_runner import analyze_mod_employee_readiness

    sf = get_session_factory()
    with sf() as db:
        employee_readiness = analyze_mod_employee_readiness(db, user, d)
    return {
        "id": mod_id,
        "manifest": data,
        "validation_ok": len(ve) == 0,
        "warnings": ve,
        "files": files,
        "employee_readiness": employee_readiness,
    }


@router.put("/api/mods/{mod_id}/manifest")
def api_put_manifest(mod_id: str, body: ManifestPutDTO, user: User = Depends(require_user)):
    assert_user_owns_mod(user, mod_id)
    try:
        d = library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    try:
        warnings = save_manifest_validated(d, body.manifest)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "warnings": warnings}


@router.get("/api/mods/{mod_id}/file")
def api_get_mod_file(mod_id: str, path: str, user: User = Depends(require_user)):
    assert_user_owns_mod(user, mod_id)
    try:
        d = library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    try:
        p = resolve_under_mod(d, path)
        text = read_text_file(p)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"path": path.replace("\\", "/").lstrip("/"), "content": text}


@router.put("/api/mods/{mod_id}/file")
def api_put_mod_file(mod_id: str, body: ModFilePutDTO, user: User = Depends(require_user)):
    assert_user_owns_mod(user, mod_id)
    try:
        d = library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    try:
        p = resolve_under_mod(d, body.path)
        write_text_file(p, body.content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    manifest_warnings: List[str] = []
    if p.name == "manifest.json" and p.parent.resolve() == d.resolve():
        data, err = read_manifest(d)
        if data and not err:
            manifest_warnings = validate_manifest_dict(data)
            fn = folder_name_must_match_id(d, data)
            if fn:
                manifest_warnings = list(manifest_warnings) + [fn]
    return {"ok": True, "manifest_warnings": manifest_warnings}


@router.post("/api/mods/create")
def api_create_mod(body: CreateModDTO, user: User = Depends(require_user)):
    mid = body.mod_id.strip().lower().replace(" ", "-")
    try:
        dest = create_mod(mid, body.display_name.strip(), library_paths.lib())
        apply_industry_to_mod_dir(dest, (body.industry_id or "通用").strip())
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    add_user_mod(user.id, mid)
    return {
        "ok": True,
        "path": str(dest),
        "id": mid,
        "industry_id": (body.industry_id or "通用").strip(),
    }


@router.delete("/api/mods/{mod_id}")
def api_delete_mod(mod_id: str, user: User = Depends(require_user)):
    mid = mod_id.strip()
    assert_user_owns_mod(user, mid)
    try:
        remove_mod_by_manifest_id(library_paths.lib(), mid)
    except FileNotFoundError:
        raise HTTPException(404, "不存在") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    remove_user_mod(user.id, mid)
    return {"ok": True}


@router.post("/api/mods/import")
async def api_import_mod(
    file: UploadFile = File(...), replace: bool = True, user: User = Depends(require_user)
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "请上传 .zip")
    raw = await file.read()
    max_bytes = int(os.environ.get("MODSTORE_CATALOG_UPLOAD_MAX_BYTES", str(80 * 1024 * 1024)))
    if len(raw) > max_bytes:
        raise HTTPException(400, f"文件过大（>{max_bytes // 1024 // 1024}MB）")
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)
    try:
        dest = import_zip(tmp_path, library_paths.lib(), replace=replace)
    except (ValueError, FileExistsError) as e:
        raise HTTPException(400, str(e)) from e
    finally:
        tmp_path.unlink(missing_ok=True)
    add_user_mod(user.id, dest.name)
    return {"ok": True, "id": dest.name, "path": str(dest)}


@router.get("/api/mods/{mod_id}/export")
def api_export_mod(mod_id: str, user: User = Depends(require_user)):
    assert_user_owns_mod(user, mod_id)
    try:
        d = library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in d.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(d).as_posix())
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{mod_id}.zip"'},
    )
