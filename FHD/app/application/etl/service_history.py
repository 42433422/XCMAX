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
        details = self._live_document_route_details(db, run)
        return self.run_dict(
            run,
            file_name=upload.file_name,
            batch_id=upload.batch_id,
            relative_path=upload.relative_path,
            details=details,
        )

    @staticmethod
    def _live_document_route_details(db: Session, run: EtlRun) -> dict[str, Any]:
        """Overlay workbook route snapshots with their current child-run state."""

        details = load_json(run.summary_json, {})
        routes = details.get("document_routes") if isinstance(details, dict) else None
        root_run_id = str(details.get("workbook_root_run_id") or "").strip()
        if not isinstance(routes, list) or root_run_id != str(run.id):
            return details

        route_run_ids = {
            str(route.get("run_id") or "").strip()
            for route in routes
            if isinstance(route, dict) and str(route.get("run_id") or "").strip()
        }
        if not route_run_ids:
            return details
        live_runs = {
            child.id: child
            for child in db.query(EtlRun)
            .filter(
                EtlRun.id.in_(route_run_ids),
                EtlRun.tenant_id == run.tenant_id,
                EtlRun.owner_user_id == run.owner_user_id,
            )
            .all()
        }
        refreshed_routes: list[Any] = []
        for route in routes:
            if not isinstance(route, dict):
                refreshed_routes.append(route)
                continue
            child = live_runs.get(str(route.get("run_id") or "").strip())
            if child is None:
                refreshed_routes.append(route)
                continue
            refreshed_routes.append(
                {
                    **route,
                    "status": child.status,
                    "stage": child.stage,
                    "progress": int(child.progress or 0),
                    "total_rows": int(child.total_rows or 0),
                    "summary": {
                        "new": int(child.new_rows or 0),
                        "update": int(child.update_rows or 0),
                        "skip": int(child.skip_rows or 0),
                        "error": int(child.error_rows or 0),
                    },
                    "error": (
                        {"code": child.error_code, "message": child.error_message}
                        if child.error_code
                        else None
                    ),
                    "updated_at": child.updated_at.isoformat() if child.updated_at else None,
                }
            )
        details["document_routes"] = refreshed_routes
        details["document_route"] = next(
            (
                route
                for route in refreshed_routes
                if isinstance(route, dict) and str(route.get("run_id") or "") == str(run.id)
            ),
            details.get("document_route"),
        )
        return details

    def list_runs(
        self,
        db: Session,
        *,
        owner_user_id: int,
        limit: int = 50,
        batch_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.cleanup_retention(db, owner_user_id=owner_user_id)
        query = db.query(EtlRun).filter(EtlRun.owner_user_id == owner_user_id)
        if batch_id:
            query = query.join(EtlUpload, EtlUpload.id == EtlRun.upload_id).filter(
                EtlUpload.owner_user_id == owner_user_id,
                EtlUpload.batch_id == batch_id,
            )
        rows = query.order_by(EtlRun.created_at.desc()).limit(min(max(limit, 1), 500)).all()
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
        uploads = {
            upload.id: upload
            for upload in db.query(EtlUpload)
            .filter(
                EtlUpload.owner_user_id == owner_user_id,
                EtlUpload.id.in_(upload_ids),
            )
            .all()
        }
        result: list[dict[str, Any]] = []
        for run in rows:
            upload = uploads.get(run.upload_id)
            result.append(
                self.run_dict(
                    run,
                    file_name=upload.file_name if upload else None,
                    batch_id=upload.batch_id if upload else None,
                    relative_path=upload.relative_path if upload else None,
                )
            )
        return result

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

    def run_dict(
        self,
        run: EtlRun,
        *,
        file_name: str | None = None,
        batch_id: str | None = None,
        relative_path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        details = details if isinstance(details, dict) else load_json(run.summary_json, {})
        if isinstance(details, dict):
            details.pop("_document_plan", None)
        return {
            "id": run.id,
            "upload_id": run.upload_id,
            "file_name": str(file_name or details.get("file_name") or ""),
            "batch_id": batch_id or details.get("batch_id"),
            "relative_path": str(relative_path or details.get("relative_path") or file_name or ""),
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
