"""Apply an employee profile and owner policy to one attendance day."""

from __future__ import annotations

from datetime import date, datetime, time

from .attendance_intervals import (
    _clip_work_intervals_to_schedule,
    _hours_between,
    _overlap_hours,
    _round_half_hour,
    _round_half_hour_with_25_minute_grace,
    _round_whole_hour,
    _time_plus_hours,
    _unique_sorted,
    _work_intervals,
)
from .attendance_models import DayBandEntry, EmployeeDayTemplateData, TemplateEmployeeProfile
from .parser import AttendanceDayRecord, dingtalk_work_hours_as_hours
from .rules import TimeRange, is_rest_shift, resolve_schedule_ranges


def _profile_blocks(
    profile: TemplateEmployeeProfile,
) -> list[tuple[str, time, time, float]]:
    ms = profile.morning_work_start
    if ms is not None:
        t1 = _time_plus_hours(ms, 1.0)
        return [
            ("morning", ms, t1, profile.block_values[0]),
            ("morning", t1, time(12, 0), profile.block_values[1]),
            (
                "afternoon",
                time(13, 30),
                time(15, 30),
                profile.block_values[2],
            ),
            (
                "afternoon",
                time(15, 30),
                time(17, 30),
                profile.block_values[3],
            ),
        ]
    first = profile.block_values[0]
    if first <= 1.0:
        return [
            (
                "morning",
                time(9, 0),
                time(10, 0),
                profile.block_values[0],
            ),
            (
                "morning",
                time(10, 0),
                time(12, 0),
                profile.block_values[1],
            ),
            (
                "afternoon",
                time(13, 30),
                time(15, 30),
                profile.block_values[2],
            ),
            (
                "afternoon",
                time(15, 30),
                time(17, 30),
                profile.block_values[3],
            ),
        ]
    return [
        (
            "morning",
            time(8, 0),
            time(10, 0),
            profile.block_values[0],
        ),
        (
            "morning",
            time(10, 0),
            time(12, 0),
            profile.block_values[1],
        ),
        (
            "afternoon",
            time(13, 30),
            time(15, 30),
            profile.block_values[2],
        ),
        (
            "afternoon",
            time(15, 30),
            time(17, 30),
            profile.block_values[3],
        ),
    ]


def _default_profile(
    record: AttendanceDayRecord,
) -> TemplateEmployeeProfile:
    return TemplateEmployeeProfile(
        employee_name=record.employee_name,
        base_row=-1,
        department=record.department,
        nature_text="",
        block_values=(2.0, 2.0, 2.0, 2.0),
        overtime_start=time(18, 0),
        morning_work_start=None,
    )


def _build_full_day_entries(
    profile: TemplateEmployeeProfile, symbol: str
) -> tuple[list[DayBandEntry], list[DayBandEntry]]:
    morning: list[DayBandEntry] = []
    afternoon: list[DayBandEntry] = []
    blocks = _profile_blocks(profile)
    for band, _start, _end, credit in blocks:
        if credit <= 0:
            continue
        entry = DayBandEntry(symbol=symbol, value=credit)
        if band == "morning":
            morning.append(entry)
        else:
            afternoon.append(entry)
    return (morning, afternoon)


def _interval_entries(
    intervals: list[tuple[datetime, datetime]],
    profile: TemplateEmployeeProfile,
    symbol: str,
) -> tuple[list[DayBandEntry], list[DayBandEntry]]:
    if not intervals:
        return ([], [])
    morning: list[DayBandEntry] = []
    afternoon: list[DayBandEntry] = []
    for band, block_start, block_end, credit in _profile_blocks(profile):
        total_hours = 0.0
        for start, end in intervals:
            total_hours += _overlap_hours(start, end, block_start, block_end)
        rounded = min(_round_whole_hour(total_hours), credit)
        if rounded <= 0:
            continue
        entry = DayBandEntry(symbol=symbol, value=rounded)
        if band == "morning":
            morning.append(entry)
        else:
            afternoon.append(entry)
    return (morning, afternoon)


def _night_overtime_entry(
    work_date: date,
    last_punch: datetime | None,
    *,
    symbol: str,
    overtime_start: time,
) -> DayBandEntry | None:
    if last_punch is None:
        return None
    base_dt = datetime.combine(work_date, overtime_start)
    if last_punch <= base_dt:
        return None
    rounded = _round_half_hour(_hours_between(base_dt, last_punch))
    if rounded <= 0:
        return None
    if rounded < 1:
        rounded = 1.0
    return DayBandEntry(symbol=symbol, value=rounded)


def _fixed_night_overtime_entry(
    work_date: date, last_punch: datetime | None, *, symbol: str
) -> DayBandEntry | None:
    """晚上加班固定从 18:00 起，按最后一次打卡时间结算；零头满 25 分钟进 0.5 小时。"""
    if last_punch is None:
        return None
    base_dt = datetime.combine(work_date, time(18, 0))
    if last_punch <= base_dt:
        return None
    rounded = _round_half_hour_with_25_minute_grace(_hours_between(base_dt, last_punch))
    if rounded <= 0:
        return None
    return DayBandEntry(symbol=symbol, value=rounded)


def _absence_symbol(record: AttendanceDayRecord, absent_streak: int) -> str | None:
    if record.leave_hours > 0:
        return "〇"
    if not record.absent_days:
        return None
    if absent_streak >= 5:
        return "〇"
    if absent_streak >= 3:
        return "〇"
    return None


def _regular_symbol(record: AttendanceDayRecord) -> str:
    shift_text = record.shift_name
    if is_rest_shift(shift_text):
        return "★"
    is_factory_person = (
        "惠州工厂" in record.department or "工厂" in record.attendance_group or "工厂" in shift_text
    )
    if (
        "公司" in shift_text
        and is_factory_person
        and ("远程" not in record.attendance_group)
        and ("公司-考勤" not in record.attendance_group)
    ):
        return "☆"
    return "√"


def _resolved_day_symbol(record: AttendanceDayRecord) -> str:
    """写入明细用的班次符号。周日不计正班：原为正班 √ 或交叉 ☆ 的一律按星期天加班 ★（可关）。"""
    from . import rules as _att_rules

    s = _regular_symbol(record)
    if not _att_rules.ACTIVE_POLICY.get("sunday_map_sqrt_to_star", True):
        return s
    if record.work_date.weekday() == 6 and s in ("√", "☆"):
        return "★"
    return s


def _symbol_entry(symbol: str, value: float) -> DayBandEntry | None:
    if value <= 0:
        return None
    return DayBandEntry(symbol=symbol, value=round(value, 2))


def _append_entry(entries: list[DayBandEntry], symbol: str, value: float) -> None:
    entry = _symbol_entry(symbol, value)
    if entry is not None:
        entries.append(entry)


def _build_day_template_data(
    record: AttendanceDayRecord,
    profile: TemplateEmployeeProfile,
    *,
    absent_streak: int,
) -> tuple[EmployeeDayTemplateData, dict[str, float], list[str]]:
    punches = _unique_sorted(record.all_punch_times())
    day_payload = EmployeeDayTemplateData(work_date=record.work_date, notes=list(record.notes))
    work_intervals = _work_intervals(punches)
    symbol = _resolved_day_symbol(record)
    dingtalk_hours = dingtalk_work_hours_as_hours(record.work_duration_raw)
    late_count = 0.0
    early_count = 0.0
    absent_hours = 0.0
    if not punches:
        fill_from_aggregate = (
            not is_rest_shift(record.shift_name)
            and record.leave_hours <= 0
            and (dingtalk_hours >= 6.5 or record.attendance_day_hint >= 1.0)
        )
        if fill_from_aggregate:
            reg = _resolved_day_symbol(record)
            morning, afternoon = _build_full_day_entries(profile, reg)
            day_payload.morning.extend(morning)
            day_payload.afternoon.extend(afternoon)
            day_payload.notes.append(
                f"dingtalk_aggregate_fill hours≈{dingtalk_hours:g} 出勤={record.attendance_day_hint:g}"
            )
        else:
            absence_symbol = _absence_symbol(record, absent_streak)
            if absence_symbol:
                morning, afternoon = _build_full_day_entries(profile, absence_symbol)
                day_payload.morning.extend(morning)
                day_payload.afternoon.extend(afternoon)
                absent_hours = round(sum(e.value for e in morning + afternoon), 2)
    else:
        schedule_ranges: tuple[TimeRange, ...] = ()
        if len(punches) == 1:
            if is_rest_shift(record.shift_name) and record.leave_hours <= 0:
                morning, afternoon = ([], [])
            else:
                morning, afternoon = _build_full_day_entries(profile, symbol)
        elif not work_intervals:
            morning, afternoon = _build_full_day_entries(profile, symbol)
        else:
            schedule_ranges = resolve_schedule_ranges(
                record.work_date,
                group_name=record.attendance_group,
                shift_name=record.shift_name,
                has_any_punch=True,
            )
            effective_intervals = (
                _clip_work_intervals_to_schedule(record.work_date, work_intervals, schedule_ranges)
                if schedule_ranges
                else work_intervals
            )
            morning, afternoon = _interval_entries(effective_intervals, profile, symbol)
            if not morning and (not afternoon):
                if schedule_ranges:
                    pass
                else:
                    morning, afternoon = _build_full_day_entries(profile, symbol)
        day_payload.morning.extend(morning)
        day_payload.afternoon.extend(afternoon)
        night_symbol = "★" if symbol == "★" else "☆"
        night_entry = _fixed_night_overtime_entry(
            record.work_date, punches[-1], symbol=night_symbol
        )
        night_total = night_entry.value if night_entry is not None else 0.0
        if night_total > 0:
            day_payload.night.append(DayBandEntry(symbol=night_symbol, value=night_total))
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
