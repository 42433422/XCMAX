"""Deprecated shim — re-export from ``taiyangniao_attendance.mapper`` (mod-local)."""

from __future__ import annotations

from . import _load_mod_submodule as _load

_mod = _load("mapper")

for _name in (
    "DayBandEntry",
    "EmployeeDayTemplateData",
    "EmployeeMonthTemplateData",
    "TemplateEmployeeProfile",
    "build_template_profiles",
    "open_output_workbook",
    "write_detail_sheet",
    "write_monthly_sheet",
):
    if hasattr(_mod, _name):
        globals()[_name] = getattr(_mod, _name)

del _name, _load
