"""附件工件 HTTP 接口：上传即入库，供对话工具按需取数。"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.application.attachment_artifacts.parser import (
    TemporaryDocument,
    UnsupportedDocument,
    parse_file,
)
from app.application.attachment_artifacts.store import ArtifactStore

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_FILES = 200
_CHUNK_BYTES = 1024 * 1024


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


async def _ingest(upload: UploadFile, index: int, tmpdir: Path, store: ArtifactStore) -> dict[str, Any]:
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
    return {
        **base,
        "status": "ok",
        "artifact": {
            "id": record.id,
            "size": record.size,
            "created_at": record.created_at,
            "sheets": [
                {"name": sheet.name, "columns": sheet.columns, "row_count": sheet.row_count}
                for sheet in record.sheets
            ],
        },
    }


@router.post("/")
async def upload_attachments(files: list[UploadFile] = File(...)) -> dict[str, Any]:
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
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="xcagi_attachment_") as tmpdir:
        for index, upload in enumerate(files):
            results.append(await _ingest(upload, index, Path(tmpdir), store))
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
