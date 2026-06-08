"""工作台用户素材库：上传、列表、下载、删除、元数据更新。"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from modstore_server.api.deps import _get_current_user
from modstore_server.models import User, UserStudioAsset, get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workbench/studio-assets", tags=["workbench"])

_STUDIO_MAX_DEFAULT = 100 * 1024 * 1024

_ALLOWED_SUFFIX = {
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".webm",
    ".flac",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".txt",
    ".md",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".csv",
    ".json",
}

_SUFFIX_TO_MIME = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".csv": "text/csv",
    ".json": "application/json",
}

_KINDS = {"audio", "image", "document", "other"}

_AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_DOC_EXT = {".pdf", ".txt", ".md", ".docx", ".xlsx", ".xlsm", ".csv", ".json"}


def _max_bytes() -> int:
    raw = (os.environ.get("MODSTORE_STUDIO_ASSET_MAX_BYTES") or "").strip()
    if not raw:
        raw = (os.environ.get("MODSTORE_EMPLOYEE_FILE_MAX_BYTES") or "").strip()
    if not raw:
        return _STUDIO_MAX_DEFAULT
    try:
        return max(1, int(raw, 10))
    except ValueError:
        return _STUDIO_MAX_DEFAULT


def _data_root() -> Path:
    raw = (os.environ.get("MODSTORE_DATA_DIR") or "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
    else:
        p = (Path.cwd() / "var").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_basename(name: str, fallback: str = "upload.bin") -> str:
    base = Path(name or "").name
    if not base or base in {".", ".."}:
        return fallback
    if ".." in base or "/" in base or "\\" in base:
        return fallback
    base = re.sub(r"[^\w.\-()\u4e00-\u9fff]+", "_", base).strip("._") or fallback
    return base[:220] if len(base) > 220 else base


def _infer_kind(suffix: str) -> str:
    if suffix in _AUDIO_EXT:
        return "audio"
    if suffix in _IMAGE_EXT:
        return "image"
    if suffix in _DOC_EXT:
        return "document"
    return "other"


def _normalize_mime(suffix: str, declared: str) -> str:
    low = (declared or "").strip().lower()
    if low and "/" in low and ".." not in low and len(low) < 200:
        return low
    return _SUFFIX_TO_MIME.get(suffix, "application/octet-stream")


def _resolved_file_path(root: Path, relpath: str) -> Path:
    if not relpath or ".." in relpath:
        raise HTTPException(404, "素材不存在")
    full = (root / relpath).resolve()
    root_r = root.resolve()
    try:
        full.relative_to(root_r)
    except ValueError as e:
        raise HTTPException(404, "素材不存在") from e
    return full


def _parse_metadata(raw: Optional[str]) -> Dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "metadata 不是合法 JSON")
    if not isinstance(obj, dict):
        raise HTTPException(400, "metadata 必须是 JSON 对象")
    return obj


def _now_ts(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.isoformat() + "Z" if dt.tzinfo is None else dt.isoformat()


class StudioAssetMetadataPatch(BaseModel):
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_studio_assets(
    user: User = Depends(_get_current_user),
    offset: int = 0,
    limit: int = 50,
):
    if offset < 0:
        offset = 0
    limit = max(1, min(200, limit))
    sf = get_session_factory()
    with sf() as session:
        q = (
            session.query(UserStudioAsset)
            .filter(UserStudioAsset.user_id == int(user.id))
            .order_by(UserStudioAsset.id.desc())
        )
        total = q.count()
        rows: List[UserStudioAsset] = q.offset(offset).limit(limit).all()
        items = []
        for r in rows:
            meta: Dict[str, Any] = {}
            try:
                meta = json.loads(r.metadata_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            items.append(
                {
                    "id": r.id,
                    "kind": r.kind,
                    "filename": r.filename,
                    "mime_type": r.mime_type,
                    "size_bytes": int(r.size_bytes or 0),
                    "metadata": meta,
                    "created_at": _now_ts(r.created_at),
                    "updated_at": _now_ts(r.updated_at),
                }
            )
        return {"total": total, "offset": offset, "limit": limit, "items": items}


@router.post("")
async def upload_studio_asset(
    file: UploadFile = File(...),
    kind: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
    user: User = Depends(_get_current_user),
):
    max_b = _max_bytes()
    payload = await file.read()
    if len(payload) > max_b:
        mb = max(1, max_b // (1024 * 1024))
        raise HTTPException(
            413,
            f"文件过大（超过 {mb}MB）。可调高 MODSTORE_STUDIO_ASSET_MAX_BYTES 与网关 client_max_body_size。",
        )

    safe_name = _safe_basename(file.filename or "")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(400, f"不支持的文件类型：{suffix or '(无扩展名)'}")

    inferred = _infer_kind(suffix)
    k = (kind or "").strip().lower() or inferred
    if k not in _KINDS:
        raise HTTPException(400, f"非法 kind：{kind}")
    if k != inferred and inferred != "other":
        raise HTTPException(400, f"kind 与文件扩展名不一致（推断为 {inferred}）")

    meta_obj = _parse_metadata(metadata)
    mime = _normalize_mime(suffix, file.content_type or "")

    root = _data_root()
    sf = get_session_factory()
    row = UserStudioAsset(
        user_id=int(user.id),
        kind=k,
        filename=safe_name,
        mime_type=mime,
        size_bytes=len(payload),
        storage_relpath="",
        metadata_json=json.dumps(meta_obj, ensure_ascii=False),
    )
    with sf() as session:
        session.add(row)
        session.flush()
        aid = int(row.id)
        relpath = f"user_studio_assets/{int(user.id)}/{aid}/{safe_name}"
        dest = _resolved_file_path(root, relpath)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(payload)
        except OSError as e:
            session.rollback()
            logger.warning("studio asset write failed: %s", e)
            raise HTTPException(500, "写入文件失败") from e
        row.storage_relpath = relpath
        session.commit()
        return {
            "id": aid,
            "kind": row.kind,
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "metadata": meta_obj,
            "created_at": _now_ts(row.created_at),
        }


@router.get("/{asset_id}/file")
def download_studio_asset(
    asset_id: int,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(UserStudioAsset)
            .filter(UserStudioAsset.id == asset_id, UserStudioAsset.user_id == int(user.id))
            .first()
        )
        if not row or not row.storage_relpath:
            raise HTTPException(404, "素材不存在")
        rel = row.storage_relpath
        mime = row.mime_type or "application/octet-stream"
        fn = row.filename or "download"
    root = _data_root()
    path = _resolved_file_path(root, rel)
    if not path.is_file():
        raise HTTPException(404, "文件已丢失")
    return FileResponse(path, filename=fn, media_type=mime)


@router.delete("/{asset_id}")
def delete_studio_asset(
    asset_id: int,
    user: User = Depends(_get_current_user),
):
    root = _data_root()
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(UserStudioAsset)
            .filter(UserStudioAsset.id == asset_id, UserStudioAsset.user_id == int(user.id))
            .first()
        )
        if not row:
            raise HTTPException(404, "素材不存在")
        rel = row.storage_relpath or ""
        session.delete(row)
        session.commit()
    if rel:
        try:
            path = _resolved_file_path(root, rel)
            if path.is_file():
                path.unlink()
            parent = path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            logger.warning("studio asset delete orphan file failed rel=%s", rel)
    return {"ok": True}


@router.patch("/{asset_id}")
def patch_studio_asset_metadata(
    asset_id: int,
    body: StudioAssetMetadataPatch,
    user: User = Depends(_get_current_user),
):
    sf = get_session_factory()
    with sf() as session:
        row = (
            session.query(UserStudioAsset)
            .filter(UserStudioAsset.id == asset_id, UserStudioAsset.user_id == int(user.id))
            .first()
        )
        if not row:
            raise HTTPException(404, "素材不存在")
        row.metadata_json = json.dumps(body.metadata or {}, ensure_ascii=False)
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        return {
            "id": row.id,
            "metadata": body.metadata or {},
            "updated_at": _now_ts(row.updated_at),
        }
