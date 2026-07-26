"""Attendance, export, and webhook batch ETL target adapters."""

from __future__ import annotations

import csv
import itertools
from collections.abc import Iterable
from pathlib import Path
from threading import Event
from typing import Any

from app.application.etl.errors import EtlError
from app.application.etl.secrets import read_webhook_secret
from app.application.etl.targets.base import TargetAdapter, TargetField, json_safe
from app.application.etl.transforms import neutralize_spreadsheet_formula
from app.utils.path_utils import get_app_data_dir


class AttendanceAdapter(TargetAdapter):
    type = "attendance"
    label = "考勤"
    reversible = True
    fields = (TargetField("document_path", "考勤文件", aliases=("document_path",)),)
    default_match_keys = ("source_file", "source_row")

    def execute_batch(
        self, rows: Iterable[dict[str, Any]], context: dict[str, Any]
    ) -> dict[str, Any]:
        from app.application.attendance_import_app_service import import_attendance_workbook

        source_path = Path(str(context["upload_path"]))
        if source_path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise EtlError("ETL_ATTENDANCE_FILE_INVALID", "考勤仅支持 Excel 工作簿")
        data_root = Path(get_app_data_dir())
        db_path = data_root / "data" / "mod_dbs" / "taiyangniao-pro.db"
        result = import_attendance_workbook(
            source_path,
            db_path,
            source_file_key=f"{context['file_sha256']}:{source_path.name}",
            sync_ui_tables=True,
        )
        row_count = int(context.get("row_count") or 0)
        callback = context.get("progress_callback")
        if callable(callback):
            callback(row_count, row_count)
        return {"receipt": result, "executed": row_count}

    def rollback_batch(self, context: dict[str, Any], receipt: dict[str, Any]) -> int:
        import sqlite3

        source_file = str(receipt.get("source_file") or "")
        db_path = Path(str(receipt.get("db_path") or ""))
        if not source_file or not db_path.is_file():
            raise EtlError("ETL_ATTENDANCE_ROLLBACK_DATA_MISSING", "考勤撤销依据不存在")
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("BEGIN")
            deleted = 0
            for statement in (
                "DELETE FROM attendance_daily_records WHERE source_file = ?",
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
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


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
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            worksheet = workbook.create_sheet("ETL导出")
            worksheet.append(headers)
            for executed, row in enumerate(stream, start=1):
                worksheet.append(
                    [neutralize_spreadsheet_formula(row.get(key, "")) for key in headers]
                )
                if executed % 500 == 0:
                    callback = context.get("progress_callback")
                    if callable(callback):
                        callback(executed, total)
            workbook.save(path)
            workbook.close()
        callback = context.get("progress_callback")
        if callable(callback):
            callback(executed, total)
        return {
            "receipt": {
                "file_name": path.name,
                "download_url": f"/api/etl/runs/{context['run_id']}/download",
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
        from app.application.etl import targets

        targets._assert_safe_webhook_url(endpoint)
        headers = dict(config.get("headers") or {})
        secret = read_webhook_secret(config.get("secret_ref"))
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        total = int(context.get("row_count") or (len(rows) if hasattr(rows, "__len__") else 0))
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
                    raise EtlError(
                        "ETL_WEBHOOK_DELIVERY_FAILED",
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
