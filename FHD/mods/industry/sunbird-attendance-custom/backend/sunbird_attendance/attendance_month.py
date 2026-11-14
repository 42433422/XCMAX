"""Aggregate daily attendance and project the template roster month."""

from __future__ import annotations

from datetime import date

from .attendance_day import _build_day_template_data, _default_profile
from .attendance_intervals import _unique_sorted
from .attendance_models import EmployeeMonthTemplateData, TemplateEmployeeProfile
from .parser import AttendanceDayRecord
from .template_layout import iter_detail_sheet_block_base_rows


def _filter_records_to_template_roster(
    records: list[AttendanceDayRecord],
    template_profiles: dict[str, TemplateEmployeeProfile],
) -> list[AttendanceDayRecord]:
    """只保留「明细」模板里已有姓名的打卡记录，再按规则聚合；钉钉表其余人员忽略。"""
    if not template_profiles:
        return []
    allowed = {str(k).strip() for k in template_profiles.keys() if str(k).strip()}
    return [r for r in records if (r.employee_name or "").strip() in allowed]


def _employee_absent_streaks(
    records: list[AttendanceDayRecord],
) -> dict[tuple[str, date], int]:
    streaks: dict[tuple[str, date], int] = {}
    by_name: dict[str, list[AttendanceDayRecord]] = {}
    for record in records:
        by_name.setdefault(record.employee_name, []).append(record)
    for name, items in by_name.items():
        streak = 0
        for record in sorted(items, key=lambda r: r.work_date):
            if not record.all_punch_times() and record.absent_days:
                streak += 1
            else:
                streak = 0
            streaks[name, record.work_date] = streak
    return streaks


def _lookup_employee(
    employees: dict[str, EmployeeMonthTemplateData], name: str
) -> EmployeeMonthTemplateData | None:
    key = (name or "").strip()
    if not key:
        return None
    if key in employees:
        return employees[key]
    for ek, ev in employees.items():
        if str(ek).strip() == key:
            return ev
    return None


def _monthly_row_dict_from_payload(
    payload: EmployeeMonthTemplateData,
) -> dict[str, object]:
    return {
        "姓名": payload.employee_name,
        "考勤组": payload.attendance_group,
        "部门": payload.department,
        "工号": payload.employee_no,
        "正常上班": round(payload.normal_hours, 2),
        "平常加班": round(payload.weekday_overtime_hours, 2),
        "星期天加班": round(payload.sunday_overtime_hours, 2),
        "请假": round(payload.leave_hours, 2),
        "旷工": round(payload.absent_hours, 2),
        "迟到": round(payload.late_count, 2),
        "早退": round(payload.early_count, 2),
        "警告": "；".join(sorted(set(payload.warnings))),
    }


def _empty_monthly_row(name: str, dept: str = "", group: str = "") -> dict[str, object]:
    return {
        "姓名": name,
        "考勤组": group,
        "部门": dept,
        "工号": "",
        "正常上班": 0.0,
        "平常加班": 0.0,
        "星期天加班": 0.0,
        "请假": 0.0,
        "旷工": 0.0,
        "迟到": 0.0,
        "早退": 0.0,
        "警告": "",
    }


def _build_monthly_rows_for_template(
    employees: dict[str, EmployeeMonthTemplateData],
    personnel_roster: list[tuple[str, str, str]] | None,
    detail_ws,
) -> list[dict[str, object]]:
    """与「明细」每人块顺序一致：按人员管理名单或模板块自上而下；无钉钉汇总仍输出一行（零值），避免月度统计主表与夜班侧栏断行。"""
    roster = (
        personnel_roster
        if personnel_roster is not None
        else [
            (detail_ws.cell(br, 1).value, "", detail_ws.cell(br, 3).value)
            for br in iter_detail_sheet_block_base_rows(detail_ws)
        ]
    )
    out = []
    for dept, _, name in roster:
        name = str(name or "").strip()
        payload = _lookup_employee(employees, name) if name else None
        out.append(
            _monthly_row_dict_from_payload(payload)
            if payload is not None
            else _empty_monthly_row(name, dept=str(dept or "").strip())
        )
    return out


def _aggregate_employee_records(
    records: list[AttendanceDayRecord],
    *,
    template_profiles: dict[str, TemplateEmployeeProfile],
) -> tuple[dict[str, EmployeeMonthTemplateData], list[dict[str, object]]]:
    employees: dict[str, EmployeeMonthTemplateData] = {}
    analysis_rows: list[dict[str, object]] = []
    absent_streaks = _employee_absent_streaks(records)
    for record in sorted(records, key=lambda r: (r.employee_name, r.work_date)):
        profile = template_profiles.get(record.employee_name) or _default_profile(record)
        punches = _unique_sorted(record.all_punch_times())
        month_payload = employees.setdefault(
            record.employee_name,
            EmployeeMonthTemplateData(
                employee_name=record.employee_name,
                attendance_group=record.attendance_group,
                department=record.department,
                employee_no=record.employee_no,
            ),
        )
        day_payload, metrics, warnings = _build_day_template_data(
            record,
            profile,
            absent_streak=absent_streaks.get((record.employee_name, record.work_date), 0),
        )
        month_payload.days[record.work_date.day] = day_payload
        month_payload.normal_hours += metrics["normal_hours"]
        month_payload.weekday_overtime_hours += metrics["weekday_overtime_hours"]
        month_payload.sunday_overtime_hours += metrics["sunday_overtime_hours"]
        month_payload.leave_hours += metrics["leave_hours"]
        month_payload.absent_hours += metrics["absent_hours"]
        month_payload.late_count += metrics["late_count"]
        month_payload.early_count += metrics["early_count"]
        month_payload.warnings.extend(warnings)
        analysis_rows.append(
            {
                "姓名": record.employee_name,
                "考勤组": record.attendance_group,
                "部门": record.department,
                "日期": record.work_date.isoformat(),
                "班次": record.shift_name,
                "打卡时间": ", ".join(dt.strftime("%H:%M") for dt in punches),
                "正班工时": round(metrics["normal_hours"], 2),
                "平常加班": round(metrics["weekday_overtime_hours"], 2),
                "星期天加班": round(metrics["sunday_overtime_hours"], 2),
                "请假工时": round(metrics["leave_hours"], 2),
                "旷工工时": round(metrics["absent_hours"], 2),
                "迟到次数": round(metrics["late_count"], 2),
                "早退次数": round(metrics["early_count"], 2),
                "备注": "；".join(record.notes + warnings),
            }
        )
    return (employees, analysis_rows)
