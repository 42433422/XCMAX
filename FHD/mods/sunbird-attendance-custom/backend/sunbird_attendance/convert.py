"""Public convert compatibility exports; implementations own their dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .attendance_day import _absence_symbol as _absence_symbol
from .attendance_day import _append_entry as _append_entry
from .attendance_day import _build_day_template_data as _build_day_template_data
from .attendance_day import _build_full_day_entries as _build_full_day_entries
from .attendance_day import _default_profile as _default_profile
from .attendance_day import _fixed_night_overtime_entry as _fixed_night_overtime_entry
from .attendance_day import _interval_entries as _interval_entries
from .attendance_day import _night_overtime_entry as _night_overtime_entry
from .attendance_day import _profile_blocks as _profile_blocks
from .attendance_day import _regular_symbol as _regular_symbol
from .attendance_day import _resolved_day_symbol as _resolved_day_symbol
from .attendance_day import _symbol_entry as _symbol_entry
from .attendance_intervals import _band_windows as _band_windows
from .attendance_intervals import (
    _clip_work_intervals_to_schedule as _clip_work_intervals_to_schedule,
)
from .attendance_intervals import _hours_between as _hours_between
from .attendance_intervals import _overlap_hours as _overlap_hours
from .attendance_intervals import _primary_interval as _primary_interval
from .attendance_intervals import _round_half_hour as _round_half_hour
from .attendance_intervals import (
    _round_half_hour_with_25_minute_grace as _round_half_hour_with_25_minute_grace,
)
from .attendance_intervals import _round_whole_hour as _round_whole_hour
from .attendance_intervals import (
    _saturday_factory_outside_regular_hours as _saturday_factory_outside_regular_hours,
)
from .attendance_intervals import _time_plus_hours as _time_plus_hours
from .attendance_intervals import _unique_sorted as _unique_sorted
from .attendance_intervals import _work_intervals as _work_intervals
from .attendance_models import DayBandEntry as DayBandEntry
from .attendance_models import EmployeeDayTemplateData as EmployeeDayTemplateData
from .attendance_models import EmployeeMonthTemplateData as EmployeeMonthTemplateData
from .attendance_models import TemplateEmployeeProfile as TemplateEmployeeProfile
from .attendance_month import _aggregate_employee_records as _aggregate_employee_records
from .attendance_month import _build_monthly_rows_for_template as _build_monthly_rows_for_template
from .attendance_month import _employee_absent_streaks as _employee_absent_streaks
from .attendance_month import _empty_monthly_row as _empty_monthly_row
from .attendance_month import (
    _filter_records_to_template_roster as _filter_records_to_template_roster,
)
from .attendance_month import _lookup_employee as _lookup_employee
from .attendance_month import _monthly_row_dict_from_payload as _monthly_row_dict_from_payload
from .conversion_service import AttendanceConversionService
from .detail_sheet import write_detail_sheet as write_detail_sheet
from .monthly_sheet import write_monthly_sheet as write_monthly_sheet
from .parser import AttendanceDayRecord as AttendanceDayRecord
from .parser import dingtalk_work_hours_as_hours as dingtalk_work_hours_as_hours
from .parser import parse_attendance_workbook as parse_attendance_workbook
from .rules import TimeRange as TimeRange
from .rules import is_company_factory_group as is_company_factory_group
from .rules import is_rest_shift as is_rest_shift
from .rules import resolve_schedule_ranges as resolve_schedule_ranges
from .template_layout import iter_detail_sheet_block_base_rows as iter_detail_sheet_block_base_rows
from .template_profiles import build_template_profiles as build_template_profiles
from .template_workbook import open_output_workbook as open_output_workbook
from .template_workbook import (
    rebuild_detail_sheet_person_blocks as rebuild_detail_sheet_person_blocks,
)
from .workbook_writer import AttendanceWorkbookWriter
from .workbook_writer import _retain_detail_and_monthly_sheets as _retain_detail_and_monthly_sheets


def _install_owner_policy() -> None:
    from .owner_config import read_policy
    from .rules import set_attendance_policy

    set_attendance_policy(read_policy())


def _clear_attendance_policy() -> None:
    from .rules import set_attendance_policy

    set_attendance_policy({})


def _conversion_service() -> AttendanceConversionService:
    from .owner_config import read_policy

    return AttendanceConversionService(
        writer=AttendanceWorkbookWriter(open_workbook=open_output_workbook),
        load_policy=read_policy,
        parser=parse_attendance_workbook,
    )


def convert_attendance_records(
    records: list[AttendanceDayRecord],
    output_path: str | Path,
    *,
    template_path: str | Path,
    month_label: str,
    personnel_roster: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """Write stored attendance records with the authenticated owner's policy."""
    return _conversion_service().from_records(
        records,
        output_path,
        template_path=template_path,
        month_label=month_label,
        personnel_roster=personnel_roster,
    )


def convert_attendance_file(
    input_path: str,
    output_path: str | None = None,
    *,
    template_path: str | None = None,
    month: str | None = None,
    header_row: int = 0,
    use_llm: bool | None = None,
    personnel_roster: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """Parse a DingTalk workbook and write the owner's attendance template."""
    return _conversion_service().from_file(
        input_path,
        output_path,
        template_path=template_path,
        month=month,
        header_row=header_row,
        use_llm=use_llm,
        personnel_roster=personnel_roster,
    )
