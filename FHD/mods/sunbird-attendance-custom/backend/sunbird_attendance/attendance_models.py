"""Attendance projections shared by calculation and workbook writers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass
class DayBandEntry:
    symbol: str
    value: float


@dataclass
class EmployeeDayTemplateData:
    work_date: date
    morning: list[DayBandEntry] = field(default_factory=list)
    afternoon: list[DayBandEntry] = field(default_factory=list)
    night: list[DayBandEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class EmployeeMonthTemplateData:
    employee_name: str
    attendance_group: str
    department: str
    employee_no: str
    days: dict[int, EmployeeDayTemplateData] = field(default_factory=dict)
    normal_hours: float = 0.0
    weekday_overtime_hours: float = 0.0
    sunday_overtime_hours: float = 0.0
    leave_hours: float = 0.0
    absent_hours: float = 0.0
    late_count: float = 0.0
    early_count: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class TemplateWriteResult:
    matched_employee_count: int
    unmatched_employee_names: list[str]


@dataclass(frozen=True)
class TemplateEmployeeProfile:
    employee_name: str
    base_row: int
    department: str
    nature_text: str
    block_values: tuple[float, float, float, float]
    overtime_start: time
    morning_work_start: time | None = None
