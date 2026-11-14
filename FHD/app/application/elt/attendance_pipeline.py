"""Attendance ETL stages: slice, then clean, then persist.

Slice only identifies sheet regions and source rows. Clean normalizes fields,
validates them, and assigns the business id. Persist writes attendance tables
and the result workbook. A repeat of the same business id does not insert
another daily row.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

from app.application.elt.errors import EltError
from app.application.elt.parser_types import ParsedDataset, ParsedRow
from app.application.elt.transforms import neutralize_spreadsheet_formula

_DATE_RE = re.compile(r"(20\d{2}|\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
_MONTH_TITLE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月.*考勤")
_EMPLOYEE_NAME_RE = re.compile(r"[\u4e00-\u9fa5·]{2,6}")
_WEEKDAYS = "一二三四五六日"
# Baseline v1 (agreed for monthly mark sheets): a mark is recorded verbatim;
# blank is "unmarked", never inferred as present or absent.
_MARKS = {
    "√": "present_marked",
    "✓": "present_marked",
    "✔": "present_marked",
    "✘": "absent",
    "✗": "absent",
    "×": "absent",
}
_MATRIX_FIELDS = (
    "work_month",
    "days_in_month",
    "absent_dates",
    "present_marked_dates",
    "unmarked_days",
    "month_notes",
)
_HEADER_ALIASES = {
    "employee_name": ("姓名", "员工姓名"),
    "employee_no": ("工号", "员工工号", "员工编号"),
    "user_id": ("userid", "用户id"),
    "work_date": ("日期", "考勤日期", "workdate"),
    "clock_in": ("上班1打卡时间", "上班打卡时间", "上班时间"),
    "clock_out": ("下班1打卡时间", "下班打卡时间", "下班时间"),
    "department": ("部门",),
    "attendance_group": ("考勤组",),
    "position": ("职位", "岗位"),
    "shift_name": ("班次",),
}


def parse_attendance_dataset(path: Path, *, max_rows: int) -> ParsedDataset:
    """Return one cleaned row per non-empty source row. Slice metadata has no business id."""
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    source_size = path.stat().st_size
    uploaded_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    workbook = load_workbook(path, read_only=False, data_only=False)
    rows: list[ParsedRow] = []
    sheet_identity: list[dict[str, Any]] = []
    names = workbook.sheetnames
    primary = next((name for name in ("每日统计", "明细") if name in names), None)
    try:
        for index, sheet in enumerate(workbook.worksheets):
            identity = {
                "name": sheet.title,
                "index": index,
                "state": sheet.sheet_state,
                "order": index,
                "max_row": sheet.max_row,
                "max_column": sheet.max_column,
            }
            sheet_identity.append(identity)
            header_row, columns = _header(sheet)
            if primary and sheet.title != primary:
                identity["status"] = "sliced_not_business_table"
                identity["blank"] = header_row is None and _sheet_blank(sheet)
                continue
            if header_row is None:
                identity["blank"] = _sheet_blank(sheet)
                blocks = [] if identity["blank"] else _matrix_blocks(sheet)
                if blocks:
                    identity["status"] = "identified"
                    identity["template_type"] = "monthly_mark_matrix"
                    identity["regions"] = [block.region() for block in blocks]
                    for block in blocks:
                        for row in block.rows(path.name, source_sha, source_size, uploaded_at):
                            if len(rows) >= max_rows:
                                raise EltError(
                                    "ELT_ROW_LIMIT_EXCEEDED",
                                    f"文件超过 {max_rows} 行限制",
                                    status_code=413,
                                )
                            row.provenance["workbook"]["sheets"] = sheet_identity
                            rows.append(row)
                    continue
                identity["status"] = "blank" if identity["blank"] else "unparsed"
                continue
            identity["blank"] = False
            identity["header_row"] = header_row
            identity["status"] = "identified"
            template = (
                "dingtalk_daily"
                if sheet.title in {"每日统计", "原始记录", "打卡时间"}
                else "attendance_roster"
            )
            header_names = {
                index: _header_text(sheet, header_row, index) for index in columns.values()
            }
            seen: set[str] = set()
            emitted = 0
            for row_number, values in enumerate(
                sheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1
            ):
                if emitted >= max_rows:
                    raise EltError(
                        "ELT_ROW_LIMIT_EXCEEDED", f"文件超过 {max_rows} 行限制", status_code=413
                    )
                if not any(str(value or "").strip() for value in values):
                    continue
                emitted += 1
                raw = {
                    header_names[col]: _text(value)
                    for col, value in enumerate(values)
                    if col in header_names and header_names[col]
                }
                slice_record = {
                    "slice_id": f"{source_sha[:12]}:{sheet.title}:{row_number}",
                    "source_file_id": source_sha,
                    "source_filename": path.name,
                    "source_sha256": source_sha,
                    "source_size": source_size,
                    "uploaded_at": uploaded_at,
                    "sheet": sheet.title,
                    "sheet_index": index,
                    "sheet_state": sheet.sheet_state,
                    "template_type": template,
                    "table_region": _table_region(columns, header_row, row_number),
                    "original_row_range": [row_number, row_number],
                    "status": "identified",
                    "error": None,
                }
                cleaned, issues = _clean(columns, values)
                business_id = ""
                duplicate_status = "unique"
                if not issues:
                    business_id = _business_id(cleaned)
                    duplicate_status = "same_business_key" if business_id in seen else "unique"
                    seen.add(business_id)
                else:
                    slice_record["status"] = "needs_clean"
                rows.append(
                    ParsedRow(
                        sheet=sheet.title,
                        row_number=row_number,
                        values={**raw, **cleaned, "business_id": business_id},
                        provenance={
                            "sheet": sheet.title,
                            "row": row_number,
                            "columns": {key: columns[key] + 1 for key in columns},
                            "slice": slice_record,
                            "clean": {
                                "record_id": slice_record["slice_id"],
                                "business_id": business_id,
                                "mapping_result": {
                                    key: raw.get(header_names.get(columns[key], ""), "")
                                    for key in columns
                                },
                                "cleaning_result": cleaned,
                                "validation_result": issues,
                                "duplicate_status": duplicate_status,
                                "database_status": "pending",
                            },
                            "workbook": {
                                "filename": path.name,
                                "sha256": source_sha,
                                "size": source_size,
                                "uploaded_at": uploaded_at,
                                "sheets": sheet_identity,
                            },
                        },
                    )
                )
    finally:
        workbook.close()
    if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha:
        raise EltError("ELT_SOURCE_HASH_CHANGED", "解析改变了原件哈希")
    unparsed = [item["name"] for item in sheet_identity if item.get("status") == "unparsed"]
    if unparsed and not rows:
        raise EltError(
            "ELT_ATTENDANCE_REGION_UNPARSED",
            "工作表 "
            + "、".join(unparsed)
            + " 有内容但未识别出考勤区域，不能进入确认；请检查表头或版式",
            status_code=422,
        )
    matrix = any(item.get("template_type") == "monthly_mark_matrix" for item in sheet_identity)
    return ParsedDataset(
        headers=[
            "employee_name",
            "employee_no",
            "user_id",
            "work_date",
            "clock_in",
            "clock_out",
            "department",
            "attendance_group",
            *(_MATRIX_FIELDS if matrix else ()),
            "business_id",
        ],
        rows=rows,
        source_features={
            "kind": "attendance_workbook",
            "pipeline": ["slice", "clean", "persist"],
            "stages": {
                "slice": {"business_ids": False, "sheets": sheet_identity},
                "clean": {"business_ids": True, "rows": len(rows)},
            },
            "workbook": {
                "filename": path.name,
                "sha256": source_sha,
                "size": source_size,
                "uploaded_at": uploaded_at,
                "sheet_count": len(sheet_identity),
                "sheets": sheet_identity,
            },
            "structure_detection": "attendance_slice_clean_v1",
        },
        warnings=[
            *(
                warning
                for item in sheet_identity
                for region in item.get("regions") or []
                for warning in region["warnings"]
            ),
            *(
                {
                    "code": "ELT_ATTENDANCE_SHEET_UNPARSED",
                    "sheet": name,
                    "message": f"工作表 {name} 有内容但未识别出考勤区域，未纳入本次预演",
                }
                for name in unparsed
            ),
        ],
    )


def persist_attendance_rows(
    rows: list[dict[str, Any]],
    *,
    db_path: Path,
    source_file: str,
    upload_path: Path,
    run_id: str,
    fault: str | None = None,
) -> dict[str, Any]:
    """Write cleaned rows once, then the workbook. Missing output is a failure."""
    from app.application.attendance_import_app_service import _ensure_schema
    from app.application.elt.attendance_rollback_scope import source_snapshot

    fault = os.environ.get("FHD_ETL_ATTENDANCE_FAULT", "") if fault is None else fault
    db_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_schema(conn)
        _ensure_monthly_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        _, prior_source_rows = source_snapshot(conn, source_file)
        for row in rows:
            issues = row.get("validation_result") or []
            if issues or not str(row.get("employee_name") or "").strip():
                errors.append(
                    {
                        "field": (issues[0].get("field") if issues else "employee_name"),
                        "reason": (issues[0].get("message") if issues else "员工姓名不能为空"),
                        "source_row": row.get("source_row"),
                    }
                )
                continue
            business_id = str(row.get("business_id") or "")
            if not business_id:
                errors.append(
                    {
                        "field": "business_id",
                        "reason": "清洗阶段未生成业务主键",
                        "source_row": row.get("source_row"),
                    }
                )
                continue
            if _business_exists(conn, business_id):
                skipped += 1
                continue
            if row.get("work_date"):
                _insert_daily(conn, row, source_file, business_id)
            elif row.get("work_month"):
                _insert_monthly(conn, row, source_file, business_id)
            _insert_employee(conn, row, source_file)
            if str(row.get("department") or "").strip():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO attendance_departments
                        (source_file, department, main_department, attendance_group)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        source_file,
                        row.get("department") or "",
                        row.get("department") or "",
                        row.get("attendance_group") or "",
                    ),
                )
            written += 1
            output_rows.append(row)
            if fault == "after_first_commit" and written == 1:
                conn.commit()
                raise EltError("ELT_ATTENDANCE_FAULT", "测试注入：首行提交后失败")
        conn.execute(
            """
            INSERT INTO attendance_import_batches
                (source_file, month_label, rows_in, rows_written, imported_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_file,
                "",
                len(rows),
                written,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        batch_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        rollback_digest, _ = source_snapshot(conn, source_file)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise EltError("ELT_ATTENDANCE_PERSIST_FAILED", "考勤写入失败") from exc
    finally:
        conn.close()
    if fault == "skip_output":
        raise EltError("ELT_OUTPUT_MISSING", "考勤结果文件未生成")
    output = _write_output(run_id, _committed_rows(db_path, output_rows))
    if not output.is_file():
        raise EltError("ELT_OUTPUT_MISSING", "考勤结果文件未生成")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "source_file": source_file,
        "db_path": str(db_path),
        "batch_id": batch_id,
        "rollback_scope": {
            "version": 1,
            "run_id": run_id,
            "source_file": source_file,
            "exclusive_source": not prior_source_rows,
            "digest": rollback_digest,
        },
        "executed": written,
        "skipped": skipped,
        "errors": errors,
        "error_rows": len(errors),
        "daily_rows_written": written,
        "product_rows": 0,
        "customer_rows": 0,
        "file_name": output.name,
        "output_path": str(output),
        "sha256": digest,
        "size": output.stat().st_size,
        "download_url": f"/api/elt/runs/{run_id}/download",
    }


def _write_output(run_id: str, rows: list[dict[str, Any]]) -> Path:
    from app.utils.path_io.path_utils import get_app_data_dir

    root = Path(get_app_data_dir()).resolve() / "etl" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"etl-{run_id}.xlsx"
    book = Workbook()
    sheet = book.worksheets[0]
    sheet.title = "考勤结果"
    headers = [
        "员工姓名",
        "员工编号",
        "日期",
        "上班打卡",
        "下班打卡",
        "正班小时",
        "周日加班",
        "晚上加班",
        "业务主键",
        "切片",
        "来源工作表",
        "来源行",
    ]
    sheet.append(headers)
    monthly = [row for row in rows if row.get("work_month")]
    if monthly:
        month_sheet = book.create_sheet("月度考勤")
        month_sheet.append(
            [
                "员工姓名",
                "月份",
                "当月天数",
                "缺勤天数",
                "缺勤日期",
                "标记出勤天数",
                "标记出勤日期",
                "未标记天数",
                "月度备注",
                "业务主键",
                "来源工作表",
                "来源行",
            ]
        )
        for row in monthly:
            absent = [item for item in str(row.get("absent_dates") or "").split(",") if item]
            marked = [
                item for item in str(row.get("present_marked_dates") or "").split(",") if item
            ]
            month_sheet.append(
                [
                    row.get("employee_name") or "",
                    row.get("work_month") or "",
                    int(row.get("days_in_month") or 0),
                    len(absent),
                    ",".join(absent),
                    len(marked),
                    ",".join(marked),
                    int(row.get("unmarked_days") or 0),
                    neutralize_spreadsheet_formula(row.get("month_notes") or ""),
                    row.get("business_id") or "",
                    row.get("source_sheet") or "",
                    row.get("source_row") or "",
                ]
            )
    for row in rows:
        if row.get("work_month"):
            continue
        metrics = _hours(row.get("work_date"), row.get("clock_in"), row.get("clock_out"))
        sheet.append(
            [
                row.get("employee_name") or "",
                row.get("employee_no") or row.get("user_id") or "",
                row.get("work_date") or "",
                row.get("clock_in") or "",
                row.get("clock_out") or "",
                metrics["regular_hours"],
                metrics["sunday_overtime_hours"],
                metrics["night_overtime_hours"],
                row.get("business_id") or "",
                row.get("slice_id") or "",
                row.get("source_sheet") or "",
                row.get("source_row") or "",
            ]
        )
    book.save(path)
    book.close()
    reopened = load_workbook(path, read_only=True)
    try:
        saved = [cell.value for cell in next(reopened.worksheets[0].iter_rows(max_row=1))]
    finally:
        reopened.close()
    if saved != headers:
        path.unlink(missing_ok=True)
        raise EltError("ELT_OUTPUT_INVALID", "考勤结果文件无法按原表头重开")
    return path


def _hours(work_date: str | None, clock_in: str | None, clock_out: str | None) -> dict[str, float]:
    """Weekday windows 08:00–12:00 and 13:30–17:30; Sunday is overtime; night starts at 18:00."""
    parsed_date = _parse_date(work_date or "")
    start = _parse_clock(clock_in or "", parsed_date)
    end = _parse_clock(clock_out or "", parsed_date)
    if parsed_date is None or start is None or end is None or end <= start:
        return {"regular_hours": 0.0, "sunday_overtime_hours": 0.0, "night_overtime_hours": 0.0}
    if parsed_date.weekday() == 6:
        regular = 0.0
        sunday = round((end - start).total_seconds() / 3600.0, 2)
    else:
        regular = round(
            _overlap(start, end, time(8, 0), time(12, 0))
            + _overlap(start, end, time(13, 30), time(17, 30)),
            2,
        )
        sunday = 0.0
    night = 0.0
    night_base = datetime.combine(parsed_date, time(18, 0))
    if end > night_base:
        night = _round_half_hour_with_25_minute_grace((end - night_base).total_seconds() / 3600.0)
    return {
        "regular_hours": regular,
        "sunday_overtime_hours": sunday,
        "night_overtime_hours": night,
    }


def _overlap(start: datetime, end: datetime, window_start: time, window_end: time) -> float:
    left = max(start, datetime.combine(start.date(), window_start))
    right = min(end, datetime.combine(start.date(), window_end))
    if right <= left:
        return 0.0
    return (right - left).total_seconds() / 3600.0


def _round_half_hour_with_25_minute_grace(value: float) -> float:
    if value <= 0:
        return 0.0
    whole = int(value * 2)
    remainder_minutes = (value - (whole / 2)) * 60
    if remainder_minutes >= 25:
        whole += 1
    return round(whole / 2, 2)


def _clean(columns: dict[str, int], values: tuple) -> tuple[dict[str, Any], list[dict]]:
    cleaned = {
        key: _text(values[index]) if index < len(values) else "" for key, index in columns.items()
    }
    cleaned["employee_name"] = cleaned.get("employee_name", "")
    cleaned["work_date"] = _iso_date(cleaned.get("work_date", ""))
    cleaned["clock_in"] = _clock_text(cleaned.get("clock_in", ""))
    cleaned["clock_out"] = _clock_text(cleaned.get("clock_out", ""))
    issues = []
    if not cleaned["employee_name"]:
        issues.append(
            {
                "field": "employee_name",
                "code": "ELT_REQUIRED_FIELD_MISSING",
                "message": "员工姓名不能为空",
            }
        )
    if "work_date" in columns and not cleaned["work_date"]:
        issues.append({"field": "work_date", "code": "ELT_DATE_INVALID", "message": "日期无法识别"})
    return cleaned, issues


def _business_id(cleaned: dict[str, Any]) -> str:
    employee_key = (
        cleaned.get("employee_no") or cleaned.get("user_id") or cleaned.get("employee_name")
    )
    material = f"{employee_key}|{cleaned.get('work_date') or ''}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def _header(sheet) -> tuple[int | None, dict[str, int]]:
    for row_number, row in enumerate(sheet.iter_rows(max_row=15, values_only=True), start=1):
        found: dict[str, int] = {}
        for index, value in enumerate(row):
            token = _text(value).replace(" ", "").lower()
            if not token:
                continue
            for key, aliases in _HEADER_ALIASES.items():
                if key in found:
                    continue
                if token in aliases or token.replace("_", "") in aliases:
                    found[key] = index
        if "employee_name" in found and len(found) >= 2:
            return row_number, found
    return None, {}


def _sheet_blank(sheet) -> bool:
    for row in sheet.iter_rows(max_row=5, max_col=5, values_only=True):
        if any(str(value or "").strip() for value in row):
            return False
    return True


def _header_text(sheet, header_row: int, index: int) -> str:
    for row in sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True):
        if index < len(row) and _text(row[index]):
            return _text(row[index])
    return ""


def _table_region(columns: dict[str, int], header_row: int, row_number: int) -> str:
    if not columns:
        return f"A{header_row}:A{row_number}"
    last = max(columns.values()) + 1
    letter = chr(ord("A") + min(last - 1, 25))
    return f"A{header_row}:{letter}{row_number}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _iso_date(value: str) -> str:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else ""


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    match = _DATE_RE.search(value.replace(" ", ""))
    if not match:
        return None
    year = int(match.group(1))
    if year < 100:
        year += 2000
    try:
        return date(year, int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_clock(value: str, on: date | None) -> datetime | None:
    if not value or on is None:
        return None
    match = re.search(r"(\d{1,2}):(\d{2})", value)
    if not match:
        return None
    try:
        return datetime.combine(on, time(int(match.group(1)), int(match.group(2))))
    except ValueError:
        return None


def _clock_text(value: str) -> str:
    match = re.search(r"(\d{1,2}:\d{2})", value)
    return match.group(1) if match else ""


def _tenant_stamp() -> str:
    from app.infrastructure.tenant_scope import current_tenant_id

    tenant = current_tenant_id()
    return "" if tenant is None else str(tenant)


def _business_exists(conn: sqlite3.Connection, business_id: str) -> bool:
    for query in (
        "SELECT 1 FROM attendance_daily_records WHERE business_id = ?",
        "SELECT 1 FROM attendance_monthly_marks WHERE business_id = ?",
    ):
        try:
            if conn.execute(query, (business_id,)).fetchone():
                return True
        except sqlite3.OperationalError:
            continue
    return False


def _ensure_monthly_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance_monthly_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id TEXT NOT NULL UNIQUE,
            source_file TEXT NOT NULL,
            source_sheet TEXT,
            source_row INTEGER,
            employee_name TEXT NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT '',
            customer_id TEXT NOT NULL DEFAULT '',
            work_month TEXT NOT NULL,
            days_in_month INTEGER NOT NULL,
            absent_dates TEXT NOT NULL DEFAULT '',
            present_marked_dates TEXT NOT NULL DEFAULT '',
            unmarked_days INTEGER NOT NULL,
            month_notes TEXT NOT NULL DEFAULT '',
            imported_at TEXT NOT NULL
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(attendance_monthly_marks)")}
    for column in ("tenant_id", "customer_id"):
        if column not in columns:
            conn.execute(
                f"ALTER TABLE attendance_monthly_marks ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
            )


def _insert_monthly(
    conn: sqlite3.Connection, row: dict[str, Any], source_file: str, business_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO attendance_monthly_marks (
            business_id, source_file, source_sheet, source_row, employee_name, tenant_id,
            customer_id, work_month,
            days_in_month, absent_dates, present_marked_dates, unmarked_days, month_notes,
            imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            business_id,
            source_file,
            row.get("source_sheet") or "",
            int(row.get("source_row") or 0),
            row.get("employee_name") or "",
            _tenant_stamp(),
            str(row.get("customer_id") or ""),
            row.get("work_month") or "",
            int(row.get("days_in_month") or 0),
            row.get("absent_dates") or "",
            row.get("present_marked_dates") or "",
            int(row.get("unmarked_days") or 0),
            row.get("month_notes") or "",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def _committed_rows(db_path: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read written rows back from the committed database, not from the cleaning cache."""
    ids = [
        str(row["business_id"])
        for row in rows
        if row.get("business_id") and (row.get("work_date") or row.get("work_month"))
    ]
    if not ids:
        return rows
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        found: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), 500):
            chunk = (json.dumps(ids[start : start + 500]),)
            for record in conn.execute(
                "SELECT * FROM attendance_monthly_marks "
                "WHERE business_id IN (SELECT value FROM json_each(?))",
                chunk,
            ):
                found[record["business_id"]] = dict(record)
            for record in conn.execute(
                "SELECT business_id, employee_name, employee_no, user_id, work_date, source_row, "
                "daily_times_json FROM attendance_daily_records "
                "WHERE business_id IN (SELECT value FROM json_each(?))",
                chunk,
            ):
                times = json.loads(record["daily_times_json"] or "[]") + [None, None]
                found[record["business_id"]] = {
                    **dict(record),
                    "clock_in": times[0],
                    "clock_out": times[1],
                }
    finally:
        conn.close()
    missing = [business_id for business_id in ids if business_id not in found]
    if missing:
        raise EltError("ELT_OUTPUT_SOURCE_MISSING", f"{len(missing)} 条已写入记录无法从数据库读回")
    return [{**row, **found.get(str(row.get("business_id") or ""), {})} for row in rows]


def _insert_daily(
    conn: sqlite3.Connection, row: dict[str, Any], source_file: str, business_id: str
) -> None:
    times = json.dumps([row.get("clock_in"), row.get("clock_out")], ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO attendance_daily_records (
            source_file, month_label, source_row, employee_name, attendance_group,
            department, employee_no, position, user_id, work_date, shift_name,
            daily_times_json, raw_times_json, all_times_json, leave_hours, absent_days,
            late_count_hint, early_count_hint, missing_card_count, notes_json,
            imported_at, business_id, tenant_id, customer_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, '[]', ?, ?, ?, ?)
        """,
        (
            source_file,
            (row.get("work_date") or "")[:7],
            int(row.get("source_row") or 0),
            row.get("employee_name") or "",
            row.get("attendance_group") or "",
            row.get("department") or "",
            row.get("employee_no") or "",
            row.get("position") or "",
            row.get("user_id") or "",
            row.get("work_date") or "",
            row.get("shift_name") or "",
            times,
            "[]",
            times,
            datetime.now().isoformat(timespec="seconds"),
            business_id,
            _tenant_stamp(),
            str(row.get("customer_id") or ""),
        ),
    )


def _insert_employee(conn: sqlite3.Connection, row: dict[str, Any], source_file: str) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO attendance_employees
            (source_file, employee_name, department, main_department, attendance_group,
             employee_no, position, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_file,
            row.get("employee_name") or "",
            row.get("department") or "",
            row.get("department") or "",
            row.get("attendance_group") or "",
            row.get("employee_no") or "",
            row.get("position") or "",
            row.get("user_id") or "",
        ),
    )


class _MatrixBlock:
    """One month of a mark sheet: title, weekday row, day row, employee rows, remarks."""

    def __init__(self, sheet, title_row: int, year: int, month: int, end_row: int) -> None:
        self.sheet = sheet
        self.title_row = title_row
        self.year = year
        self.month = month
        self.end_row = end_row
        self.day_columns: dict[int, int] = {}
        self.issues: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.mismatched_days: dict[int, str] = {}
        self.employees: list[tuple[int, str]] = []
        self.notes: list[str] = []
        self.note_rows: list[int] = []
        self.blank_rows: list[int] = []
        self.header_rows: list[int] = []

    def region(self) -> dict[str, Any]:
        return {
            "kind": "monthly_mark_matrix",
            "month": f"{self.year:04d}-{self.month:02d}",
            "title_row": self.title_row,
            "header_rows": self.header_rows,
            "employee_rows": [row for row, _name in self.employees],
            "note_rows": self.note_rows,
            "blank_rows": self.blank_rows,
            "range": f"A{self.title_row}:{_column_letter(max(self.day_columns or {1: 0}))}{self.end_row}",
            "issues": self.issues,
            "warnings": self.warnings,
        }

    def rows(self, filename: str, source_sha: str, source_size: int, uploaded_at: str):
        import calendar

        days_in_month = calendar.monthrange(self.year, self.month)[1]
        work_month = f"{self.year:04d}-{self.month:02d}"
        for row_number, name in self.employees:
            cells = {cell.column: cell.value for cell in self.sheet[row_number]}
            absent: list[str] = []
            marked: list[str] = []
            issues = [dict(item) for item in self.issues]
            for column, day in sorted(self.day_columns.items()):
                raw = _text(cells.get(column))
                if not raw:
                    continue
                meaning = _MARKS.get(raw)
                iso = date(self.year, self.month, day).isoformat()
                if day in self.mismatched_days:
                    issues.append(
                        {
                            "field": "absent_dates",
                            "code": "ELT_DATE_AMBIGUOUS",
                            "message": f"{_column_letter(column)}{row_number} 的标记落在"
                            + self.mismatched_days[day],
                        }
                    )
                if meaning == "absent":
                    absent.append(iso)
                elif meaning == "present_marked":
                    marked.append(iso)
                else:
                    issues.append(
                        {
                            "field": "absent_dates",
                            "code": "ELT_ATTENDANCE_MARK_UNKNOWN",
                            "message": f"{_column_letter(column)}{row_number} 标记“{raw}”含义未确认",
                        }
                    )
            cleaned = {
                "employee_name": name,
                "work_month": work_month,
                "days_in_month": days_in_month,
                "absent_dates": ",".join(absent),
                "present_marked_dates": ",".join(marked),
                "unmarked_days": days_in_month - len(absent) - len(marked),
                "month_notes": "；".join(self.notes),
            }
            business_id = (
                "" if issues else _business_id({"employee_name": name, "work_date": work_month})
            )
            slice_id = f"{source_sha[:12]}:{self.sheet.title}:{row_number}"
            yield ParsedRow(
                sheet=self.sheet.title,
                row_number=row_number,
                values={**cleaned, "business_id": business_id},
                provenance={
                    "sheet": self.sheet.title,
                    "row": row_number,
                    "columns": {
                        "employee_name": 1,
                        **{f"day_{day}": column for column, day in self.day_columns.items()},
                    },
                    "slice": {
                        "slice_id": slice_id,
                        "source_file_id": source_sha,
                        "source_filename": filename,
                        "source_sha256": source_sha,
                        "source_size": source_size,
                        "uploaded_at": uploaded_at,
                        "sheet": self.sheet.title,
                        "sheet_state": self.sheet.sheet_state,
                        "template_type": "monthly_mark_matrix",
                        "table_region": self.region()["range"],
                        "original_row_range": [row_number, row_number],
                        "status": "needs_clean" if issues else "identified",
                        "error": None,
                    },
                    "clean": {
                        "record_id": slice_id,
                        "business_id": business_id,
                        "mapping_result": {
                            "employee_name": name,
                            "month_title_row": self.title_row,
                        },
                        "cleaning_result": cleaned,
                        "validation_result": issues,
                        "duplicate_status": "unique",
                        "database_status": "pending",
                    },
                    "workbook": {
                        "filename": filename,
                        "sha256": source_sha,
                        "size": source_size,
                        "uploaded_at": uploaded_at,
                    },
                    "validation_issues": issues,
                },
            )


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(max(1, index))


def _matrix_blocks(sheet) -> list[_MatrixBlock]:
    """Slice a sheet of stacked monthly mark tables; returns [] when the layout is absent."""
    titles: list[tuple[int, int, int]] = []
    last_row = 0
    for row in sheet.iter_rows():
        texts = [(cell, _text(cell.value)) for cell in row if _text(cell.value)]
        if not texts:
            continue
        last_row = row[0].row
        match = _MONTH_TITLE_RE.search(texts[0][1])
        if match and 1 <= int(match.group(2)) <= 12:
            titles.append((row[0].row, int(match.group(1)), int(match.group(2))))
    blocks: list[_MatrixBlock] = []
    for index, (title_row, year, month) in enumerate(titles):
        end_row = titles[index + 1][0] - 1 if index + 1 < len(titles) else last_row
        block = _MatrixBlock(sheet, title_row, year, month, end_row)
        _fill_block(block)
        if block.day_columns and block.employees:
            blocks.append(block)
    return blocks


def _fill_block(block: _MatrixBlock) -> None:
    import calendar

    days_in_month = calendar.monthrange(block.year, block.month)[1]
    weekday_by_column: dict[int, str] = {}
    for row_number in range(block.title_row + 1, block.end_row + 1):
        cells = [(cell.column, cell.value) for cell in block.sheet[row_number]]
        texts = [(column, _text(value)) for column, value in cells if _text(value)]
        if not texts:
            block.blank_rows.append(row_number)
            continue
        days = [
            (column, value)
            for column, value in cells
            if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 31
        ]
        weekdays = [(column, text) for column, text in texts if text in _WEEKDAYS]
        if not block.day_columns and len(days) >= 28:
            block.header_rows.append(row_number)
            block.day_columns = {column: int(value) for column, value in days}
            for column, day in block.day_columns.items():
                if day > days_in_month:
                    block.issues.append(
                        {
                            "field": "work_month",
                            "code": "ELT_DATE_AMBIGUOUS",
                            "message": f"{block.year}年{block.month}月没有{day}日",
                        }
                    )
                expected = _WEEKDAYS[
                    date(block.year, block.month, min(day, days_in_month)).weekday()
                ]
                written = weekday_by_column.get(column)
                if written and written != expected and day <= days_in_month:
                    message = f"{block.month}月{day}日表头写“{written}”，日历为“{expected}”"
                    block.mismatched_days[day] = message + "，需确认日期"
                    block.warnings.append(
                        {
                            "code": "ELT_ATTENDANCE_WEEKDAY_MISMATCH",
                            "month": f"{block.year:04d}-{block.month:02d}",
                            "row": row_number,
                            "message": message,
                        }
                    )
            continue
        if not block.day_columns and len(weekdays) >= 28:
            block.header_rows.append(row_number)
            weekday_by_column = dict(weekdays)
            continue
        first_column, first_text = texts[0]
        side_notes = [text for column, text in texts[1:] if column not in block.day_columns]
        if block.day_columns and first_column <= 2 and _EMPLOYEE_NAME_RE.fullmatch(first_text):
            block.employees.append((row_number, first_text))
            block.notes.extend(side_notes)
            continue
        block.note_rows.append(row_number)
        block.notes.extend(text for _column, text in texts)
