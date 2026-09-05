# ruff: noqa: E402, F401
from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from app.mod_sdk.errors import RECOVERABLE_ERRORS

from .mapper import (
    DayBandEntry,
    EmployeeDayTemplateData,
    EmployeeMonthTemplateData,
    TemplateEmployeeProfile,
    build_template_profiles,
    iter_detail_sheet_block_base_rows,
    open_output_workbook,
    rebuild_detail_sheet_person_blocks,
    write_detail_sheet,
    write_monthly_sheet,
)
from .parser import (
    AttendanceDayRecord,
    dingtalk_work_hours_as_hours,
    parse_attendance_workbook,
)
from .rules import (
    TimeRange,
    is_company_factory_group,
    is_rest_shift,
    resolve_schedule_ranges,
)

logger = logging.getLogger(__name__)


from sunbird_attendance.convert_part01 import _absence_symbol as _absence_symbol
from sunbird_attendance.convert_part01 import _append_entry as _append_entry
from sunbird_attendance.convert_part01 import _band_windows as _band_windows
from sunbird_attendance.convert_part01 import _build_full_day_entries as _build_full_day_entries
from sunbird_attendance.convert_part01 import _clear_attendance_policy as _clear_attendance_policy
from sunbird_attendance.convert_part01 import (
    _clip_work_intervals_to_schedule as _clip_work_intervals_to_schedule,
)
from sunbird_attendance.convert_part01 import _default_profile as _default_profile
from sunbird_attendance.convert_part01 import (
    _filter_records_to_template_roster as _filter_records_to_template_roster,
)
from sunbird_attendance.convert_part01 import (
    _fixed_night_overtime_entry as _fixed_night_overtime_entry,
)
from sunbird_attendance.convert_part01 import _hours_between as _hours_between
from sunbird_attendance.convert_part01 import _install_owner_policy as _install_owner_policy
from sunbird_attendance.convert_part01 import _interval_entries as _interval_entries
from sunbird_attendance.convert_part01 import _night_overtime_entry as _night_overtime_entry
from sunbird_attendance.convert_part01 import _overlap_hours as _overlap_hours
from sunbird_attendance.convert_part01 import _primary_interval as _primary_interval
from sunbird_attendance.convert_part01 import _profile_blocks as _profile_blocks
from sunbird_attendance.convert_part01 import _regular_symbol as _regular_symbol
from sunbird_attendance.convert_part01 import _resolved_day_symbol as _resolved_day_symbol
from sunbird_attendance.convert_part01 import (
    _retain_detail_and_monthly_sheets as _retain_detail_and_monthly_sheets,
)
from sunbird_attendance.convert_part01 import _round_half_hour as _round_half_hour
from sunbird_attendance.convert_part01 import (
    _round_half_hour_with_25_minute_grace as _round_half_hour_with_25_minute_grace,
)
from sunbird_attendance.convert_part01 import _round_whole_hour as _round_whole_hour
from sunbird_attendance.convert_part01 import (
    _saturday_factory_outside_regular_hours as _saturday_factory_outside_regular_hours,
)
from sunbird_attendance.convert_part01 import _symbol_entry as _symbol_entry
from sunbird_attendance.convert_part01 import _time_plus_hours as _time_plus_hours
from sunbird_attendance.convert_part01 import _unique_sorted as _unique_sorted
from sunbird_attendance.convert_part01 import _work_intervals as _work_intervals
from sunbird_attendance.convert_part02 import (
    _aggregate_employee_records as _aggregate_employee_records,
)
from sunbird_attendance.convert_part02 import _build_day_template_data as _build_day_template_data
from sunbird_attendance.convert_part02 import (
    _build_monthly_rows_for_template as _build_monthly_rows_for_template,
)
from sunbird_attendance.convert_part02 import _employee_absent_streaks as _employee_absent_streaks
from sunbird_attendance.convert_part02 import _empty_monthly_row as _empty_monthly_row
from sunbird_attendance.convert_part02 import _lookup_employee as _lookup_employee
from sunbird_attendance.convert_part02 import (
    _monthly_row_dict_from_payload as _monthly_row_dict_from_payload,
)
from sunbird_attendance.convert_part02 import (
    convert_attendance_records as convert_attendance_records,
)
from sunbird_attendance.convert_part03 import convert_attendance_file as convert_attendance_file
