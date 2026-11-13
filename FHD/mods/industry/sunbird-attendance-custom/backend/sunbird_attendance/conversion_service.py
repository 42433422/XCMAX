"""Coordinate parsing, owner-policy scope and workbook delivery."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.mod_sdk.errors import RECOVERABLE_ERRORS

from .header_resolver import llm_enabled_by_env
from .parser import AttendanceDayRecord, ParsedAttendanceWorkbook
from .roster_identity import PersonnelRoster
from .rules import attendance_policy_scope
from .workbook_writer import AttendanceWorkbookWriter

logger = logging.getLogger(__name__)


class AttendanceParser(Protocol):
    def __call__(
        self, path: Path, /, *, month: str | None, header_row: int, use_llm: bool
    ) -> ParsedAttendanceWorkbook: ...


@dataclass(frozen=True)
class AttendanceConversionService:
    writer: AttendanceWorkbookWriter
    load_policy: Callable[[], dict[str, Any]]
    parser: AttendanceParser

    def from_records(
        self,
        records: list[AttendanceDayRecord],
        output_path: str | Path,
        *,
        template_path: str | Path,
        month_label: str,
        personnel_roster: PersonnelRoster | None = None,
    ) -> dict[str, Any]:
        if not records:
            return {"success": False, "error": "no attendance records"}
        try:
            with attendance_policy_scope(self.load_policy()):
                result = self.writer.write(
                    records, Path(output_path), Path(template_path), month_label, personnel_roster
                )
                result.update(
                    input="database", rows_in=len(records), header_info=None, used_llm=False
                )
                return result
        except RECOVERABLE_ERRORS as exc:
            logger.exception("Attendance conversion from record list failed")
            return {"success": False, "error": str(exc)}

    def from_file(
        self,
        input_path: str,
        output_path: str | None = None,
        *,
        template_path: str | None = None,
        month: str | None = None,
        header_row: int = 0,
        use_llm: bool | None = None,
        personnel_roster: PersonnelRoster | None = None,
    ) -> dict[str, Any]:
        if use_llm is None:
            use_llm = llm_enabled_by_env()
        src = Path(input_path)
        if not src.exists():
            return {"success": False, "error": "input file not found"}
        out = Path(output_path) if output_path else src.with_name(src.stem + "_converted.xlsx")
        template = Path(template_path) if template_path else out if out.exists() else None
        try:
            with attendance_policy_scope(self.load_policy()):
                parsed = self.parser(
                    src, month=month, header_row=max(0, int(header_row or 0)), use_llm=bool(use_llm)
                )
                result = self.writer.write(
                    parsed.records, out, template, month or parsed.month, personnel_roster
                )
                if not result.get("success"):
                    return result
                header = parsed.daily_header
                header_info = (
                    {
                        "header_row": header.header_row,
                        "data_start_row": header.data_start_row,
                        "source": header.source,
                        "columns": header.columns,
                        "clock_time_columns": header.clock_time_columns,
                        "leave_columns": header.leave_columns,
                    }
                    if header is not None
                    else None
                )
                result.update(
                    input=str(src),
                    rows_in=parsed.rows_in,
                    header_info=header_info,
                    used_llm=bool(use_llm),
                )
                return result
        except RECOVERABLE_ERRORS as exc:
            logger.exception("Attendance conversion failed")
            return {"success": False, "error": str(exc)}
