"""Upload ownership and retention-safe storage operations."""

from __future__ import annotations

import hashlib
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError, EtlNotFound
from app.application.etl.parsers import SUPPORTED_SUFFIXES
from app.application.etl.service_support import (
    MAX_FILE_BYTES,
    clean_batch_id,
    clean_filename,
    clean_relative_path,
    new_id,
    utcnow,
)
from app.db.models.etl import EtlUpload
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_utils import get_app_data_dir


class UploadServiceMixin:
    def save_upload(
        self,
        db: Session,
        *,
        owner_user_id: int,
        file_name: str,
        content_type: str | None,
        stream: BinaryIO,
        batch_id: str | None = None,
        relative_path: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = tenant_id_for_write()
        safe_name = clean_filename(file_name)
        safe_batch_id = clean_batch_id(batch_id)
        safe_relative_path = clean_relative_path(relative_path, safe_name)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise EtlError("ETL_FILE_TYPE_UNSUPPORTED", f"不支持的文件类型: {suffix}")
        upload_id = new_id()
        root = (
            Path(get_app_data_dir()).resolve()
            / "etl"
            / "uploads"
            / str(tenant_id)
            / str(owner_user_id)
        )
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / f"{upload_id}{suffix}").resolve()
        if root not in destination.parents:
            raise EtlError("ETL_UPLOAD_PATH_INVALID", "上传路径无效")

        digest = hashlib.sha256()
        total = 0
        try:
            with destination.open("xb") as handle:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise EtlError(
                            "ETL_FILE_TOO_LARGE",
                            "单文件不能超过 50MB",
                            status_code=413,
                        )
                    digest.update(chunk)
                    handle.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if total == 0:
            destination.unlink(missing_ok=True)
            raise EtlError("ETL_FILE_EMPTY", "上传文件为空")

        upload = EtlUpload(
            id=upload_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            file_name=safe_name,
            batch_id=safe_batch_id,
            relative_path=safe_relative_path,
            suffix=suffix,
            content_type=str(content_type or "")[:128] or None,
            size_bytes=total,
            sha256=digest.hexdigest(),
            storage_path=str(destination),
            expires_at=utcnow() + timedelta(days=7),
        )
        db.add(upload)
        db.flush()
        return self.upload_dict(upload)

    def upload_dict(self, upload: EtlUpload) -> dict[str, Any]:
        return {
            "upload_id": upload.id,
            "file_name": upload.file_name,
            "batch_id": upload.batch_id,
            "relative_path": upload.relative_path or upload.file_name,
            "suffix": upload.suffix,
            "size_bytes": upload.size_bytes,
            "sha256": upload.sha256,
            "expires_at": upload.expires_at.isoformat() if upload.expires_at else None,
        }

    def _owned_upload(self, db: Session, upload_id: str, owner_user_id: int) -> EtlUpload:
        upload = self._owned_upload_record(db, upload_id, owner_user_id)
        if upload.expires_at:
            expires_at = upload.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < utcnow():
                raise EtlError("ETL_UPLOAD_EXPIRED", "上传文件已过期", status_code=410)
        if not upload.storage_path or not Path(upload.storage_path).is_file():
            raise EtlError("ETL_UPLOAD_MISSING", "上传文件已被清理", status_code=410)
        return upload

    @staticmethod
    def _owned_upload_record(db: Session, upload_id: str, owner_user_id: int) -> EtlUpload:
        upload = (
            db.query(EtlUpload)
            .filter(EtlUpload.id == upload_id, EtlUpload.owner_user_id == owner_user_id)
            .first()
        )
        if upload is None:
            raise EtlNotFound("上传文件")
        return upload
