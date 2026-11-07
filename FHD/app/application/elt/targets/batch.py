"""Attendance, export, and webhook batch ETL target adapters."""

from __future__ import annotations

import csv
import itertools
import json
from collections.abc import Iterable
from pathlib import Path
from threading import Event
from typing import Any, cast

from app.application.elt.errors import EltError
from app.application.elt.secrets import read_webhook_secret
from app.application.elt.targets.targets_base import (
    PreviewDecision,
    TargetAdapter,
    TargetField,
    json_safe,
)
from app.application.elt.transforms import neutralize_spreadsheet_formula
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir


class AttendanceAdapter(TargetAdapter):
    type = "attendance"
    label = "考勤"
    reversible = True
    fields = (
        TargetField("employee_name", "员工姓名", required=True, aliases=("姓名", "员工姓名")),
        TargetField("employee_no", "员工编号", aliases=("工号", "员工工号", "员工编号")),
        TargetField("user_id", "用户ID", aliases=("UserId", "用户ID")),
        TargetField("work_date", "日期", type="date", aliases=("日期", "考勤日期", "workDate")),
        TargetField("clock_in", "上班打卡", aliases=("上班1打卡时间", "上班打卡时间", "上班时间")),
        TargetField("clock_out", "下班打卡", aliases=("下班1打卡时间", "下班打卡时间", "下班时间")),
        TargetField("department", "部门", aliases=("部门",)),
        TargetField("attendance_group", "考勤组", aliases=("考勤组",)),
        TargetField("work_month", "考勤月份", aliases=("work_month",)),
        TargetField("days_in_month", "当月天数", type="integer", aliases=("days_in_month",)),
        TargetField("absent_dates", "缺勤日期", aliases=("absent_dates",)),
        TargetField("present_marked_dates", "标记出勤日期", aliases=("present_marked_dates",)),
        TargetField("unmarked_days", "未标记天数", type="integer", aliases=("unmarked_days",)),
        TargetField("month_notes", "月度备注", aliases=("month_notes",)),
        TargetField("business_id", "业务主键", aliases=("business_id",)),
        TargetField("document_path", "考勤文件", aliases=("document_path",)),
    )
    default_match_keys = ("business_id",)

    @staticmethod
    def _source_file_key(context: dict[str, Any]) -> str:
        source_path = Path(str(context["upload_path"]))
        name = str(context.get("file_name") or source_path.name)
        return f"{context['file_sha256']}:{name}"

    @staticmethod
    def _db_path() -> Path:
        return Path(get_app_data_dir()) / "data" / "mod_dbs" / "taiyangniao-pro.db"

    def _existing_batch(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        import sqlite3

        cache = context.get("_preview_cache")
        cache_key = f"attendance_batch:{self._source_file_key(context)}"
        if isinstance(cache, dict) and cache_key in cache:
            return cast("dict[str, Any] | None", cache[cache_key])
        db_path = self._db_path()
        match = None
        if db_path.is_file():
            try:
                with sqlite3.connect(str(db_path)) as conn:
                    row = conn.execute(
                        """
                        SELECT id, rows_written, imported_at
                        FROM attendance_import_batches
                        WHERE source_file = ?
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (self._source_file_key(context),),
                    ).fetchone()
                if row:
                    match = {
                        "batch_id": int(row[0]),
                        "rows_written": int(row[1] or 0),
                        "imported_at": str(row[2] or ""),
                    }
            except sqlite3.OperationalError:
                match = None
        if isinstance(cache, dict):
            cache[cache_key] = match
        return match

    def preview(self, db, data, *, allowed_update_fields, context):
        del db, allowed_update_fields
        source_path = Path(str(context["upload_path"]))
        if source_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            return PreviewDecision(
                "error",
                reason="unsupported_attendance_file",
                issues=[
                    {
                        "code": "ELT_ATTENDANCE_FILE_INVALID",
                        "field": "document_path",
                        "severity": "error",
                        "message": "考勤仅支持 Excel 工作簿",
                    }
                ],
            )
        payload = data if isinstance(data, dict) else {}
        name = str(payload.get("employee_name") or "").strip()
        if not name and not payload.get("business_id"):
            return PreviewDecision(
                "error",
                reason="attendance_row_invalid",
                issues=[
                    {
                        "code": "ELT_REQUIRED_FIELD_MISSING",
                        "field": "employee_name",
                        "severity": "error",
                        "message": "员工姓名不能为空",
                    }
                ],
            )
        business_id = str(payload.get("business_id") or "")
        cache = context.setdefault("_preview_cache", {})
        seen = cache.setdefault("attendance_business_ids", set())
        if business_id and (business_id in seen or self._business_written(business_id)):
            return PreviewDecision(
                "skip",
                match_ref=business_id,
                before={"business_id": business_id},
                after=payload,
                reason="duplicate_attendance_source",
            )
        identity = json.dumps(
            json_safe(
                {k: v for k, v in payload.items() if k not in {"business_id", "document_path"}}
            ),
            sort_keys=True,
            ensure_ascii=False,
        )
        seen_people = cache.setdefault("attendance_identities", set())
        if name and identity in seen_people:
            return PreviewDecision(
                "skip",
                match_ref=business_id,
                after=payload,
                reason="duplicate_attendance_in_source",
            )
        if business_id:
            seen.add(business_id)
        if name:
            seen_people.add(identity)
        return PreviewDecision("new", after=payload, reason="new_attendance_row")

    def _business_written(self, business_id: str) -> bool:
        import sqlite3

        db_path = self._db_path()
        if not db_path.is_file():
            return False
        from app.application.elt.attendance_pipeline import _business_exists

        try:
            with sqlite3.connect(str(db_path)) as conn:
                return _business_exists(conn, business_id)
        except sqlite3.OperationalError:
            return False

    @staticmethod
    def require_complete_selection(
        selected_rows: int, total_rows: int, *, skip_rows: int = 0
    ) -> None:
        del total_rows
        if selected_rows <= 0 and skip_rows <= 0:
            raise EltError(
                "ELT_ATTENDANCE_EMPTY_SELECTION",
                "没有可执行的考勤行；请修正文件并重新预演",
                status_code=409,
            )

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        from app.application.elt.attendance_pipeline import persist_attendance_rows

        source_path = Path(str(context["upload_path"]))
        if source_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise EltError("ELT_ATTENDANCE_FILE_INVALID", "考勤仅支持 Excel 工作簿")
        materialized = [row for row in rows if isinstance(row, dict)]
        self.require_complete_selection(
            len(materialized),
            int(context.get("total_rows") or 0),
            skip_rows=int(context.get("skip_rows") or 0),
        )
        if not materialized:
            from app.application.elt.attendance_pipeline import _write_output

            output = _write_output(str(context["run_id"]), [])
            digest = __import__("hashlib").sha256(output.read_bytes()).hexdigest()
            return {
                "receipt": {
                    "source_file": self._source_file_key(context),
                    "file_name": output.name,
                    "output_path": str(output),
                    "sha256": digest,
                    "executed": 0,
                    "idempotent_replay": True,
                    "product_rows": 0,
                    "customer_rows": 0,
                },
                "executed": 0,
            }
        result = persist_attendance_rows(
            materialized,
            db_path=self._db_path(),
            source_file=self._source_file_key(context),
            upload_path=source_path,
            run_id=str(context["run_id"]),
        )
        callback = context.get("progress_callback")
        if callable(callback):
            callback(int(result["executed"]), max(1, len(materialized)))
        return {"receipt": result, "executed": int(result["executed"])}

    def rollback_batch(self, context: dict[str, Any], receipt: dict[str, Any]) -> int:
        import sqlite3

        source_file = str(receipt.get("source_file") or "")
        db_path = Path(str(receipt.get("db_path") or ""))
        if not source_file or not db_path.is_file():
            raise EltError("ELT_ATTENDANCE_ROLLBACK_DATA_MISSING", "考勤撤销依据不存在")
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("BEGIN")
            deleted = 0
            for statement in (
                "DELETE FROM attendance_daily_records WHERE source_file = ?",
                "DELETE FROM attendance_monthly_marks WHERE source_file = ?",
                "DELETE FROM attendance_employees WHERE source_file = ?",
                "DELETE FROM attendance_departments WHERE source_file = ?",
                "DELETE FROM products WHERE source_file = ?",
                "DELETE FROM customers WHERE source_file = ?",
            ):
                try:
                    cursor = conn.execute(statement, (source_file,))
                    deleted += int(cursor.rowcount or 0)
                except sqlite3.OperationalError:
                    continue
            batch_id = int(receipt.get("batch_id") or 0)
            if batch_id:
                conn.execute("DELETE FROM attendance_import_batches WHERE id = ?", (batch_id,))
            conn.commit()
            return deleted
        except RECOVERABLE_ERRORS:
            conn.rollback()
            raise
        finally:
            conn.close()


class AbnormalAdapter(TargetAdapter):
    """Unconfirmed templates stay abnormal and are not written to a business table."""

    type = "abnormal"
    label = "未确认模板"
    reversible = False
    fields = ()
    default_match_keys = ()

    def preview(self, db, data, *, allowed_update_fields, context):
        del db, data, allowed_update_fields, context
        return PreviewDecision(
            "error",
            reason="unconfirmed_template",
            issues=[
                {
                    "code": "ELT_TEMPLATE_UNCONFIRMED",
                    "field": "template",
                    "severity": "error",
                    "message": "模板未确认，不能强制匹配到业务表",
                }
            ],
        )

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        del rows, context
        raise EltError("ELT_TEMPLATE_UNCONFIRMED", "模板未确认，不能写入")


class ExportAdapter(TargetAdapter):
    reversible = False
    fields = ()
    default_match_keys = ()
    allow_dynamic_fields = True

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        root = Path(get_app_data_dir()).resolve() / "etl" / "exports"
        root.mkdir(parents=True, exist_ok=True)
        suffix = ".csv" if self.type == "export_csv" else ".xlsx"
        path = root / f"etl-{context['run_id']}{suffix}"
        iterator = iter(rows)
        first = next(iterator, None)
        headers = list(context.get("output_headers") or (list(first) if first else []))
        stream = itertools.chain((first,), iterator) if first is not None else iter(())
        total = int(context.get("row_count") or 0)
        executed = 0
        if self.type == "export_csv":
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for executed, row in enumerate(stream, start=1):
                    writer.writerow(
                        {key: neutralize_spreadsheet_formula(row.get(key, "")) for key in headers}
                    )
                    if executed % 500 == 0:
                        callback = context.get("progress_callback")
                        if callable(callback):
                            callback(executed, total)
        else:
            from app.application.elt.result_export import columns_for_export, write_xlsx_result

            materialized = list(stream)
            template = context.get("export_template") or {}
            written = write_xlsx_result(
                path,
                columns=columns_for_export(context, first if isinstance(first, dict) else None),
                rows=[row for row in materialized if isinstance(row, dict)],
                sheet_name=str(template.get("sheet_name") or "业务结果"),
                notes=[str(item) for item in context.get("export_notes") or [] if str(item)],
                progress=context.get("progress_callback"),
                total=total,
            )
            executed = int(written["data_rows"])
            written["download_url"] = f"/api/elt/runs/{context['run_id']}/download"
            callback = context.get("progress_callback")
            return {"receipt": written, "executed": executed}
        callback = context.get("progress_callback")
        if callable(callback):
            callback(executed, total)
        return {
            "receipt": {
                "file_name": path.name,
                "download_url": f"/api/elt/runs/{context['run_id']}/download",
                "reversible": False,
            },
            "executed": executed,
        }


class ExportCsvAdapter(ExportAdapter):
    type = "export_csv"
    label = "CSV 导出"


class ExportXlsxAdapter(ExportAdapter):
    type = "export_xlsx"
    label = "Excel 导出"


class WebhookAdapter(TargetAdapter):
    type = "webhook"
    label = "Webhook"
    reversible = False
    fields = ()
    allow_dynamic_fields = True

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        import httpx

        config = context.get("target_config") or {}
        endpoint = str(config.get("endpoint_url") or "")
        from app.application.elt import targets

        targets._assert_safe_webhook_url(endpoint)
        headers = dict(config.get("headers") or {})
        secret = read_webhook_secret(config.get("secret_ref"))
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        total = int(context.get("row_count") or 0)
        chunk_count = max(1, (total + 499) // 500)
        iterator = iter(rows)
        receipts = []
        executed = 0
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            for index in range(chunk_count):
                chunk = list(itertools.islice(iterator, 500))
                if not chunk and not context.get("connectivity_test"):
                    break
                idempotency_key = f"{context['run_id']}:{index}"
                payload = {
                    "run_id": context["run_id"],
                    "chunk_index": index,
                    "chunk_count": chunk_count,
                    "idempotency_key": idempotency_key,
                    "rows": json_safe(chunk),
                }
                response = None
                for attempt in range(3):
                    try:
                        response = client.post(
                            endpoint,
                            json=payload,
                            headers={**headers, "Idempotency-Key": idempotency_key},
                        )
                        if response.status_code < 500:
                            break
                    except httpx.HTTPError:
                        response = None
                    if attempt < 2:
                        # A bounded interruptible wait keeps retries deterministic
                        # without a hot-path sleep loop.
                        Event().wait(2**attempt)
                if response is None or response.status_code >= 300:
                    raise EltError(
                        "ELT_WEBHOOK_DELIVERY_FAILED",
                        f"Webhook 第 {index + 1} 个分片发送失败",
                        status_code=502,
                    )
                receipts.append({"chunk_index": index, "status_code": response.status_code})
                executed += len(chunk)
                callback = context.get("progress_callback")
                if callable(callback):
                    callback(executed, total)
        return {
            "receipt": {
                "chunks": receipts,
                "reversible": False,
                "executed_rows": executed,
            },
            "executed": executed,
        }
