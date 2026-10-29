"""Committed, integrity-checked source snapshots, before mapping or target effects."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict
from app.application.etl.parser_types import ParsedDataset, ParsedRow, ParsedRows
from app.application.etl.parsers import MAX_ROWS
from app.application.etl.service_support import dump_json, load_json, utcnow
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.infrastructure.tenant_scope import tenant_id_for_write


def source_digest(rows: Iterable[ParsedRow]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(dump_json([row.sheet, row.row_number, row.values, row.provenance]).encode())
        digest.update(b"\n")
    return digest.hexdigest()


class SourceServiceMixin:
    if TYPE_CHECKING:
        _owned_upload: Any
        _owned_upload_record: Any

    @staticmethod
    def _source_profile(run: EtlRun) -> dict[str, Any]:
        return {
            "target_type": run.target_type,
            "compatibility_preset_id": load_json(run.draft_json, {}).get("compatibility_preset_id")
            or "",
            "parser_version": 1,
        }

    def _load_source_snapshot(self, db: Session, run: EtlRun) -> ParsedDataset | None:
        if run.tenant_id != tenant_id_for_write():
            raise EtlConflict("ETL_SOURCE_SNAPSHOT_INVALID", "原始数据快照不属于当前租户")
        summary = load_json(run.summary_json, {})
        manifest = summary.get("source_snapshot")
        if manifest is None:
            return None  # Historical previews keep their original compatibility path.
        try:
            expires_at = datetime.fromisoformat(manifest["expires_at"])
            created_at = run.created_at or utcnow()
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if (
                expires_at.tzinfo is None
                or expires_at > created_at + timedelta(days=90)
                or expires_at <= utcnow()
            ):
                raise ValueError("snapshot expiry")
        except (KeyError, TypeError, ValueError):
            raise EtlConflict(
                "ETL_SOURCE_SNAPSHOT_INVALID",
                "原始数据快照期限无效或已过期，请重新上传；已停止转换和写入",
            ) from None
        rows = (
            db.query(
                EtlRunRow.source_sheet,
                EtlRunRow.source_row,
                EtlRunRow.source_json,
                EtlRunRow.provenance_json,
            )
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.tenant_id == tenant_id_for_write(),
                EtlRunRow.owner_user_id == run.owner_user_id,
            )
            .order_by(EtlRunRow.id)
            .limit(MAX_ROWS + 1)
            .yield_per(500)
        )
        sources = ParsedRows()
        dataset = None
        try:

            def parsed_sources():
                for row in rows:
                    source = ParsedRow(
                        row.source_sheet,
                        row.source_row,
                        load_json(row.source_json, {}),
                        load_json(row.provenance_json, {}),
                    )
                    sources.append(source)
                    yield source

            digest = source_digest(parsed_sources())
            if (
                not isinstance(manifest, dict)
                or manifest.get("version") != 1
                or manifest.get("upload_id") != run.upload_id
                or manifest.get("file_sha256") != run.file_sha256
                or manifest.get("profile") != self._source_profile(run)
                or manifest.get("rows") != len(sources)
                or len(sources) > MAX_ROWS
                or manifest.get("sha256") != digest
                or not isinstance(manifest.get("headers"), list)
                or manifest.get("requires_original")
                != (run.target_type in {"knowledge", "attendance"})
                or (
                    run.created_at is not None
                    and run.created_at.replace(tzinfo=UTC) < utcnow() - timedelta(days=90)
                )
            ):
                raise EtlConflict(
                    "ETL_SOURCE_SNAPSHOT_INVALID",
                    "原始数据快照已过期或不完整，请重新上传；已停止转换和写入",
                )
            dataset = ParsedDataset(
                headers=manifest["headers"],
                rows=sources,
                source_features=load_json(run.source_features_json, {}),
                warnings=summary.get("warnings", []),
            )
            return dataset
        finally:
            if dataset is None:
                sources.close()

    def _persist_source_snapshot(
        self,
        db: Session,
        run: EtlRun,
        dataset: ParsedDataset,
        *,
        source_expires_at: str | None = None,
    ) -> None:
        existing = self._load_source_snapshot(db, run)
        if existing is not None:
            existing.close()
            raise EtlConflict("ETL_SOURCE_SNAPSHOT_EXISTS", "原始数据快照不可覆盖，请新建处理任务")
        if len(dataset.rows) > MAX_ROWS:
            raise EtlConflict("ETL_SOURCE_TOO_MANY_ROWS", "原始数据行数超过处理上限")
        # Replace only incomplete legacy attempts; the completion marker and all
        # raw rows commit together. No LLM, field mapping, or target call precedes it.
        db.query(EtlRunRow).filter(
            EtlRunRow.run_id == run.id,
            EtlRunRow.tenant_id == tenant_id_for_write(),
            EtlRunRow.owner_user_id == run.owner_user_id,
        ).delete(synchronize_session=False)
        for index, source in enumerate(dataset.rows, 1):
            db.add(
                EtlRunRow(
                    tenant_id=tenant_id_for_write(),
                    owner_user_id=run.owner_user_id,
                    run_id=run.id,
                    source_sheet=source.sheet,
                    source_row=source.row_number,
                    source_json=dump_json(source.values),
                    provenance_json=dump_json(source.provenance),
                )
            )
            if index % 500 == 0:
                db.flush()
        created_at = run.created_at or utcnow()
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        summary = load_json(run.summary_json, {})
        summary.update(
            {
                "warnings": dataset.warnings,
                "source_snapshot": {
                    "version": 1,
                    "upload_id": run.upload_id,
                    "file_sha256": run.file_sha256,
                    "sha256": source_digest(dataset.rows),
                    "rows": len(dataset.rows),
                    "headers": dataset.headers,
                    "profile": self._source_profile(run),
                    "requires_original": run.target_type in {"knowledge", "attendance"},
                    "loaded_at": utcnow().isoformat(),
                    "expires_at": source_expires_at
                    or (created_at + timedelta(days=90)).isoformat(),
                },
            }
        )
        run.total_rows = len(dataset.rows)
        run.source_features_json = dump_json(dataset.source_features)
        run.summary_json = dump_json(summary)
        run.stage = "source_loaded"
        run.progress = 20
        db.commit()

    def _execution_upload(self, db: Session, run: EtlRun, owner_user_id: int) -> EtlUpload:
        snapshot = self._load_source_snapshot(db, run)
        if snapshot is not None:
            snapshot.close()
        if snapshot is not None and run.target_type not in {"knowledge", "attendance"}:
            return cast("EtlUpload", self._owned_upload_record(db, run.upload_id, owner_user_id))
        return cast("EtlUpload", self._owned_upload(db, run.upload_id, owner_user_id))
