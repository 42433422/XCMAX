"""Confirmed ETL execution, retry, and rollback operations."""

from __future__ import annotations

import logging
import math
import time
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.application.elt.chat_recall import record_import_origin
from app.application.elt.errors import EltConflict, EltError
from app.application.elt.operation_owner import (
    OWNED_EXECUTE,
    TRANSACTION_ERRORS,
    OperationOwner,
    activate_operation,
    bind_owner,
    claim_operation,
    commit_rows,
    fail_operation,
    fence_operation,
    finish_operation,
    release_transaction,
    row_receipts,
    unbind_owner,
)
from app.application.elt.parsers import MAX_ROWS
from app.application.elt.preview_confirmation import (
    invalidate_preview,
    record_confirmation,
    verify_execution,
    verify_preview,
)
from app.application.elt.service_rollback import RollbackServiceMixin
from app.application.elt.service_support import (
    EXECUTOR,
    dump_json,
    load_json,
    new_session,
    safe_error,
    utcnow,
)
from app.application.elt.targets import TargetAdapter, get_adapter
from app.application.elt.targets.batch import AttendanceAdapter
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_BATCH_RESULT = Draft202012Validator(
    {
        "type": "object",
        "required": ["executed", "receipt"],
        "properties": {
            "executed": {"type": "integer", "minimum": 0},
            "receipt": {"type": "object"},
            "success": {"const": True},
        },
    }
)


def _batch_executed(target: str, result: Any, eligible: int) -> int:
    """A batch must account for every approved row before acknowledging the lot."""
    if not _BATCH_RESULT.is_valid(result):
        raise EltError("ELT_BATCH_RECEIPT_INVALID", "批量执行未返回完整回执，请核对实际结果")
    executed = result["executed"]
    receipt = result["receipt"]
    skipped = (
        receipt.get("duplicates", 0)
        if target == "dynamic_table"
        else (receipt.get("skipped", 0) if target == "attendance" else 0)
    )
    if (
        type(executed) is not int
        or type(skipped) is not int
        or skipped < 0
        or executed + skipped != eligible
        or (
            target == "dynamic_table"
            and (type(receipt.get("inserted")) is not int or receipt["inserted"] != executed)
        )
        or (target == "attendance" and receipt.get("error_rows", 0) != 0)
    ):
        raise EltError("ELT_BATCH_RECEIPT_INVALID", "批量回执行数与确认范围不符，请核对实际结果")
    return cast(int, executed)


def _unconfirmed_mappings(mappings: Any) -> list[dict[str, Any]]:
    """Mappings below a confident match stay out of the warehouse until a person confirms them."""
    if not isinstance(mappings, list):
        return []
    pending: list[dict[str, Any]] = []
    for item in mappings:
        if not isinstance(item, dict) or not str(item.get("source") or "").strip():
            continue
        if item.get("confirmed") is True or "confidence" not in item:
            continue
        try:
            confidence = float(item["confidence"])
        except (TypeError, ValueError):
            pending.append(item)
            continue
        if not math.isfinite(confidence) or not 0.9 <= confidence <= 1:
            pending.append(item)
    return pending


class ExecutionServiceMixin(RollbackServiceMixin):
    if TYPE_CHECKING:
        _owned_run: Any
        _owned_target_config: Any
        _execution_upload: Any
        _load_source_snapshot: Any
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
        preview_revision: str | None = None,
        accept_suggested: bool = False,
        chat_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if not confirmed:
            raise EltError("ELT_CONFIRMATION_REQUIRED", "执行前必须显式确认")
        if run.status != "preview_ready":
            raise EltConflict("ELT_PREVIEW_REQUIRED", "请先完成预演再执行")
        if run.error_rows and not valid_rows_only:
            raise EltConflict(
                "ELT_INVALID_ROWS_BLOCKED",
                "预演存在错误行；默认阻断整批。仅在明确选择“仅写入正确行”后才能继续",
            )
        operation = claim_operation(
            db,
            run,
            "execute_queue",
            allowed_statuses={"preview_ready"},
            require_unrolled_back=True,
        )
        bind_owner(db, operation)
        committed = False
        try:
            # The ownership update locks this run. Read again under that lock,
            # rather than approving a stale ORM snapshot before a concurrent edit.
            db.refresh(run)
            if int(run.total_rows or 0) == 0:
                raise EltConflict("ELT_PREVIEW_EMPTY", "没有识别出可入库的数据，不能确认或入库")
            pending_mappings = _unconfirmed_mappings(
                load_json(run.draft_json, {}).get("field_mappings")
            )
            # 用户一次性接受 AI 建议映射时不逐字段确认；错误行仍按原规则拦截。
            if pending_mappings and not accept_suggested:
                names = "、".join(
                    str(item.get("target") or item.get("source") or "字段")
                    for item in pending_mappings[:8]
                )
                raise EltConflict(
                    "ELT_MAPPING_CONFIRMATION_REQUIRED",
                    f"有歧义的字段尚未确认：{names}。请确认映射后再入库",
                )
            if run.error_rows and not valid_rows_only:
                raise EltConflict(
                    "ELT_INVALID_ROWS_BLOCKED", "预演存在错误行，请核对后明确选择执行范围"
                )
            get_adapter(run.target_type)
            verify_preview(db, run, preview_revision)
            self._execution_upload(db, run, owner_user_id)
            draft = load_json(run.draft_json, {})
            if run.target_type == "webhook":
                self._owned_target_config(
                    db, str(draft.get("target_config_id") or ""), owner_user_id
                )
            if run.target_type == "attendance":
                AttendanceAdapter.require_complete_selection(
                    run.new_rows + run.update_rows,
                    run.total_rows,
                    skip_rows=int(run.skip_rows or 0),
                )
            assert preview_revision is not None
            record_confirmation(run, preview_revision, valid_rows_only=valid_rows_only)
            record_import_origin(run, chat_context)
            run.status = "executing"
            run.stage = "executing"
            run.progress = 0
            run.confirmed_at = utcnow()
            run.error_code = None
            run.error_message = None
            from app.application.elt.audit import record_elt_audit

            record_elt_audit(
                db,
                actor=owner_user_id,
                action="elt_confirm",
                payload={
                    "run_id": run.id,
                    "upload_id": run.upload_id,
                    "file_sha256": run.file_sha256,
                    "target_type": run.target_type,
                    "preview_revision": preview_revision,
                    "valid_rows_only": valid_rows_only,
                    "outcome": "confirmed",
                },
            )
            tenant_id = tenant_id_for_write()
            db.commit()
            committed = True
        finally:
            try:
                # Rejected approval must not leave a durable lease or fail the run.
                if not committed:
                    db.rollback()
            finally:
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
        from app.application.elt.service_background import submit_background

        submit_background(
            self,
            kind="execute",
            run_id=run_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            operation_token=operation_token,
            options={"valid_rows_only": valid_rows_only},
            executor=EXECUTOR,
            session_factory=new_session,
        )

    def _execute_worker(
        self,
        run_id: str,
        owner_user_id: int,
        valid_rows_only: bool,
        *,
        operation_token: str | None = None,
        owned_background: bool = False,
    ) -> None:
        db = new_session()
        started_at = time.monotonic()
        operation: OperationOwner | None = None
        external_started = False
        pending_batch_receipt: str | None = None
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
            kind = (
                OWNED_EXECUTE
                if owned_background
                else "batch_execute"
                if uses_batch or run.target_type == "knowledge"
                else "execute"
            )
            operation = (
                activate_operation(db, run, kind, operation_token)
                if operation_token
                else claim_operation(
                    db, run, kind, allowed_statuses={"executing"}, require_unrolled_back=True
                )
            )
            bind_owner(db, operation)
            db.commit()
            # Recheck after queueing and dispatch using this exact target snapshot.
            target_config = verify_execution(db, run, valid_rows_only=valid_rows_only)
            upload = self._execution_upload(db, run, owner_user_id)
            draft = load_json(run.draft_json, {})

            eligible_filters = (
                EltRunRow.run_id == run.id,
                EltRunRow.owner_user_id == owner_user_id,
                EltRunRow.final_action.in_(["new", "update"]),
                or_(
                    EltRunRow.execution_status.is_(None),
                    EltRunRow.execution_status.not_in(["success", "rolled_back"]),
                ),
            )
            eligible_count = db.query(EltRunRow).filter(*eligible_filters).count()
            if run.target_type == "attendance":
                AttendanceAdapter.require_complete_selection(
                    eligible_count, run.total_rows, skip_rows=int(run.skip_rows or 0)
                )
                run.stage = "persisting"
                db.commit()
            context = self._row_context(run, upload, 0)
            context["skip_rows"] = int(run.skip_rows or 0)
            context["_execution_cache"] = {}
            context["row_count"] = eligible_count
            context["total_rows"] = run.total_rows
            context["output_headers"] = [
                str(item.get("target") or "")
                for item in draft.get("field_mappings") or []
                if str(item.get("target") or "")
            ]
            if run.target_type in {"export_xlsx", "export_csv"}:
                from app.application.elt.result_export import export_context

                features = load_json(run.source_features_json, {})
                first_sheet = (
                    db.query(EltRunRow.source_sheet)
                    .filter(
                        EltRunRow.run_id == run.id,
                        EltRunRow.owner_user_id == owner_user_id,
                    )
                    .order_by(EltRunRow.id)
                    .limit(1)
                    .scalar()
                )
                context.update(export_context(draft, adapter, features, str(first_sheet or "")))
            if target_config:
                context["target_config"] = {
                    "endpoint_url": target_config["endpoint_url"],
                    "headers": target_config["headers"],
                    "secret_ref": target_config["secret_ref"],
                }

            def progress_callback(processed: int, total: int) -> None:
                current = self._owned_run(db, run_id, owner_user_id)
                current.progress = min(99, int(processed / max(1, total) * 100))
                db.commit()

            context["progress_callback"] = progress_callback
            if uses_batch:
                previous = (
                    db.query(EltRunRow)
                    .filter(
                        EltRunRow.run_id == run.id,
                        EltRunRow.owner_user_id == owner_user_id,
                        EltRunRow.execution_status == "success",
                    )
                    .count()
                )

                def normalized_rows():
                    last_id = 0
                    page_size = 500
                    max_pages = (MAX_ROWS + page_size - 1) // page_size + 1
                    for _page_number in range(max_pages):
                        page = (
                            db.query(EltRunRow)
                            .filter(*eligible_filters, EltRunRow.id > last_id)
                            .order_by(EltRunRow.id)
                            .limit(page_size)
                            .all()
                        )
                        if not page:
                            break
                        for row in page:
                            last_id = row.id
                            payload = load_json(row.normalized_json, {})
                            if run.target_type == "attendance" and isinstance(payload, dict):
                                provenance = load_json(row.provenance_json, {})
                                payload = {
                                    **payload,
                                    "source_row": row.source_row,
                                    "source_sheet": row.source_sheet,
                                    "slice_id": (provenance.get("slice") or {}).get("slice_id"),
                                    "validation_result": load_json(row.validation_json, []),
                                }
                            elif run.target_type == "dynamic_table" and isinstance(payload, dict):
                                # 通用表按 sheet / 区块分表：把来源坐标带进批次，适配器据此建多张表。
                                from app.application.elt.targets.dynamic import PARTITION_MARKER

                                provenance = load_json(row.provenance_json, {})
                                payload = {
                                    **payload,
                                    PARTITION_MARKER: {
                                        "sheet": str(row.source_sheet or ""),
                                        "table_id": str(provenance.get("table_id") or ""),
                                        "table_title": str(provenance.get("table_title") or ""),
                                        "table_range": str(provenance.get("table_range") or ""),
                                        "row": int(row.source_row or 0),
                                    },
                                }
                            yield payload

                def persist_batch_receipt(result: dict[str, Any]) -> None:
                    nonlocal pending_batch_receipt
                    # Retain each acknowledgement through a failed first commit,
                    # so the original operation's failure boundary can save it.
                    pending_batch_receipt = dump_json({"batch_result": result})
                    run.receipt_json = pending_batch_receipt
                    db.commit()
                    pending_batch_receipt = None

                context["batch_receipt_callback"] = persist_batch_receipt
                external_started = True
                result = adapter.execute_batch(normalized_rows(), context)
                # Preserve the original acknowledgement even when it fails validation.
                persist_batch_receipt(result)
                executed = _batch_executed(run.target_type, result, eligible_count)
                db.query(EltRunRow).filter(*eligible_filters).update(
                    {
                        EltRunRow.execution_status: "success",
                        EltRunRow.execution_error_code: None,
                        EltRunRow.execution_error_message: None,
                    },
                    synchronize_session=False,
                )
                run.executed_rows = previous + executed
                run.receipt_json = dump_json(result.get("receipt") or {})
                db.commit()
            else:
                eligible = (
                    db.query(EltRunRow).filter(*eligible_filters).order_by(EltRunRow.id).all()
                )
                external_started = run.target_type == "knowledge" and bool(eligible)
                self._execute_rows(
                    db,
                    run,
                    upload,
                    adapter,
                    eligible,
                    set(draft.get("allowed_update_fields") or []),
                    context,
                    operation,
                )
            run = self._owned_run(db, run_id, owner_user_id)
            rows_written = int(run.executed_rows or 0)
            if run.target_type == "attendance":
                receipt_now = load_json(run.receipt_json, {})
                output_path = Path(str(receipt_now.get("output_path") or ""))
                if not output_path.is_file():
                    raise EltError("ELT_OUTPUT_MISSING", "考勤结果文件未生成")
                import hashlib

                actual = hashlib.sha256(output_path.read_bytes()).hexdigest()
                if receipt_now.get("sha256") and receipt_now.get("sha256") != actual:
                    raise EltError("ELT_OUTPUT_HASH_MISMATCH", "考勤结果文件与回执哈希不一致")
            attendance_errors = run.target_type == "attendance" and int(run.error_rows or 0)
            if attendance_errors and int(run.executed_rows or 0):
                run.status = "partial"
                run.stage = "partial"
            elif attendance_errors and not int(run.executed_rows or 0):
                run.status = "failed"
                run.stage = "failed"
            else:
                run.status = "completed"
                run.stage = "completed"
            run.progress = 100
            run.executed_at = utcnow()
            receipt = load_json(run.receipt_json, {})
            stored_entities = load_json(run.summary_json, {}).get("entities")
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
                    "rows_written": bool(rows_written),
                    **(
                        {
                            "entities": {
                                key: int(stored_entities.get(key) or 0)
                                for key in (
                                    "customers",
                                    "purchase_units",
                                    "products",
                                    "records",
                                )
                            }
                        }
                        if isinstance(stored_entities, dict)
                        else {}
                    ),
                }
            )
            if run.target_type == "shipment_records" and run.status in {"completed", "partial"}:
                try:
                    from app.application.elt.shipment_layout_fill import (
                        write_committed_shipment_workbook,
                    )

                    produced = write_committed_shipment_workbook(db, run)
                except BOUNDARY_ERRORS:
                    logger.exception("shipment result workbook skipped for %s", run.id)
                    produced = None
                if produced:
                    receipt.update(produced)
            run.receipt_json = dump_json(receipt)
            from app.application.elt.audit import record_elt_audit

            wrote = int(run.executed_rows or 0)
            if wrote:
                record_elt_audit(
                    db,
                    actor=owner_user_id,
                    action="elt_submit",
                    payload={
                        "run_id": run.id,
                        "upload_id": run.upload_id,
                        "file_sha256": run.file_sha256,
                        "target_type": run.target_type,
                        "outcome": "partial" if run.status != "completed" else "success",
                        "executed_rows": wrote,
                        "executed_at": run.executed_at.isoformat() if run.executed_at else None,
                        "new_rows": run.new_rows,
                        "update_rows": run.update_rows,
                        "skip_rows": run.skip_rows,
                        "error_rows": run.error_rows,
                    },
                )
            if run.status == "failed":
                record_elt_audit(
                    db,
                    actor=owner_user_id,
                    action="elt_exception",
                    payload={
                        "run_id": run.id,
                        "upload_id": run.upload_id,
                        "target_type": run.target_type,
                        "outcome": "failed",
                        "error_code": run.error_code,
                        "executed_rows": wrote,
                    },
                )
            finish_operation(db, operation)
            db.commit()
            self._record_execution_metrics(run, started_at, "success")
        except BOUNDARY_ERRORS as exc:  # Task boundary; external effects retain unknown status.
            released = release_transaction(db)
            code, message = safe_error(exc)
            try:
                if operation is not None:
                    with nullcontext(db) if released else new_session() as failure_db:
                        if failure_db.get_bind() is not db.get_bind() or (
                            not released and failure_db is db
                        ):
                            raise EltError("ELT_OUTCOME_UNKNOWN", "无法核对原执行数据库")
                        if fail_operation(
                            failure_db,
                            operation,
                            code=code,
                            message=message,
                            outcome_unknown=(
                                not released or external_started or code == "ELT_OUTCOME_UNKNOWN"
                            ),
                            receipt_json=pending_batch_receipt,
                        ):
                            run = self._owned_run(failure_db, run_id, owner_user_id)
                            self._record_execution_metrics(run, started_at, "failed")
            except TRANSACTION_ERRORS:
                release_transaction(db)
                logger.exception("Unable to persist ETL execution failure for %s", run_id)
        finally:
            unbind_owner(db)
            try:
                db.close()
            except TRANSACTION_ERRORS:
                logger.exception("Unable to close ETL execution session for %s", run_id)

    @staticmethod
    def _record_execution_metrics(run: EltRun, started_at: float, status: str) -> None:
        try:
            from app.utils.metrics import elt_run_duration_seconds, elt_runs_total

            elt_runs_total.labels("execute", run.target_type, status).inc()
            elt_run_duration_seconds.labels("execute", run.target_type).observe(
                max(0.0, time.monotonic() - started_at)
            )
        except RECOVERABLE_ERRORS:
            logger.debug("ETL execution metrics unavailable", exc_info=True)

    def _execute_rows(
        self,
        db: Session,
        run: EltRun,
        upload: EltUpload,
        adapter: TargetAdapter,
        rows: list[EltRunRow],
        allowed_updates: set[str],
        base_context: dict[str, Any],
        operation: OperationOwner,
    ) -> None:
        executed = run.executed_rows
        total = len(rows)
        external_rows = run.target_type == "knowledge"
        chunk_size = 1 if external_rows else 500
        for chunk_start in range(0, total, chunk_size):
            chunk = rows[chunk_start : chunk_start + chunk_size]
            before = (executed, row_receipts(chunk))
            completed_in_chunk = 0
            # Start the outer SQL transaction before SAVEPOINT, including on
            # SQLite legacy drivers where SAVEPOINT alone does not issue BEGIN.
            fence_operation(db, operation)
            if external_rows:
                # Knowledge owns its own store/transaction. Persist its existing
                # non-reclaimable lease, then release our SQL write lock before
                # calling it. Each acknowledged external row is recorded once.
                db.commit()
            try:
                for row in chunk:
                    context = {
                        **base_context,
                        "source_row": row.source_row,
                        "preview_before": load_json(row.before_json, {}),
                    }
                    with nullcontext() if external_rows else db.begin_nested():
                        result = adapter.execute_row(
                            db,
                            load_json(row.normalized_json, {}),
                            action=row.final_action,
                            match_ref=str(row.match_ref or ""),
                            allowed_update_fields=allowed_updates,
                            context=context,
                        )
                        row.match_ref = str(result.get("match_ref") or row.match_ref or "")
                        row.after_json = dump_json(
                            result.get("after") or load_json(row.after_json, {})
                        )
                        row.execution_status = "success"
                        row.execution_error_code = None
                        row.execution_error_message = None
                    completed_in_chunk += 1
            except TRANSACTION_ERRORS as exc:
                if external_rows:
                    raise  # The worker preserves outcome_unknown; no row replay.
                if isinstance(exc, EltError) and exc.code == "ELT_OPERATION_LEASE_LOST":
                    db.rollback()
                    raise
                code, message = safe_error(exc)
                row.execution_status = "failed"
                row.execution_error_code = code
                row.execution_error_message = message[:500]
                executed += completed_in_chunk
                run.executed_rows = executed
                if executed:
                    if run.executed_at is None:
                        run.executed_at = utcnow()
                    from app.application.elt.audit import record_elt_audit

                    record_elt_audit(
                        db,
                        actor=run.owner_user_id,
                        action="elt_submit",
                        payload={
                            "run_id": run.id,
                            "upload_id": run.upload_id,
                            "file_sha256": run.file_sha256,
                            "target_type": run.target_type,
                            "outcome": "partial",
                            "executed_rows": executed,
                            "executed_at": run.executed_at.isoformat(),
                            "error_code": code,
                            "failed_source_row": row.source_row,
                        },
                    )
                commit_rows(db, run, operation, before, chunk, session_factory=new_session)
                raise
            executed += completed_in_chunk
            run.executed_rows = executed
            run.progress = min(99, int((chunk_start + len(chunk)) / max(1, total) * 100))
            commit_rows(db, run, operation, before, chunk, session_factory=new_session)

    def retry(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.status not in {"failed", "interrupted"}:
            raise EltConflict("ELT_RETRY_NOT_ALLOWED", "当前运行无需重试")
        if run.rollback_status == "completed":
            raise EltConflict("ELT_ALREADY_ROLLED_BACK", "本次运行已经撤销，不能重试")
        source_snapshot = self._load_source_snapshot(db, run)
        if source_snapshot is not None:
            source_snapshot.close()
        operation = claim_operation(
            db,
            run,
            "preview_queue",
            allowed_statuses={"failed", "interrupted"},
            require_unrolled_back=True,
        )
        bind_owner(db, operation)
        db.refresh(run)
        invalidate_preview(run)
        run.status = "previewing"
        # A committed snapshot resumes at transformation; incomplete historical
        # imports must be extracted again, never certified just by their row count.
        rerun_parse = run.executed_rows == 0
        run.stage = (
            "transforming"
            if source_snapshot is not None
            else ("parsing" if rerun_parse else "validating")
        )
        run.progress = 20 if source_snapshot is not None or not rerun_parse else 5
        run.error_code = None
        run.error_message = None
        tenant_id = tenant_id_for_write()
        db.commit()
        unbind_owner(db)
        try:
            from app.utils.metrics import elt_retries_total

            elt_retries_total.labels(run.target_type).inc()
        except RECOVERABLE_ERRORS:
            logger.debug("ETL retry metrics unavailable", exc_info=True)
        if rerun_parse:
            self._submit_preview(run_id, tenant_id, owner_user_id, operation_token=operation.token)
        else:
            self._submit_revalidation(
                run_id, tenant_id, owner_user_id, operation_token=operation.token
            )
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run_id, owner_user_id=owner_user_id))
