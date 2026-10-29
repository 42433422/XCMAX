"""Publish owner-scoped originals before choosing any business destination."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, CursorResult
from sqlalchemy.orm import Session

from app.application.etl import service_uploads
from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.service_support import clean_filename, new_id, utcnow
from app.db.models.etl import EltSourceAsset, EltSourceRevision, EtlUpload
from app.infrastructure.tenant_scope import current_tenant_id, tenant_id_for_write
from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)


class SourceServiceMixin:
    if TYPE_CHECKING:
        save_upload: Any

    def create_source(
        self,
        db: Session,
        *,
        owner_user_id: int,
        file_name: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> dict[str, Any]:
        asset = EltSourceAsset(
            id=new_id(),
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            name=clean_filename(file_name),
            current_version=1,
        )
        return self._publish_source_revision(
            db,
            asset=asset,
            expected_version=None,
            file_name=file_name,
            content_type=content_type,
            stream=stream,
        )

    def append_source_revision(
        self,
        db: Session,
        *,
        asset_id: str,
        expected_version: int,
        owner_user_id: int,
        file_name: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> dict[str, Any]:
        asset = self._source_asset(db, asset_id, owner_user_id)
        if expected_version < 1:
            raise EtlError("ETL_SOURCE_VERSION_INVALID", "来源版本必须为正整数")
        return self._publish_source_revision(
            db,
            asset=asset,
            expected_version=expected_version,
            file_name=file_name,
            content_type=content_type,
            stream=stream,
        )

    def _publish_source_revision(
        self,
        db: Session,
        *,
        asset: EltSourceAsset,
        expected_version: int | None,
        file_name: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> dict[str, Any]:
        revision_id = new_id()
        original: Path | None = None
        try:
            root = self._source_root(asset.tenant_id, asset.owner_user_id)
            if expected_version is None:
                db.add(asset)
                db.flush()
                version = 1
            else:
                version = expected_version + 1
                claimed = cast(
                    CursorResult[Any],
                    db.execute(
                        update(EltSourceAsset)
                        .where(
                            EltSourceAsset.id == asset.id,
                            EltSourceAsset.tenant_id == tenant_id_for_write(),
                            EltSourceAsset.owner_user_id == asset.owner_user_id,
                            EltSourceAsset.current_version == expected_version,
                        )
                        .values(current_version=version, updated_at=utcnow())
                        .execution_options(synchronize_session=False)
                    ),
                )
                if claimed.rowcount != 1:
                    raise EtlConflict(
                        "ETL_SOURCE_VERSION_CONFLICT", "来源已有新版本，请刷新后再追加"
                    )
                db.expire(asset)
            uploaded = self.save_upload(
                db,
                owner_user_id=asset.owner_user_id,
                file_name=file_name,
                content_type=content_type,
                stream=stream,
            )
            original = root / f"{uploaded['upload_id']}{uploaded['suffix']}"
            upload = self._source_upload(db, uploaded["upload_id"], asset.owner_user_id)
            upload.expires_at = None
            revision = EltSourceRevision(
                id=revision_id,
                tenant_id=asset.tenant_id,
                owner_user_id=asset.owner_user_id,
                asset_id=asset.id,
                version=version,
                upload_id=upload.id,
            )
            db.add(revision)
            db.flush()
            result = {
                "id": asset.id,
                "name": asset.name,
                "current_version": version,
                "revision": self._source_revision_dict(revision, upload),
            }
            # Publication owns the commit: a successful flush alone cannot make
            # an original durable, and a dependency's later commit is too late
            # to clean up a rejected publication.
            db.commit()
            return result
        except BOUNDARY_ERRORS:
            self._discard_unpublished_source(db, revision_id, original)
            raise

    @staticmethod
    def _discard_unpublished_source(db: Session, revision_id: str, original: Path | None) -> None:
        try:
            db.rollback()
            if original is None:
                return
            # A lost commit response does not prove a failed commit. Check the
            # durable revision independently before removing this request's file.
            bind = db.get_bind()
            engine = bind.engine if isinstance(bind, Connection) else bind
            with engine.connect() as connection:
                published = connection.execute(
                    select(EltSourceRevision.id).where(EltSourceRevision.id == revision_id)
                ).first()
            if published is None:
                original.unlink(missing_ok=True)
        except BOUNDARY_ERRORS:
            logger.warning("ELT source publication needs storage reconciliation", exc_info=True)

    @staticmethod
    def _source_asset(db: Session, asset_id: str, owner_user_id: int) -> EltSourceAsset:
        asset = (
            db.query(EltSourceAsset)
            .filter(
                EltSourceAsset.id == asset_id,
                EltSourceAsset.tenant_id == current_tenant_id(),
                EltSourceAsset.owner_user_id == owner_user_id,
            )
            .first()
        )
        if asset is None:
            raise EtlNotFound("来源资产")
        return asset

    @staticmethod
    def _source_upload(db: Session, upload_id: str, owner_user_id: int) -> EtlUpload:
        upload = (
            db.query(EtlUpload)
            .filter(
                EtlUpload.id == upload_id,
                EtlUpload.tenant_id == current_tenant_id(),
                EtlUpload.owner_user_id == owner_user_id,
            )
            .first()
        )
        if upload is None:
            raise EtlNotFound("来源原件")
        return upload

    def _source_revision(
        self,
        db: Session,
        asset_id: str,
        revision_id: str,
        owner_user_id: int,
    ) -> tuple[EltSourceRevision, EtlUpload]:
        self._source_asset(db, asset_id, owner_user_id)
        revision = (
            db.query(EltSourceRevision)
            .filter(
                EltSourceRevision.id == revision_id,
                EltSourceRevision.asset_id == asset_id,
                EltSourceRevision.tenant_id == current_tenant_id(),
                EltSourceRevision.owner_user_id == owner_user_id,
            )
            .first()
        )
        if revision is None:
            raise EtlNotFound("来源版本")
        return revision, self._source_upload(db, revision.upload_id, owner_user_id)

    def get_source(self, db: Session, *, asset_id: str, owner_user_id: int) -> dict[str, Any]:
        asset = self._source_asset(db, asset_id, owner_user_id)
        revision = (
            db.query(EltSourceRevision)
            .filter(
                EltSourceRevision.asset_id == asset.id,
                EltSourceRevision.version == asset.current_version,
                EltSourceRevision.tenant_id == current_tenant_id(),
                EltSourceRevision.owner_user_id == owner_user_id,
            )
            .first()
        )
        if revision is None:
            raise EtlNotFound("来源版本")
        return {
            "id": asset.id,
            "name": asset.name,
            "current_version": asset.current_version,
            "revision": self._source_revision_dict(
                revision, self._source_upload(db, revision.upload_id, owner_user_id)
            ),
        }

    def list_source_revisions(
        self,
        db: Session,
        *,
        asset_id: str,
        owner_user_id: int,
    ) -> list[dict[str, Any]]:
        self._source_asset(db, asset_id, owner_user_id)
        rows = (
            db.query(EltSourceRevision, EtlUpload)
            .join(EtlUpload, EtlUpload.id == EltSourceRevision.upload_id)
            .filter(
                EltSourceRevision.asset_id == asset_id,
                EltSourceRevision.tenant_id == current_tenant_id(),
                EltSourceRevision.owner_user_id == owner_user_id,
                EtlUpload.tenant_id == current_tenant_id(),
                EtlUpload.owner_user_id == owner_user_id,
            )
            .order_by(EltSourceRevision.version)
            .all()
        )
        return [self._source_revision_dict(revision, upload) for revision, upload in rows]

    def get_source_revision(
        self,
        db: Session,
        *,
        asset_id: str,
        revision_id: str,
        owner_user_id: int,
    ) -> dict[str, Any]:
        revision, upload = self._source_revision(db, asset_id, revision_id, owner_user_id)
        return self._source_revision_dict(revision, upload)

    @staticmethod
    def _source_revision_dict(revision: EltSourceRevision, upload: EtlUpload) -> dict[str, Any]:
        return {
            "id": revision.id,
            "asset_id": revision.asset_id,
            "version": revision.version,
            "upload_id": upload.id,
            "file_name": upload.file_name,
            "suffix": upload.suffix,
            "size_bytes": upload.size_bytes,
            "sha256": upload.sha256,
            "created_at": revision.created_at.isoformat() if revision.created_at else None,
        }

    @staticmethod
    def _source_root(tenant_id: int, owner_user_id: int) -> Path:
        base = Path(service_uploads.get_app_data_dir()).resolve()
        root = base / "etl" / "uploads" / str(tenant_id) / str(owner_user_id)
        if any(
            path.is_symlink()
            for path in (root, *root.parents)
            if path != base and base in path.parents
        ):
            raise EtlError("ETL_SOURCE_STORAGE_INVALID", "来源原件存储位置不可用", status_code=409)
        return root

    def get_source_content(
        self,
        db: Session,
        *,
        asset_id: str,
        revision_id: str,
        owner_user_id: int,
    ) -> tuple[BinaryIO, str]:
        revision, upload = self._source_revision(db, asset_id, revision_id, owner_user_id)
        root = self._source_root(revision.tenant_id, owner_user_id)
        original = root / f"{upload.id}{upload.suffix}"
        if Path(upload.storage_path) != original or original.is_symlink():
            raise EtlError("ETL_SOURCE_STORAGE_INVALID", "来源原件存储位置不可用", status_code=409)
        if not original.is_file():
            raise EtlError("ETL_UPLOAD_MISSING", "来源原件不可用", status_code=410)
        # Serve the verified snapshot, not a path that the response would reopen
        # after verification. Disk replacement or an in-place write must never
        # change the bytes delivered for an immutable source revision.
        snapshot = SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b")
        try:
            digest = hashlib.sha256()
            size = 0
            with original.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > upload.size_bytes:
                        raise EtlConflict("ETL_SOURCE_CONTENT_CHANGED", "来源原件校验失败")
                    digest.update(chunk)
                    snapshot.write(chunk)
            if size != upload.size_bytes or digest.hexdigest() != upload.sha256:
                raise EtlConflict("ETL_SOURCE_CONTENT_CHANGED", "来源原件校验失败")
            snapshot.seek(0)
            return cast(BinaryIO, snapshot), upload.file_name
        except BOUNDARY_ERRORS:
            snapshot.close()
            raise
