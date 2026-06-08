"""Deprecated shim — re-export from ``taiyangniao_attendance.parser`` (mod-local)."""

from __future__ import annotations

from . import _load_mod_submodule

_mod = _load_mod_submodule("parser")

AttendanceDayRecord = _mod.AttendanceDayRecord
ParsedAttendanceWorkbook = _mod.ParsedAttendanceWorkbook
parse_attendance_workbook = _mod.parse_attendance_workbook
parse_work_date = _mod.parse_work_date
parse_clock_datetime = _mod.parse_clock_datetime
extract_month_label = _mod.extract_month_label

__all__ = [
    "AttendanceDayRecord",
    "ParsedAttendanceWorkbook",
    "parse_attendance_workbook",
    "parse_work_date",
    "parse_clock_datetime",
    "extract_month_label",
]
