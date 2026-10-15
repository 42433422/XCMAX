"""Confirmed ETL execution, retry, and rollback operations."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict, EtlError
from app.application.etl.operation_owner import (
    OperationOwner,
    activate_operation,
    bind_owner,
    claim_operation,
    fail_operation,
    finish_operation,
    unbind_owner,
)
from app.application.etl.parsers import MAX_ROWS
from app.application.etl.service_rollback import RollbackServiceMixin
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
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class ExecutionServiceMixin(RollbackServiceMixin):
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
        operation = claim_operation(
            db,
            run,
            "execute_queue",
            allowed_statuses={"preview_ready"},
            require_unrolled_back=True,
        )
        bind_owner(db, operation)
        run.status = "executing"
        run.stage = "executing"
        run.progress = 0
        run.confirmed_at = utcnow()
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        unbind_owner(db)
        try:
            self._submit_execution(
                run.id, tenant_id, owner_user_id, valid_rows_only, operation_token=operation.token
            )
        except RECOVERABLE_ERRORS as exc:
            code, message = safe_error(exc)
            fail_operation(db, operation, code=code, message=message)
            raise
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run.id, owner_user_id=owner_user_id))

    def _submit_execution(
        self,
        run_id: str,
        tenant_id: int,
        owner_user_id: int,
        valid_rows_only: bool,
        *,
        operation_token: str | None = None,
    ) -> None:
        with SUBMITTED_LOCK:
            if run_id in SUBMITTED and operation_token is None:
                return
            SUBMITTED.add(run_id)

        def work() -> None:
            try:
                with tenant_scope(tenant_id):
                    self._execute_worker(
                        run_id, owner_user_id, valid_rows_only, operation_token=operation_token
                    )
            finally:
                with SUBMITTED_LOCK:
                    SUBMITTED.discard(run_id)

        EXECUTOR.submit(work)

    def _execute_worker(
        self,
        run_id: str,
        owner_user_id: int,
        valid_rows_only: bool,
        *,
        operation_token: str | None = None,
    ) -> None:
        db = new_session()
        started_at = time.monotonic()
        operation: OperationOwner | None = None
        external_started = False
        try:
            run = self._owned_run(db, run_id, owner_user_id)
            adapter = get_adapter(run.target_type)
            batch_executor = getattr(adapter, "execute_batch", None)
            # Row adapters inherit a rejecting batch stub; only an implementation
            # override may enter the external-effect path.
            uses_batch = (
                callable(batch_executor)
                and getattr(batch_executor, "__func__", batch_executor)
                is not TargetAdapter.execute_batch
            )
            kind = "batch_execute" if uses_batch else "execute"
            operation = (
                activate_operation(db, run, kind, operation_token)
                if operation_token
                else claim_operation(
                    db, run, kind, allowed_statuses={"executing"}, require_unrolled_back=True
                )
            )
            bind_owner(db, operation)
            db.commit()
            upload = self._owned_upload(db, run.upload_id, owner_user_id)
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
                    EtlRunRow.execution_status.not_in(["success", "rolled_back"]),
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
            if uses_batch:
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

                external_started = True
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
            finish_operation(db, operation)
            db.commit()
            self._record_execution_metrics(run, started_at, "success")
        except BOUNDARY_ERRORS as exc:  # Task boundary; external effects retain unknown status.
            db.rollback()
            code, message = safe_error(exc)
            try:
                if operation is not None and fail_operation(
                    db, operation, code=code, message=message, outcome_unknown=external_started
                ):
                    run = self._owned_run(db, run_id, owner_user_id)
                    self._record_execution_metrics(run, started_at, "failed")
            except RECOVERABLE_ERRORS:  # noqa: BLE001
                db.rollback()
                logger.exception("Unable to persist ETL execution failure for %s", run_id)
        finally:
            unbind_owner(db)
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
                        "preview_before": load_json(row.before_json, {}),
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
                if isinstance(exc, EtlError) and exc.code == "ETL_OPERATION_LEASE_LOST":
                    db.rollback()
                    raise
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
                        "preview_before": load_json(completed_row.before_json, {}),
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
        operation = claim_operation(
            db,
            run,
            "preview_queue",
            allowed_statuses={"failed", "interrupted"},
            require_unrolled_back=True,
        )
        bind_owner(db, operation)
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
        unbind_owner(db)
        try:
            from app.utils.metrics import etl_retries_total

            etl_retries_total.labels(run.target_type).inc()
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.debug("ETL retry metrics unavailable", exc_info=True)
        if rerun_parse:
            self._submit_preview(run_id, tenant_id, owner_user_id, operation_token=operation.token)
        else:
            self._submit_revalidation(
                run_id, tenant_id, owner_user_id, operation_token=operation.token
            )
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run_id, owner_user_id=owner_user_id))
