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

_DATE_RE = re.compile(r"(20\d{2}|\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
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
            for row_number, values in _data_rows(sheet, header_row):
                if emitted >= max_rows:
                    break
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
                cleaned, issues = _clean(raw, columns, values)
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
    )


def persist_attendance_rows(
    rows: list[dict[str, Any]],
    *,
    db_path: Path,
    source_file: str,
    upload_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Write cleaned rows once, then the workbook. Missing output is a failure."""
    from app.application.attendance_import_app_service import _ensure_schema

    fault = os.environ.get("FHD_ETL_ATTENDANCE_FAULT", "")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_schema(conn)
        conn.execute("BEGIN")
        for index, row in enumerate(rows):
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
        conn.commit()
    except EltError:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise EltError("ELT_ATTENDANCE_PERSIST_FAILED", "考勤写入失败") from exc
    finally:
        conn.close()
    if fault == "skip_output":
        raise EltError("ELT_OUTPUT_MISSING", "考勤结果文件未生成")
    output = _write_output(upload_path, run_id, output_rows)
    if not output.is_file():
        raise EltError("ELT_OUTPUT_MISSING", "考勤结果文件未生成")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "source_file": source_file,
        "db_path": str(db_path),
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


def _write_output(upload_path: Path, run_id: str, rows: list[dict[str, Any]]) -> Path:
    from app.utils.path_io.path_utils import get_app_data_dir

    root = Path(get_app_data_dir()).resolve() / "etl" / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"etl-{run_id}.xlsx"
    book = Workbook()
    sheet = book.active
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
    for row in rows:
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
        saved = [cell.value for cell in next(reopened.active.iter_rows(max_row=1))]
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


def _clean(
    raw: dict[str, str], columns: dict[str, int], values: tuple
) -> tuple[dict[str, Any], list[dict]]:
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


def _data_rows(sheet, header_row: int):
    for row_number, row in enumerate(
        sheet.iter_rows(min_row=header_row + 1, values_only=True),
        start=header_row + 1,
    ):
        yield row_number, tuple(row)


def _sheet_blank(sheet) -> bool:
    for row in sheet.iter_rows(max_row=5, max_col=5, values_only=True):
        if any(str(value or "").strip() for value in row):
            return False
    return True


def _column_name(sheet, header_row: int, index: int) -> str:
    for row in sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True):
        if index < len(row) and _text(row[index]):
            return _text(row[index])
    return ""


def _header_text(sheet, header_row: int, index: int) -> str:
    return _column_name(sheet, header_row, index)


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


def _business_exists(conn: sqlite3.Connection, business_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM attendance_daily_records WHERE business_id = ?",
        (business_id,),
    ).fetchone()
    return row is not None


def _insert_daily(
    conn: sqlite3.Connection, row: dict[str, Any], source_file: str, business_id: str
) -> None:
    conn.execute(
        """
        INSERT INTO attendance_daily_records (
            source_file, month_label, source_row, employee_name, attendance_group,
            department, employee_no, position, user_id, work_date, shift_name,
            daily_times_json, raw_times_json, all_times_json, leave_hours, absent_days,
            late_count_hint, early_count_hint, missing_card_count, notes_json,
            imported_at, business_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, '[]', ?, ?)
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
            json.dumps([row.get("clock_in"), row.get("clock_out")], ensure_ascii=False),
            "[]",
            json.dumps([row.get("clock_in"), row.get("clock_out")], ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
            business_id,
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
