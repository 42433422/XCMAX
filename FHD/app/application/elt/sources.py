"""Neutral source access through the shared, quota-managed original archive."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.application.etl import archive_store, service_uploads
from app.application.etl.archive_policy import ArchivePolicyError
from app.application.etl.errors import EtlConflict, EtlError, EtlNotFound
from app.application.etl.service_support import MAX_FILE_BYTES
from app.db.models.etl_archive import EtlArchiveAsset, EtlArchiveVersion
from app.infrastructure.tenant_scope import current_tenant_id, tenant_id_for_write


class SourceAssetServiceMixin:
    def create_source(
        self,
        db: Session,
        *,
        owner_user_id: int,
        file_name: str,
        content_type: str | None,
        stream: BinaryIO,
        request_key: str,
    ) -> dict[str, Any]:
        tenant_id_for_write()
        body = self._source_body(stream)
        try:
            revision = archive_store.create_original(
                db,
                owner=owner_user_id,
                name=file_name,
                body=body,
                root=self._source_root(),
                request_key=request_key,
            )
        except ArchivePolicyError as exc:
            raise EtlConflict("ETL_SOURCE_ARCHIVE_CONFLICT", exc.public_message) from exc
        asset = self._source_asset(db, revision.asset_id, owner_user_id)
        return self._source_dict(db, asset, revision)

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
        request_key: str,
    ) -> dict[str, Any]:
        asset = self._source_asset(db, asset_id, owner_user_id)
        if type(expected_version) is not int or expected_version < 1:
            raise EtlError("ETL_SOURCE_VERSION_INVALID", "来源版本必须为正整数")
        body = self._source_body(stream)
        try:
            revision = archive_store.append_original_version(
                db,
                owner=owner_user_id,
                asset_id=asset.id,
                body=body,
                root=self._source_root(),
                request_key=request_key,
                expected_version=expected_version,
            )
        except ArchivePolicyError as exc:
            raise EtlConflict("ETL_SOURCE_ARCHIVE_CONFLICT", exc.public_message) from exc
        return self._source_dict(db, asset, revision)

    @staticmethod
    def _source_body(stream: BinaryIO) -> bytes:
        chunks = []
        size = 0
        while chunk := stream.read(min(1024 * 1024, MAX_FILE_BYTES + 1 - size)):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise EtlError("ETL_FILE_TOO_LARGE", "来源原件超过单文件大小限制", status_code=413)
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _source_root() -> Path:
        return Path(service_uploads.get_app_data_dir()) / "etl" / "archive"

    @staticmethod
    def _source_asset(db: Session, asset_id: str, owner_user_id: int) -> EtlArchiveAsset:
        tenant = current_tenant_id()
        if tenant is None:
            raise EtlNotFound("来源资产")
        asset = (
            db.query(EtlArchiveAsset)
            .filter_by(id=asset_id, tenant_id=tenant, owner_user_id=owner_user_id, state="active")
            .first()
        )
        if asset is None:
            raise EtlNotFound("来源资产")
        return asset

    def _source_revision(
        self, db: Session, asset_id: str, revision_id: str, owner_user_id: int
    ) -> tuple[EtlArchiveAsset, EtlArchiveVersion]:
        asset = self._source_asset(db, asset_id, owner_user_id)
        revision = (
            db.query(EtlArchiveVersion)
            .filter_by(
                id=revision_id,
                asset_id=asset.id,
                tenant_id=asset.tenant_id,
                owner_user_id=owner_user_id,
            )
            .first()
        )
        if revision is None:
            raise EtlNotFound("来源版本")
        return asset, revision

    def _source_dict(
        self, db: Session, asset: EtlArchiveAsset, revision: EtlArchiveVersion
    ) -> dict[str, Any]:
        current = (
            db.query(func.max(EtlArchiveVersion.version))
            .filter_by(
                asset_id=asset.id, tenant_id=asset.tenant_id, owner_user_id=asset.owner_user_id
            )
            .scalar()
        )
        return {
            "id": asset.id,
            "name": asset.name,
            "current_version": current,
            "revision": self._source_revision_dict(asset, revision),
        }

    def get_source(self, db: Session, *, asset_id: str, owner_user_id: int) -> dict[str, Any]:
        asset = self._source_asset(db, asset_id, owner_user_id)
        revision = (
            db.query(EtlArchiveVersion)
            .filter_by(asset_id=asset.id, tenant_id=asset.tenant_id, owner_user_id=owner_user_id)
            .order_by(EtlArchiveVersion.version.desc())
            .first()
        )
        if revision is None:
            raise EtlNotFound("来源版本")
        return self._source_dict(db, asset, revision)

    def list_source_revisions(
        self, db: Session, *, asset_id: str, owner_user_id: int
    ) -> list[dict[str, Any]]:
        asset = self._source_asset(db, asset_id, owner_user_id)
        rows = (
            db.query(EtlArchiveVersion)
            .filter_by(asset_id=asset.id, tenant_id=asset.tenant_id, owner_user_id=owner_user_id)
            .order_by(EtlArchiveVersion.version)
            .all()
        )
        return [self._source_revision_dict(asset, revision) for revision in rows]

    def get_source_revision(
        self, db: Session, *, asset_id: str, revision_id: str, owner_user_id: int
    ) -> dict[str, Any]:
        asset, revision = self._source_revision(db, asset_id, revision_id, owner_user_id)
        return self._source_revision_dict(asset, revision)

    @staticmethod
    def _source_revision_dict(
        asset: EtlArchiveAsset, revision: EtlArchiveVersion
    ) -> dict[str, Any]:
        return {
            "id": revision.id,
            "asset_id": asset.id,
            "version": revision.version,
            "file_name": asset.name,
            "size_bytes": revision.size_bytes,
            "sha256": revision.sha256,
            "status": revision.status,
            "created_at": revision.created_at.isoformat() if revision.created_at else None,
        }

    def get_source_content(
        self, db: Session, *, asset_id: str, revision_id: str, owner_user_id: int
    ) -> tuple[BytesIO, str]:
        asset, revision = self._source_revision(db, asset_id, revision_id, owner_user_id)
        try:
            body = archive_store.read_original(
                db, owner=owner_user_id, version_id=revision.id, root=self._source_root()
            )
        except ArchivePolicyError as exc:
            raise EtlConflict("ETL_SOURCE_ARCHIVE_CONFLICT", exc.public_message) from exc
        return BytesIO(body), asset.name
