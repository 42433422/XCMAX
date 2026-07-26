"""ETL run history, row pagination, and retention."""

from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.service_support import (
    SUBMITTED,
    SUBMITTED_LOCK,
    load_json,
    utcnow,
)
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.utils.path_utils import get_app_data_dir


class HistoryServiceMixin:
    def get_run(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if self._execution_is_stale(run):
            run.status = "interrupted"
            run.stage = "interrupted"
            run.error_code = "ETL_EXECUTION_INTERRUPTED"
            run.error_message = "上次执行被意外中断，请重新预演或重试"
            db.commit()
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        return self.run_dict(run, file_name=upload.file_name)

    def list_runs(
        self, db: Session, *, owner_user_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        self.cleanup_retention(db, owner_user_id=owner_user_id)
        rows = (
            db.query(EtlRun)
            .filter(EtlRun.owner_user_id == owner_user_id)
            .order_by(EtlRun.created_at.desc())
            .limit(min(max(limit, 1), 100))
            .all()
        )
        interrupted = False
        for run in rows:
            if self._execution_is_stale(run):
                run.status = "interrupted"
                run.stage = "interrupted"
                run.error_code = "ETL_EXECUTION_INTERRUPTED"
                run.error_message = "上次执行被意外中断，请重新预演或重试"
                interrupted = True
        if interrupted:
            db.commit()
        upload_ids = {run.upload_id for run in rows}
        upload_names = {
            upload.id: upload.file_name
            for upload in db.query(EtlUpload)
            .filter(
                EtlUpload.owner_user_id == owner_user_id,
                EtlUpload.id.in_(upload_ids),
            )
            .all()
        }
        return [self.run_dict(run, file_name=upload_names.get(run.upload_id)) for run in rows]

    def cleanup_retention(self, db: Session, *, owner_user_id: int) -> dict[str, int]:
        now = utcnow()
        upload_root = (Path(get_app_data_dir()).resolve() / "etl" / "uploads").resolve()
        removed_files = 0
        expired_uploads = (
            db.query(EtlUpload)
            .filter(
                EtlUpload.owner_user_id == owner_user_id,
                EtlUpload.expires_at.is_not(None),
                EtlUpload.expires_at < now,
                EtlUpload.storage_path != "",
            )
            .all()
        )
        for upload in expired_uploads:
            path = Path(upload.storage_path).resolve()
            if upload_root in path.parents and path.is_file():
                path.unlink(missing_ok=True)
                removed_files += 1
            upload.storage_path = ""

        cutoff = now - timedelta(days=90)
        old_runs = (
            db.query(EtlRun)
            .filter(
                EtlRun.owner_user_id == owner_user_id,
                EtlRun.created_at < cutoff,
            )
            .all()
        )
        old_run_ids = [run.id for run in old_runs]
        removed_rows = 0
        if old_run_ids:
            removed_rows = (
                db.query(EtlRunRow)
                .filter(
                    EtlRunRow.owner_user_id == owner_user_id,
                    EtlRunRow.run_id.in_(old_run_ids),
                )
                .delete(synchronize_session=False)
            )
            for run in old_runs:
                if run.reversible and run.rollback_status != "completed":
                    run.reversible = False
                    run.rollback_status = "expired"
        if removed_files or removed_rows or old_runs:
            db.commit()
        return {"removed_upload_files": removed_files, "removed_run_rows": removed_rows}

    @staticmethod
    def _execution_is_stale(run: EtlRun) -> bool:
        if run.status != "executing" or run.updated_at is None:
            return False
        with SUBMITTED_LOCK:
            if run.id in SUBMITTED:
                return False
        updated = run.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return updated < utcnow() - timedelta(minutes=5)

    def run_dict(self, run: EtlRun, *, file_name: str | None = None) -> dict[str, Any]:
        details = load_json(run.summary_json, {})
        return {
            "id": run.id,
            "upload_id": run.upload_id,
            "file_name": str(file_name or details.get("file_name") or ""),
            "file_sha256": run.file_sha256,
            "template_id": run.template_id,
            "template_version_id": run.template_version_id,
            "target_type": run.target_type,
            "status": run.status,
            "stage": run.stage,
            "progress": run.progress,
            "total_rows": run.total_rows,
            "processed_rows": run.processed_rows,
            "summary": {
                "new": run.new_rows,
                "update": run.update_rows,
                "skip": run.skip_rows,
                "error": run.error_rows,
                "executed": run.executed_rows,
            },
            "details": details,
            "source_features": load_json(run.source_features_json, {}),
            "draft": load_json(run.draft_json, {}),
            "receipt": load_json(run.receipt_json, {}),
            "reversible": run.reversible,
            "rollback_status": run.rollback_status,
            "error": (
                {"code": run.error_code, "message": run.error_message} if run.error_code else None
            ),
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "updated_at": run.updated_at.isoformat() if run.updated_at else None,
            "executed_at": run.executed_at.isoformat() if run.executed_at else None,
        }

    def get_rows(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
        page: int,
        page_size: int,
        action: str | None = None,
    ) -> dict[str, Any]:
        self._owned_run(db, run_id, owner_user_id)
        query = db.query(EtlRunRow).filter(
            EtlRunRow.run_id == run_id, EtlRunRow.owner_user_id == owner_user_id
        )
        if action:
            query = query.filter(EtlRunRow.final_action == action)
        total = query.count()
        rows = (
            query.order_by(EtlRunRow.id)
            .offset((max(page, 1) - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "page": max(page, 1),
            "page_size": page_size,
            "total": total,
            "items": [self.row_dict(row) for row in rows],
        }

    def row_dict(self, row: EtlRunRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_sheet": row.source_sheet,
            "source_row": row.source_row,
            "source": load_json(row.source_json, {}),
            "normalized": load_json(row.normalized_json, {}),
            "provenance": load_json(row.provenance_json, {}),
            "validation_issues": load_json(row.validation_json, []),
            "llm_suggestion": load_json(row.llm_suggestion_json, {}),
            "suggested_action": row.suggested_action,
            "final_action": row.final_action,
            "action_overridden": row.action_overridden,
            "match_ref": row.match_ref,
            "before": load_json(row.before_json, {}),
            "after": load_json(row.after_json, {}),
            "execution_status": row.execution_status,
            "execution_error": (
                {
                    "code": row.execution_error_code,
                    "message": row.execution_error_message,
                }
                if row.execution_error_code
                else None
            ),
        }
