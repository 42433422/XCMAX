"""Single-owner rollback with resumable row progress and conservative batch recovery."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlConflict, EtlError
from app.application.etl.operation_owner import (
    bind_owner,
    claim_operation,
    fail_operation,
    finish_operation,
    unbind_owner,
)
from app.application.etl.service_support import dump_json, load_json, safe_error, utcnow
from app.db.models.etl import EtlRunRow
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class RollbackServiceMixin:
    if TYPE_CHECKING:
        _owned_run: Any
        _owned_upload_record: Any
        _row_context: Any
        run_dict: Any

    def rollback(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        from app.application.etl import service_execution

        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"completed", "failed", "interrupted"}:
            raise EtlConflict("ETL_ROLLBACK_NOT_ALLOWED", "当前运行没有可撤销的写入")
        if not run.reversible:
            raise EtlConflict("ETL_TARGET_NOT_REVERSIBLE", "导出和 Webhook 等外部目标不可撤销")
        if run.rollback_status == "completed":
            raise EtlConflict("ETL_ALREADY_ROLLED_BACK", "本次运行已经撤销")
        adapter = service_execution.get_adapter(run.target_type)
        upload = self._owned_upload_record(db, run.upload_id, owner_user_id)
        operation = claim_operation(
            db,
            run,
            "batch_rollback" if hasattr(adapter, "rollback_batch") else "rollback",
            allowed_statuses={"completed", "failed", "interrupted"},
        )
        bind_owner(db, operation)
        external_started = False
        try:
            run.rollback_status = "running"
            run.error_code = None
            run.error_message = None
            db.commit()
            row_query = db.query(EtlRunRow).filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
            )
            rows = (
                row_query.filter(EtlRunRow.execution_status == "success")
                .order_by(EtlRunRow.id.desc())
                .all()
            )
            previous = row_query.filter(EtlRunRow.execution_status == "rolled_back").count()
            if not rows and not previous:
                raise EtlConflict("ETL_ROLLBACK_EMPTY", "本次运行没有已写入的数据")
            deleted = None
            if rows and hasattr(adapter, "rollback_batch"):
                # No SQLite write transaction is held over an adapter that owns a
                # separate connection or external side effect. Its token is not reclaimable.
                external_started = True
                deleted = adapter.rollback_batch(
                    self._row_context(run, upload, 0), load_json(run.receipt_json, {})
                )
                for row in rows:
                    row.execution_status = "rolled_back"
            else:
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
                "rows": previous + len(rows),
                "at": run.rolled_back_at.isoformat(),
            }
            if deleted is not None:
                receipt["rollback"]["deleted_records"] = deleted
            run.receipt_json = dump_json(receipt)
            finish_operation(db, operation)
            db.commit()
            self._record_rollback_metric(run.target_type, "success")
            return cast("dict[str, Any]", self.run_dict(run, file_name=upload.file_name))
        except RECOVERABLE_ERRORS as exc:
            code, message = safe_error(exc)
            if fail_operation(
                db, operation, code=code, message=message, outcome_unknown=external_started
            ):
                self._record_rollback_metric(run.target_type, "failed")
            if external_started:
                raise EtlError(
                    "ETL_OUTCOME_UNKNOWN",
                    "外部批处理撤销结果无法确认，已停止自动重试，请核对实际结果后人工处理",
                    status_code=409,
                ) from exc
            if isinstance(exc, EtlError):
                raise
            raise EtlError(code, message, status_code=500) from exc
        finally:
            unbind_owner(db)

    @staticmethod
    def _record_rollback_metric(target_type: str, status: str) -> None:
        try:
            from app.utils.metrics import etl_rollbacks_total

            etl_rollbacks_total.labels(target_type, status).inc()
        except RECOVERABLE_ERRORS:
            logger.debug("ETL rollback metrics unavailable", exc_info=True)
