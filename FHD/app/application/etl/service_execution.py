"""Confirmed ETL execution, retry, and rollback operations."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict, EtlError
from app.application.etl.parsers import MAX_ROWS
from app.application.etl.service_support import (
    EXECUTOR,
    SUBMITTED,
    SUBMITTED_LOCK,
    dump_json,
    load_json,
    new_session,
    safe_error,
    utcnow,
)
from app.application.etl.targets import TargetAdapter, get_adapter
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.infrastructure.tenant_scope import tenant_id_for_write, tenant_scope
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExecutionServiceMixin:
    if TYPE_CHECKING:
        _owned_run: Any
        _owned_target_config: Any
        _owned_upload: Any
        _owned_upload_record: Any
        _row_context: Any
        _submit_preview: Any
        _submit_revalidation: Any
        get_run: Any
        run_dict: Any

    def execute(
        self,
        db: Session,
        *,
        run_id: str,
        owner_user_id: int,
        confirmed: bool,
        valid_rows_only: bool,
    ) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if not confirmed:
            raise EtlError("ETL_CONFIRMATION_REQUIRED", "执行前必须显式确认")
        if run.status != "preview_ready":
            raise EtlConflict("ETL_PREVIEW_REQUIRED", "请先完成预演再执行")
        if run.error_rows and not valid_rows_only:
            raise EtlConflict(
                "ETL_INVALID_ROWS_BLOCKED",
                "预演存在错误行；默认阻断整批。仅在明确选择“仅写入正确行”后才能继续",
            )
        get_adapter(run.target_type)
        self._owned_upload(db, run.upload_id, owner_user_id)
        draft = load_json(run.draft_json, {})
        if run.target_type == "webhook":
            config_id = str(draft.get("target_config_id") or "")
            self._owned_target_config(db, config_id, owner_user_id)
        run.status = "executing"
        run.stage = "executing"
        run.progress = 0
        run.confirmed_at = utcnow()
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        self._submit_execution(run.id, tenant_id, owner_user_id, valid_rows_only)
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run.id, owner_user_id=owner_user_id))

    def _submit_execution(
        self,
        run_id: str,
        tenant_id: int,
        owner_user_id: int,
        valid_rows_only: bool,
    ) -> None:
        with SUBMITTED_LOCK:
            if run_id in SUBMITTED:
                return
            SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._execute_worker(run_id, owner_user_id, valid_rows_only)
            finally:
                with SUBMITTED_LOCK:
                    SUBMITTED.discard(run_id)

        EXECUTOR.submit(work)

    def _execute_worker(
        self,
        run_id: str,
        owner_user_id: int,
        valid_rows_only: bool,
    ) -> None:
        db = new_session()
        started_at = time.monotonic()
        try:
            run = self._owned_run(db, run_id, owner_user_id)
            upload = self._owned_upload(db, run.upload_id, owner_user_id)
            adapter = get_adapter(run.target_type)
            draft = load_json(run.draft_json, {})
            target_config = None
            if run.target_type == "webhook":
                config_id = str(draft.get("target_config_id") or "")
                target_config = self._owned_target_config(db, config_id, owner_user_id)

            eligible_filters = (
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.final_action.in_(["new", "update"]),
                or_(
                    EtlRunRow.execution_status.is_(None),
                    EtlRunRow.execution_status != "success",
                ),
            )
            eligible_count = db.query(EtlRunRow).filter(*eligible_filters).count()
            context = self._row_context(run, upload, 0)
            context["_execution_cache"] = {}
            context["row_count"] = eligible_count
            context["output_headers"] = [
                str(item.get("target") or "")
                for item in draft.get("field_mappings") or []
                if str(item.get("target") or "")
            ]
            if target_config:
                context["target_config"] = {
                    "endpoint_url": target_config.endpoint_url,
                    "headers": load_json(target_config.headers_json, {}),
                    "secret_ref": target_config.secret_ref,
                }

            def progress_callback(processed: int, total: int) -> None:
                current = self._owned_run(db, run_id, owner_user_id)
                current.progress = min(99, int(processed / max(1, total) * 100))
                db.commit()

            context["progress_callback"] = progress_callback
            if hasattr(adapter, "execute_batch"):
                previous = (
                    db.query(EtlRunRow)
                    .filter(
                        EtlRunRow.run_id == run.id,
                        EtlRunRow.owner_user_id == owner_user_id,
                        EtlRunRow.execution_status == "success",
                    )
                    .count()
                )

                def normalized_rows():
                    last_id = 0
                    page_size = 500
                    max_pages = (MAX_ROWS + page_size - 1) // page_size + 1
                    for _page_number in range(max_pages):
                        page = (
                            db.query(EtlRunRow)
                            .filter(*eligible_filters, EtlRunRow.id > last_id)
                            .order_by(EtlRunRow.id)
                            .limit(page_size)
                            .all()
                        )
                        if not page:
                            break
                        for row in page:
                            last_id = row.id
                            yield load_json(row.normalized_json, {})

                result = adapter.execute_batch(normalized_rows(), context)
                db.query(EtlRunRow).filter(*eligible_filters).update(
                    {
                        EtlRunRow.execution_status: "success",
                        EtlRunRow.execution_error_code: None,
                        EtlRunRow.execution_error_message: None,
                    },
                    synchronize_session=False,
                )
                run.executed_rows = previous + int(result.get("executed") or eligible_count)
                run.receipt_json = dump_json(result.get("receipt") or {})
                db.commit()
            else:
                eligible = (
                    db.query(EtlRunRow).filter(*eligible_filters).order_by(EtlRunRow.id).all()
                )
                self._execute_rows(
                    db,
                    run,
                    upload,
                    adapter,
                    eligible,
                    set(draft.get("allowed_update_fields") or []),
                    context,
                )
            run = self._owned_run(db, run_id, owner_user_id)
            run.status = "completed"
            run.stage = "completed"
            run.progress = 100
            run.executed_at = utcnow()
            receipt = load_json(run.receipt_json, {})
            receipt.update(
                {
                    "run_id": run.id,
                    "target_type": run.target_type,
                    "executed_rows": run.executed_rows,
                    "new_rows": run.new_rows,
                    "update_rows": run.update_rows,
                    "skip_rows": run.skip_rows,
                    "error_rows": run.error_rows,
                    "reversible": run.reversible,
                    "partial": bool(valid_rows_only and run.error_rows),
                }
            )
            run.receipt_json = dump_json(receipt)
            db.commit()
            self._record_execution_metrics(run, started_at, "success")
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            db.rollback()
            code, message = safe_error(exc)
            try:
                run = self._owned_run(db, run_id, owner_user_id)
                run.status = "failed"
                run.stage = "failed"
                run.error_code = code
                run.error_message = message[:500]
                db.commit()
                self._record_execution_metrics(run, started_at, "failed")
            except RECOVERABLE_ERRORS:  # noqa: BLE001
                db.rollback()
                logger.exception("Unable to persist ETL execution failure for %s", run_id)
        finally:
            db.close()

    @staticmethod
    def _record_execution_metrics(run: EtlRun, started_at: float, status: str) -> None:
        try:
            from app.utils.metrics import etl_run_duration_seconds, etl_runs_total

            etl_runs_total.labels("execute", run.target_type, status).inc()
            etl_run_duration_seconds.labels("execute", run.target_type).observe(
                max(0.0, time.monotonic() - started_at)
            )
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL execution metrics unavailable", exc_info=True)

    def _execute_rows(
        self,
        db: Session,
        run: EtlRun,
        upload: EtlUpload,
        adapter: TargetAdapter,
        rows: list[EtlRunRow],
        allowed_updates: set[str],
        base_context: dict[str, Any],
    ) -> None:
        executed = run.executed_rows
        total = len(rows)
        for chunk_start in range(0, total, 500):
            chunk = rows[chunk_start : chunk_start + 500]
            completed_in_chunk = 0
            try:
                for row in chunk:
                    context = {
                        **base_context,
                        "source_row": row.source_row,
                    }
                    result = adapter.execute_row(
                        db,
                        load_json(row.normalized_json, {}),
                        action=row.final_action,
                        match_ref=str(row.match_ref or ""),
                        allowed_update_fields=allowed_updates,
                        context=context,
                    )
                    row.match_ref = str(result.get("match_ref") or row.match_ref or "")
                    row.after_json = dump_json(result.get("after") or load_json(row.after_json, {}))
                    row.execution_status = "success"
                    row.execution_error_code = None
                    row.execution_error_message = None
                    completed_in_chunk += 1
                executed += completed_in_chunk
                run.executed_rows = executed
                run.progress = min(99, int((chunk_start + len(chunk)) / max(1, total) * 100))
                db.commit()
            except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
                failed_row_id = row.id
                completed_row_ids = [item.id for item in chunk[:completed_in_chunk]]
                db.rollback()
                code, message = safe_error(exc)
                for completed_row_id in completed_row_ids:
                    completed_row = db.get(EtlRunRow, completed_row_id)
                    if completed_row is None:
                        continue
                    context = {
                        **base_context,
                        "source_row": completed_row.source_row,
                    }
                    result = adapter.execute_row(
                        db,
                        load_json(completed_row.normalized_json, {}),
                        action=completed_row.final_action,
                        match_ref=str(completed_row.match_ref or ""),
                        allowed_update_fields=allowed_updates,
                        context=context,
                    )
                    completed_row.match_ref = str(
                        result.get("match_ref") or completed_row.match_ref or ""
                    )
                    completed_row.after_json = dump_json(
                        result.get("after") or load_json(completed_row.after_json, {})
                    )
                    completed_row.execution_status = "success"
                    completed_row.execution_error_code = None
                    completed_row.execution_error_message = None
                if completed_row_ids:
                    executed += len(completed_row_ids)
                    replay_run = self._owned_run(db, run.id, run.owner_user_id)
                    replay_run.executed_rows = executed
                    db.commit()
                failed_row = db.get(EtlRunRow, failed_row_id)
                if failed_row:
                    failed_row.execution_status = "failed"
                    failed_row.execution_error_code = code
                    failed_row.execution_error_message = message[:500]
                run = self._owned_run(db, run.id, run.owner_user_id)
                run.executed_rows = executed
                db.commit()
                raise

    def retry(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"failed", "interrupted"}:
            raise EtlConflict("ETL_RETRY_NOT_ALLOWED", "当前运行无需重试")
        if run.rollback_status == "completed":
            raise EtlConflict("ETL_ALREADY_ROLLED_BACK", "本次运行已经撤销，不能重试")
        run.status = "previewing"
        rerun_parse = run.executed_rows == 0 and (
            run.total_rows == 0
            or db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
            )
            .count()
            != run.total_rows
        )
        run.stage = "parsing" if rerun_parse else "validating"
        run.progress = 5 if rerun_parse else 20
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        try:
            from app.utils.metrics import etl_retries_total

            etl_retries_total.labels(run.target_type).inc()
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL retry metrics unavailable", exc_info=True)
        if rerun_parse:
            self._submit_preview(run_id, tenant_id, owner_user_id)
        else:
            self._submit_revalidation(run_id, tenant_id, owner_user_id)
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run_id, owner_user_id=owner_user_id))

    def rollback(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"completed", "failed", "interrupted"}:
            raise EtlConflict("ETL_ROLLBACK_NOT_ALLOWED", "当前运行没有可撤销的写入")
        if not run.reversible:
            raise EtlConflict("ETL_TARGET_NOT_REVERSIBLE", "导出和 Webhook 等外部目标不可撤销")
        if run.rollback_status == "completed":
            raise EtlConflict("ETL_ALREADY_ROLLED_BACK", "本次运行已经撤销")
        adapter = get_adapter(run.target_type)
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        rows = (
            db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.execution_status == "success",
            )
            .order_by(EtlRunRow.id.desc())
            .all()
        )
        if not rows:
            raise EtlConflict("ETL_ROLLBACK_EMPTY", "本次运行没有已写入的数据")
        run.rollback_status = "running"
        db.commit()
        try:
            if hasattr(adapter, "rollback_batch"):
                receipt = load_json(run.receipt_json, {})
                deleted = adapter.rollback_batch(
                    self._row_context(run, upload, 0),
                    receipt,
                )
                for row in rows:
                    row.execution_status = "rolled_back"
                run.rollback_status = "completed"
                run.rolled_back_at = utcnow()
                receipt["rollback"] = {
                    "status": "completed",
                    "rows": len(rows),
                    "deleted_records": deleted,
                    "at": run.rolled_back_at.isoformat(),
                }
                run.receipt_json = dump_json(receipt)
                db.commit()
                self._record_rollback_metric(run.target_type, "success")
                return cast("dict[str, Any]", self.run_dict(run, file_name=upload.file_name))
            for row in rows:
                adapter.rollback_row(
                    db,
                    match_ref=str(row.match_ref or ""),
                    before=load_json(row.before_json, {}),
                    after=load_json(row.after_json, {}),
                    context=self._row_context(run, upload, row.source_row),
                )
                row.execution_status = "rolled_back"
                db.commit()
            run = self._owned_run(db, run_id, owner_user_id)
            run.rollback_status = "completed"
            run.rolled_back_at = utcnow()
            receipt = load_json(run.receipt_json, {})
            receipt["rollback"] = {
                "status": "completed",
                "rows": len(rows),
                "at": run.rolled_back_at.isoformat(),
            }
            run.receipt_json = dump_json(receipt)
            db.commit()
            self._record_rollback_metric(run.target_type, "success")
            return cast("dict[str, Any]", self.run_dict(run, file_name=upload.file_name))
        except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
            db.rollback()
            code, message = safe_error(exc)
            run = self._owned_run(db, run_id, owner_user_id)
            run.rollback_status = "failed"
            run.error_code = code
            run.error_message = message[:500]
            db.commit()
            self._record_rollback_metric(run.target_type, "failed")
            raise EtlError(code, message, status_code=500) from exc

    @staticmethod
    def _record_rollback_metric(target_type: str, status: str) -> None:
        try:
            from app.utils.metrics import etl_rollbacks_total

            etl_rollbacks_total.labels(target_type, status).inc()
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL rollback metrics unavailable", exc_info=True)
