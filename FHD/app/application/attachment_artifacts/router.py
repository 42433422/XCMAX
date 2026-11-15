"""附件工件 HTTP 接口：上传即入库，供对话工具按需取数。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from app.application.attachment_artifacts.attachment_parser import (
    TemporaryDocument,
    UnsupportedDocument,
    parse_file,
)
from app.application.attachment_artifacts.store import ArtifactStore
from app.utils.operational_errors import BOUNDARY_ERRORS

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_FILES = 200
_CHUNK_BYTES = 1024 * 1024
# 只有这些后缀同时登记成 ELT 上传，供数据对接中心的批量导入直接使用。
_ELT_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xls"})


class _TooLarge(Exception):
    """单个上传文件超过大小上限。"""


def _safe_name(upload: UploadFile, index: int) -> str:
    raw = (upload.filename or "").replace("\\", "/")
    return raw.rsplit("/", 1)[-1] or f"upload_{index}"


async def _save_upload(upload: UploadFile, target: Path) -> int:
    total = 0
    with target.open("wb") as handle:
        while chunk := await upload.read(_CHUNK_BYTES):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise _TooLarge
            handle.write(chunk)
    return total


def _ingest_identity(request: Request) -> tuple[int, int] | None:
    """取当前会话的租户与用户；未登录或缺少租户时不登记 ELT 上传。"""
    try:
        from app.infrastructure.auth.dependencies import resolve_session_user

        user = resolve_session_user(request)
    except BOUNDARY_ERRORS:
        return None
    tenant = getattr(user, "tenant_id", None)
    owner = getattr(user, "id", None)
    if tenant is None or owner is None:
        return None
    return int(tenant), int(owner)


def _register_elt_upload(
    target: Path, name: str, content_type: str | None, identity: tuple[int, int] | None
) -> str:
    """把电子表格同时登记成 ELT 上传，数据对接中心可直接按文件名导入。"""
    if identity is None or Path(name).suffix.lower() not in _ELT_SUFFIXES:
        return ""
    tenant, owner = identity
    try:
        from app.application.elt.service_uploads import UploadServiceMixin
        from app.db.session import get_db
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(tenant), get_db() as db, target.open("rb") as stream:
            saved = UploadServiceMixin().save_upload(
                db,
                owner_user_id=owner,
                file_name=name,
                content_type=content_type,
                stream=stream,
            )
            return str(saved.get("upload_id") or "")
    except BOUNDARY_ERRORS:
        return ""


async def _ingest(
    upload: UploadFile,
    index: int,
    tmpdir: Path,
    store: ArtifactStore,
    identity: tuple[int, int] | None = None,
) -> dict[str, Any]:
    name = _safe_name(upload, index)
    base: dict[str, Any] = {"name": name}
    if name.startswith(("~$", "._")):
        return {**base, "status": "skipped", "message": "临时文件已跳过"}
    target = tmpdir / f"{index}_{name}"
    try:
        await _save_upload(upload, target)
    except _TooLarge:
        target.unlink(missing_ok=True)
        return {**base, "status": "too_large", "message": "文件超过 50MB 上限"}
    try:
        record = parse_file(target, name=name)
    except TemporaryDocument as exc:
        return {**base, "status": "skipped", "message": str(exc)}
    except UnsupportedDocument as exc:
        return {**base, "status": "unsupported", "message": str(exc)}
    except (OSError, ValueError) as exc:
        return {**base, "status": "failed", "message": f"解析失败: {exc}"}
    store.save(record)
    elt_upload_id = _register_elt_upload(target, name, upload.content_type, identity)
    return {
        **base,
        "status": "ok",
        "artifact": {
            "id": record.id,
            "size": record.size,
            "created_at": record.created_at,
            "elt_upload_id": elt_upload_id,
            "sheets": [
                {"name": sheet.name, "columns": sheet.columns, "row_count": sheet.row_count}
                for sheet in record.sheets
            ],
        },
    }


@router.post("/")
async def upload_attachments(request: Request, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """批量上传；单文件失败不影响整批。"""
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=f"单批最多 {MAX_BATCH_FILES} 个文件")
    for upload in files:
        declared = getattr(upload, "size", None)
        if declared is not None and declared > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{_safe_name(upload, 0)} 超过 50MB 上限",
            )
    store = ArtifactStore()
    identity = _ingest_identity(request)
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="xcagi_attachment_") as tmpdir:
        for index, upload in enumerate(files):
            results.append(await _ingest(upload, index, Path(tmpdir), store, identity))
    return {"ok": True, "results": results}


@router.get("/")
async def list_attachments_api() -> dict[str, Any]:
    return {"ok": True, "attachments": ArtifactStore().list_all()}


@router.get("/{artifact_id}")
async def get_attachment(artifact_id: str) -> dict[str, Any]:
    record = ArtifactStore().get(artifact_id)
    if record is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    return {"ok": True, "artifact": record.to_dict()}


@router.delete("/{artifact_id}")
async def delete_attachment(artifact_id: str) -> dict[str, Any]:
    if not ArtifactStore().delete(artifact_id):
        raise HTTPException(status_code=404, detail="附件不存在")
    return {"ok": True, "deleted": artifact_id}