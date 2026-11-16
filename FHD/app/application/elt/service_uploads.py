"""Upload ownership and retention-safe storage operations."""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy.orm import Session

from app.application.elt.errors import EltError, EltNotFound
from app.application.elt.parsers import SUPPORTED_SUFFIXES
from app.application.elt.service_support import (
    MAX_FILE_BYTES,
    MAX_FILE_MIB,
    READ_ONLY_MODE,
    clean_batch_id,
    clean_filename,
    clean_relative_path,
    new_id,
    utcnow,
)
from app.application.elt.upload_content_gate import check_declared_mime, check_stored_content
from app.db.models.elt import EltUpload
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir


def discard_stored_upload(path: Path) -> None:
    # Stored originals are read-only; Windows refuses to unlink them until writable again.
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    path.unlink(missing_ok=True)


def register_chat_upload(user, filename: str, content_type: str | None, stream: BinaryIO):
    """Create an owned immutable copy from an authenticated upload, never a client path."""
    from app.application.elt import get_elt_service
    from app.db.session import get_db
    from app.infrastructure.tenant_scope import tenant_scope

    owner, tenant = getattr(user, "id", None), getattr(user, "tenant_id", None)
    if not owner or not tenant:
        raise EltError("ELT_USER_REQUIRED", "需要登录并具有租户上下文", status_code=401)
    with tenant_scope(int(tenant)), get_db() as db:
        return get_elt_service().save_upload(
            db,
            owner_user_id=int(owner),
            file_name=filename,
            content_type=content_type,
            stream=stream,
        )


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
        requested_suffix = Path(safe_name).suffix.lower()
        # Physical paths use a server-owned suffix constant, never part of the supplied name.
        suffix = next(
            (allowed for allowed in SUPPORTED_SUFFIXES if allowed == requested_suffix), None
        )
        if suffix is None:
            raise EltError("ELT_FILE_TYPE_UNSUPPORTED", f"不支持的文件类型: {requested_suffix}")
        check_declared_mime(suffix, content_type)
        upload_id = new_id()
        root = (
            Path(get_app_data_dir()).resolve()
            / "elt"
            / "uploads"
            / str(tenant_id)
            / str(owner_user_id)
        )
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / f"{upload_id}{suffix}").resolve()
        if root not in destination.parents:
            raise EltError("ELT_UPLOAD_PATH_INVALID", "上传路径无效")

        digest = hashlib.sha256()
        total = 0
        created = False
        try:
            with destination.open("xb") as handle:
                created = True
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise EltError(
                            "ELT_FILE_TOO_LARGE",
                            f"单文件不能超过 {MAX_FILE_MIB}MB",
                            status_code=413,
                        )
                    digest.update(chunk)
                    handle.write(chunk)
        except RECOVERABLE_ERRORS:
            if created:
                destination.unlink(missing_ok=True)
            raise
        if total == 0:
            destination.unlink(missing_ok=True)
            raise EltError("ELT_FILE_EMPTY", "上传文件为空")
        verified = False
        try:
            check_stored_content(destination, suffix)
            verified = True
        finally:
            if not verified:
                destination.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            destination.chmod(READ_ONLY_MODE)

        upload = EltUpload(
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
        from app.application.elt.audit import record_elt_audit

        record_elt_audit(
            db,
            actor=owner_user_id,
            action="elt_upload",
            payload={
                "upload_id": upload.id,
                "file_name": upload.file_name,
                "sha256": upload.sha256,
                "size_bytes": upload.size_bytes,
                "batch_id": upload.batch_id,
                "outcome": "stored",
            },
        )
        return self.upload_dict(upload)

    def upload_dict(self, upload: EltUpload) -> dict[str, Any]:
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

    def _owned_upload(self, db: Session, upload_id: str, owner_user_id: int) -> EltUpload:
        upload = self._owned_upload_record(db, upload_id, owner_user_id)
        if upload.expires_at:
            expires_at = upload.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < utcnow():
                raise EltError("ELT_UPLOAD_EXPIRED", "上传文件已过期", status_code=410)
        if not upload.storage_path or not Path(upload.storage_path).is_file():
            raise EltError("ELT_UPLOAD_MISSING", "上传文件已被清理", status_code=410)
        return upload

    @staticmethod
    def _owned_upload_record(db: Session, upload_id: str, owner_user_id: int) -> EltUpload:
        upload = (
            db.query(EltUpload)
            .filter(EltUpload.id == upload_id, EltUpload.owner_user_id == owner_user_id)
            .first()
        )
        if upload is None:
            raise EltNotFound("上传文件")
        return upload
