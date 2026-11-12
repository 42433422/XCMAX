"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("sunbird_attendance.convert")


def _build_day_template_data(
    record: _facade().AttendanceDayRecord,
    profile: _facade().TemplateEmployeeProfile,
    *,
    absent_streak: int,
) -> tuple[_facade().EmployeeDayTemplateData, dict[str, float], list[str]]:
    punches = _facade()._unique_sorted(record.all_punch_times())
    day_payload = _facade().EmployeeDayTemplateData(
        work_date=record.work_date, notes=list(record.notes)
    )
    work_intervals = _facade()._work_intervals(punches)
    symbol = _facade()._resolved_day_symbol(record)
    dingtalk_hours = _facade().dingtalk_work_hours_as_hours(record.work_duration_raw)
    late_count = 0.0
    early_count = 0.0
    absent_hours = 0.0
    if not punches:
        fill_from_aggregate = (
            not _facade().is_rest_shift(record.shift_name)
            and record.leave_hours <= 0
            and (dingtalk_hours >= 6.5 or record.attendance_day_hint >= 1.0)
        )
        if fill_from_aggregate:
            reg = _facade()._resolved_day_symbol(record)
            morning, afternoon = _facade()._build_full_day_entries(profile, reg)
            day_payload.morning.extend(morning)
            day_payload.afternoon.extend(afternoon)
            day_payload.notes.append(
                f"dingtalk_aggregate_fill hours≈{dingtalk_hours:g} 出勤={record.attendance_day_hint:g}"
            )
        else:
            absence_symbol = _facade()._absence_symbol(record, absent_streak)
            if absence_symbol:
                morning, afternoon = _facade()._build_full_day_entries(profile, absence_symbol)
                day_payload.morning.extend(morning)
                day_payload.afternoon.extend(afternoon)
                absent_hours = round(sum(e.value for e in morning + afternoon), 2)
    else:
        schedule_ranges: tuple[_facade().TimeRange, ...] = ()
        if len(punches) == 1:
            if _facade().is_rest_shift(record.shift_name) and record.leave_hours <= 0:
                morning, afternoon = ([], [])
            else:
                morning, afternoon = _facade()._build_full_day_entries(profile, symbol)
        elif not work_intervals:
            morning, afternoon = _facade()._build_full_day_entries(profile, symbol)
        else:
            schedule_ranges = _facade().resolve_schedule_ranges(
                record.work_date,
                group_name=record.attendance_group,
                shift_name=record.shift_name,
                has_any_punch=True,
            )
            effective_intervals = (
                _facade()._clip_work_intervals_to_schedule(
                    record.work_date, work_intervals, schedule_ranges
                )
                if schedule_ranges
                else work_intervals
            )
            morning, afternoon = _facade()._interval_entries(effective_intervals, profile, symbol)
            if not morning and (not afternoon):
                if schedule_ranges:
                    pass
                else:
                    morning, afternoon = _facade()._build_full_day_entries(profile, symbol)
        day_payload.morning.extend(morning)
        day_payload.afternoon.extend(afternoon)
        night_symbol = "★" if symbol == "★" else "☆"
        night_entry = _facade()._fixed_night_overtime_entry(
            record.work_date, punches[-1], symbol=night_symbol
        )
        night_total = night_entry.value if night_entry is not None else 0.0
        if night_total > 0:
            day_payload.night.append(_facade().DayBandEntry(symbol=night_symbol, value=night_total))
    metrics = {
        "normal_hours": round(
            sum(e.value for e in day_payload.morning + day_payload.afternoon if e.symbol == "√"),
            2,
        ),
        "weekday_overtime_hours": round(
            sum(
                e.value
                for e in day_payload.morning + day_payload.afternoon + day_payload.night
                if e.symbol == "☆"
            ),
            2,
        ),
        "sunday_overtime_hours": round(
            sum(
                e.value
                for e in day_payload.morning + day_payload.afternoon + day_payload.night
                if e.symbol == "★"
            ),
            2,
        ),
        "leave_hours": round(
            sum(e.value for e in day_payload.morning + day_payload.afternoon if e.symbol == "〇"),
            2,
        ),
        "absent_hours": round(absent_hours, 2),
        "late_count": late_count,
        "early_count": early_count,
    }
    warning_notes: list[str] = []
    if record.missing_card_count:
        warning_notes.append(f"缺卡{record.missing_card_count:g}次")
    if (
        not punches
        and dingtalk_hours < 6.5
        and (record.attendance_day_hint < 1.0)
        and (not record.leave_hours)
        and (not record.absent_days)
    ):
        warning_notes.append("无有效打卡")
    if len(punches) >= 3:
        warning_notes.append(f"去重后打卡{len(punches)}次")
    return (day_payload, metrics, warning_notes)


def _employee_absent_streaks(
    records: list[_facade().AttendanceDayRecord],
) -> dict[tuple[str, _facade().date], int]:
    streaks: dict[tuple[str, _facade().date], int] = {}
    by_name: dict[str, list[_facade().AttendanceDayRecord]] = {}
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
    employees: dict[str, _facade().EmployeeMonthTemplateData], name: str
) -> _facade().EmployeeMonthTemplateData | None:
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
    payload: _facade().EmployeeMonthTemplateData,
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
    employees: dict[str, _facade().EmployeeMonthTemplateData],
    personnel_roster: list[tuple[str, str, str]] | None,
    detail_ws,
) -> list[dict[str, object]]:
    """与「明细」每人块顺序一致：按人员管理名单或模板块自上而下；无钉钉汇总仍输出一行（零值），避免月度统计主表与夜班侧栏断行。"""
    if personnel_roster:
        out: list[dict[str, object]] = []
        for dept, _nature, name in personnel_roster:
            raw_name = str(name).strip() if name is not None else ""
            p = _facade()._lookup_employee(employees, raw_name)
            if p is not None:
                out.append(_facade()._monthly_row_dict_from_payload(p))
            else:
                out.append(_facade()._empty_monthly_row(raw_name, dept=str(dept or "").strip()))
        return out
    out: list[dict[str, object]] = []
    for br in _facade().iter_detail_sheet_block_base_rows(detail_ws):
        raw = detail_ws.cell(br, 3).value
        raw_name = str(raw).strip() if raw not in (None, "") else ""
        dept = str(detail_ws.cell(br, 1).value or "").strip()
        p = _facade()._lookup_employee(employees, raw_name) if raw_name else None
        if p is not None:
            out.append(_facade()._monthly_row_dict_from_payload(p))
        elif raw_name:
            out.append(_facade()._empty_monthly_row(raw_name, dept=dept))
        else:
            out.append(_facade()._empty_monthly_row("", dept=dept))
    return out


def _aggregate_employee_records(
    records: list[_facade().AttendanceDayRecord],
    *,
    template_profiles: dict[str, _facade().TemplateEmployeeProfile],
) -> tuple[dict[str, _facade().EmployeeMonthTemplateData], list[dict[str, object]]]:
    employees: dict[str, _facade().EmployeeMonthTemplateData] = {}
    analysis_rows: list[dict[str, object]] = []
    absent_streaks = _facade()._employee_absent_streaks(records)
    for record in sorted(records, key=lambda r: (r.employee_name, r.work_date)):
        profile = template_profiles.get(record.employee_name) or _facade()._default_profile(record)
        punches = _facade()._unique_sorted(record.all_punch_times())
        month_payload = employees.setdefault(
            record.employee_name,
            _facade().EmployeeMonthTemplateData(
                employee_name=record.employee_name,
                attendance_group=record.attendance_group,
                department=record.department,
                employee_no=record.employee_no,
            ),
        )
        day_payload, metrics, warnings = _facade()._build_day_template_data(
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


def convert_attendance_records(
    records: list[_facade().AttendanceDayRecord],
    output_path: str | _facade().Path,
    *,
    template_path: str | _facade().Path,
    month_label: str,
    personnel_roster: list[tuple[str, str, str]] | None = None,
) -> dict[str, _facade().Any]:
    """将已解析的 ``AttendanceDayRecord`` 列表（如从 SQLite 还原）按与 ``convert_attendance_file`` 相同规则写入明细模板。"""
    out = _facade().Path(output_path)
    template = _facade().Path(template_path)
    if not records:
        return {"success": False, "error": "no attendance records"}
    _facade()._install_owner_policy()
    try:
        workbook = _facade().open_output_workbook(out, template)
        detail_ws = workbook["明细"] if "明细" in workbook.sheetnames else workbook.active
        if personnel_roster:
            _facade().rebuild_detail_sheet_person_blocks(detail_ws, personnel_roster)
        template_profiles = _facade().build_template_profiles(detail_ws)
        if not template_profiles:
            return {
                "success": False,
                "error": "明细页未解析到任何员工块，请检查固定模板或人员管理名单",
            }
        filtered = _facade()._filter_records_to_template_roster(records, template_profiles)
        if not filtered and (not personnel_roster):
            return {
                "success": False,
                "error": "钉钉数据与模板明细中的姓名无交集：请核对模板人员名单与「每日统计」姓名列是否一致（含空格/全半角）。",
            }
        employees, analysis_rows = _facade()._aggregate_employee_records(
            filtered, template_profiles=template_profiles
        )
        monthly_rows = _facade()._build_monthly_rows_for_template(
            employees, personnel_roster, detail_ws
        )
        template_result = _facade().write_detail_sheet(workbook, employees, month_label=month_label)
        _facade().write_monthly_sheet(workbook, monthly_rows, link_detail_side_totals=True)
        _facade()._retain_detail_and_monthly_sheets(workbook)
        output_sheet_names = list(workbook.sheetnames)
        out.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(out)
        workbook.close()
        return {
            "success": True,
            "input": "database",
            "output": str(out),
            "month": month_label,
            "rows_in": len(records),
            "rows_used_for_template": len(filtered),
            "rows_stats": len(analysis_rows),
            "employees_total": len(employees),
            "employees_matched": template_result.matched_employee_count,
            "unmatched_names": template_result.unmatched_employee_names,
            "header_info": None,
            "used_llm": False,
            "personnel_roster_count": len(personnel_roster) if personnel_roster else 0,
            "output_sheet_names": output_sheet_names,
        }
    except _facade().RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("Attendance conversion from record list failed")
        return {"success": False, "error": str(exc)}
    finally:
        _facade()._clear_attendance_policy()
