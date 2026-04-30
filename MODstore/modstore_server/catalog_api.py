"""公网 Catalog 只读/上传 API（挂载在 MODstore 服务 /v1）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile

from modman.employee_sandbox import (
    assert_employee_sandbox_passes_for_catalog_zip,
    catalog_require_employee_sandbox,
    catalog_sandbox_probe_http,
)
from modman.repo_config import load_config, resolved_xcagi_backend_url
from modstore_server.catalog_store import append_package, get_package, list_packages, load_store

router = APIRouter(prefix="/v1", tags=["catalog"])


def _upload_token() -> str:
    return (os.environ.get("MODSTORE_CATALOG_UPLOAD_TOKEN") or "").strip()


def _require_upload(authorization: Optional[str]) -> None:
    tok = _upload_token()
    if not tok:
        raise HTTPException(503, "未配置 MODSTORE_CATALOG_UPLOAD_TOKEN，拒绝写入")
    if (authorization or "").strip() != f"Bearer {tok}":
        raise HTTPException(401, "无效的上传凭证")


@router.get("/packages", summary="分页列出包")
def api_list_packages(
    artifact: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows, total = list_packages(artifact=artifact, q=q, limit=limit, offset=offset)
    return {"packages": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/packages/{pkg_id}/{version}", summary="包详情")
def api_get_package(pkg_id: str, version: str):
    r = get_package(pkg_id, version)
    if not r:
        raise HTTPException(404, "未找到该版本")
    return r


@router.get("/index.json", summary="轻量全量索引")
def api_index_json():
    data = load_store()
    out = []
    for r in data.get("packages") or []:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "id": r.get("id"),
                "version": r.get("version"),
                "name": r.get("name"),
                "artifact": r.get("artifact") or "mod",
                "sha256": r.get("sha256"),
                "download_url": r.get("download_url")
                or (f"/v1/packages/{r.get('id')}/{r.get('version')}/download" if r.get("stored_filename") else None),
                "commerce": r.get("commerce"),
                "license": r.get("license"),
            }
        )
    return {"packages": out}


@router.get("/packages/{pkg_id}/{version}/download", summary="下载已上传包文件")
def api_download(pkg_id: str, version: str):
    from modstore_server.catalog_store import files_dir

    r = get_package(pkg_id, version)
    if not r:
        raise HTTPException(404, "未找到")
    name = r.get("stored_filename")
    if not name:
        raise HTTPException(404, "该记录无本地文件")
    path = files_dir() / str(name)
    if not path.is_file():
        raise HTTPException(404, "文件缺失")
    from fastapi.responses import FileResponse

    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/packages", summary="登记新包（multipart：metadata JSON + file）")
async def api_upload_package(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    metadata: str = Form(..., description="JSON 字符串，字段与 PackageRecord 一致"),
    file: UploadFile = File(...),
):
    _require_upload(authorization)
    import json

    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(400, "metadata 须为 JSON")
    if not isinstance(meta, dict):
        raise HTTPException(400, "metadata 须为对象")
    if not (str(meta.get("id") or "").strip() and str(meta.get("version") or "").strip()):
        raise HTTPException(400, "metadata 须含 id 与 version")
    rec: Dict[str, Any] = dict(meta)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".xcmod", ".xcemp", ".zip"}:
        raise HTTPException(400, "file 须为 .xcmod / .xcemp / .zip")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / (file.filename or "upload.bin")
        tmp.write_bytes(await file.read())
        if catalog_require_employee_sandbox():
            try:
                base = ""
                if catalog_sandbox_probe_http():
                    try:
                        base = resolved_xcagi_backend_url(load_config()).strip()
                    except Exception:
                        base = ""
                assert_employee_sandbox_passes_for_catalog_zip(
                    tmp,
                    probe_http=catalog_sandbox_probe_http() and bool(base),
                    backend_base=base or None,
                )
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        saved = append_package(rec, tmp)
    return {"ok": True, "package": saved}
