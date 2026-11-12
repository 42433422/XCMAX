"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("sunbird_attendance.convert")


def _filter_records_to_template_roster(
    records: list[_facade().AttendanceDayRecord],
    template_profiles: dict[str, _facade().TemplateEmployeeProfile],
) -> list[_facade().AttendanceDayRecord]:
    """只保留「明细」模板里已有姓名的打卡记录，再按规则聚合；钉钉表其余人员忽略。"""
    if not template_profiles:
        return []
    allowed = {str(k).strip() for k in template_profiles.keys() if str(k).strip()}
    return [r for r in records if (r.employee_name or "").strip() in allowed]


def _retain_detail_and_monthly_sheets(workbook) -> None:
    """输出只保留「明细」与「月度统计」（后者含指向明细侧栏小计的公式，便于手改后自动重算）。"""
    keep = frozenset({"明细", "月度统计"})
    if "明细" not in workbook.sheetnames:
        workbook.active.title = "明细"
    for name in list(workbook.sheetnames):
        if name not in keep:
            del workbook[name]


def _band_windows() -> dict[str, _facade().TimeRange]:
    return {
        "morning": _facade().TimeRange(_facade().time(0, 0), _facade().time(12, 30)),
        "afternoon": _facade().TimeRange(_facade().time(12, 30), _facade().time(18, 0)),
        "night": _facade().TimeRange(_facade().time(18, 0), _facade().time(23, 59)),
    }


def _hours_between(start: _facade().datetime, end: _facade().datetime) -> float:
    return max((end - start).total_seconds() / 3600.0, 0.0)


def _overlap_hours(
    interval_start: _facade().datetime,
    interval_end: _facade().datetime,
    range_start: _facade().time,
    range_end: _facade().time,
) -> float:
    start = max(interval_start, _facade().datetime.combine(interval_start.date(), range_start))
    end = min(interval_end, _facade().datetime.combine(interval_end.date(), range_end))
    return _facade()._hours_between(start, end)


def _unique_sorted(values: list[_facade().datetime]) -> list[_facade().datetime]:
    seen: set[_facade().datetime] = set()
    result: list[_facade().datetime] = []
    for value in sorted(values):
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _round_half_hour(value: float) -> float:
    if value <= 0:
        return 0.0
    return round(round(value * 2) / 2, 2)


def _round_half_hour_with_25_minute_grace(value: float) -> float:
    if value <= 0:
        return 0.0
    whole_half_hours = _facade().math.floor(value * 2)
    remainder_hours = value - whole_half_hours / 2
    if remainder_hours * 60 >= 25:
        whole_half_hours += 1
    return round(whole_half_hours / 2, 2)


def _round_whole_hour(value: float) -> float:
    if value <= 0:
        return 0.0
    return float(int(_facade().math.floor(value + 0.5)))


def _time_plus_hours(t: _facade().time, hours: float) -> _facade().time:
    return (
        _facade().datetime.combine(_facade().date.min, t) + _facade().timedelta(hours=hours)
    ).time()


def _profile_blocks(
    profile: _facade().TemplateEmployeeProfile,
) -> list[tuple[str, _facade().time, _facade().time, float]]:
    ms = profile.morning_work_start
    if ms is not None:
        t1 = _facade()._time_plus_hours(ms, 1.0)
        return [
            ("morning", ms, t1, profile.block_values[0]),
            ("morning", t1, _facade().time(12, 0), profile.block_values[1]),
            (
                "afternoon",
                _facade().time(13, 30),
                _facade().time(15, 30),
                profile.block_values[2],
            ),
            (
                "afternoon",
                _facade().time(15, 30),
                _facade().time(17, 30),
                profile.block_values[3],
            ),
        ]
    first = profile.block_values[0]
    if first <= 1.0:
        return [
            (
                "morning",
                _facade().time(9, 0),
                _facade().time(10, 0),
                profile.block_values[0],
            ),
            (
                "morning",
                _facade().time(10, 0),
                _facade().time(12, 0),
                profile.block_values[1],
            ),
            (
                "afternoon",
                _facade().time(13, 30),
                _facade().time(15, 30),
                profile.block_values[2],
            ),
            (
                "afternoon",
                _facade().time(15, 30),
                _facade().time(17, 30),
                profile.block_values[3],
            ),
        ]
    return [
        (
            "morning",
            _facade().time(8, 0),
            _facade().time(10, 0),
            profile.block_values[0],
        ),
        (
            "morning",
            _facade().time(10, 0),
            _facade().time(12, 0),
            profile.block_values[1],
        ),
        (
            "afternoon",
            _facade().time(13, 30),
            _facade().time(15, 30),
            profile.block_values[2],
        ),
        (
            "afternoon",
            _facade().time(15, 30),
            _facade().time(17, 30),
            profile.block_values[3],
        ),
    ]


def _default_profile(
    record: _facade().AttendanceDayRecord,
) -> _facade().TemplateEmployeeProfile:
    return _facade().TemplateEmployeeProfile(
        employee_name=record.employee_name,
        base_row=-1,
        department=record.department,
        nature_text="",
        block_values=(2.0, 2.0, 2.0, 2.0),
        overtime_start=_facade().time(18, 0),
        morning_work_start=None,
    )


def _primary_interval(
    punches: list[_facade().datetime],
) -> tuple[_facade().datetime, _facade().datetime] | None:
    if len(punches) < 2:
        return None
    start = punches[0]
    end = punches[-1]
    return (start, end) if end > start else None


def _work_intervals(
    punches: list[_facade().datetime],
) -> list[tuple[_facade().datetime, _facade().datetime]]:
    """按相邻两卡拆成多段在岗时间（钉钉常见「上班1/下班1/上班2/下班2」）。

    偶数次打卡依次两两配对，午休落在两段之间，不会被单段「首末卡」吞进正班重叠。
    奇数次打卡无法可靠配对，退回首尾单段，与历史 `_primary_interval` 行为一致。
    """
    n = len(punches)
    if n < 2:
        return []
    if n % 2 == 1:
        span = _facade()._primary_interval(punches)
        return [span] if span else []
    intervals: list[tuple[_facade().datetime, _facade().datetime]] = []
    for i in range(0, n, 2):
        start, end = (punches[i], punches[i + 1])
        if end > start:
            intervals.append((start, end))
    return intervals


def _clip_work_intervals_to_schedule(
    work_date: _facade().date,
    work_intervals: list[tuple[_facade().datetime, _facade().datetime]],
    schedule_ranges: tuple[_facade().TimeRange, ...],
) -> list[tuple[_facade().datetime, _facade().datetime]]:
    """把实际上班区间与「应计正班的日历时段」求交（如周六配置班段仅 13:30–16:00）。"""
    clipped: list[tuple[_facade().datetime, _facade().datetime]] = []
    for wi_start, wi_end in work_intervals:
        for sr in schedule_ranges:
            cs = max(wi_start, _facade().datetime.combine(work_date, sr.start))
            ce = min(wi_end, _facade().datetime.combine(work_date, sr.end))
            if ce > cs:
                clipped.append((cs, ce))
    return clipped


def _saturday_factory_outside_regular_hours(
    work_date: _facade().date,
    work_intervals: list[tuple[_facade().datetime, _facade().datetime]],
    schedule_ranges: tuple[_facade().TimeRange, ...],
    *,
    group_name: str | None,
    shift_name: str | None,
) -> float:
    """公司/工厂周六：正班以解析/回退日程为准，窗口外时长计平常加班。"""
    if work_date.weekday() != 5 or not _facade().is_company_factory_group(group_name, shift_name):
        return 0.0
    if not schedule_ranges:
        return 0.0
    clipped = _facade()._clip_work_intervals_to_schedule(work_date, work_intervals, schedule_ranges)
    total = sum(_facade()._hours_between(a, b) for (a, b) in work_intervals)
    inside = sum(_facade()._hours_between(a, b) for (a, b) in clipped)
    return max(0.0, total - inside)


def _build_full_day_entries(
    profile: _facade().TemplateEmployeeProfile, symbol: str
) -> tuple[list[_facade().DayBandEntry], list[_facade().DayBandEntry]]:
    morning: list[_facade().DayBandEntry] = []
    afternoon: list[_facade().DayBandEntry] = []
    blocks = _facade()._profile_blocks(profile)
    for band, _start, _end, credit in blocks:
        if credit <= 0:
            continue
        entry = _facade().DayBandEntry(symbol=symbol, value=credit)
        if band == "morning":
            morning.append(entry)
        else:
            afternoon.append(entry)
    return (morning, afternoon)


def _interval_entries(
    intervals: list[tuple[_facade().datetime, _facade().datetime]],
    profile: _facade().TemplateEmployeeProfile,
    symbol: str,
) -> tuple[list[_facade().DayBandEntry], list[_facade().DayBandEntry]]:
    if not intervals:
        return ([], [])
    morning: list[_facade().DayBandEntry] = []
    afternoon: list[_facade().DayBandEntry] = []
    for band, block_start, block_end, credit in _facade()._profile_blocks(profile):
        total_hours = 0.0
        for start, end in intervals:
            total_hours += _facade()._overlap_hours(start, end, block_start, block_end)
        rounded = min(_facade()._round_whole_hour(total_hours), credit)
        if rounded <= 0:
            continue
        entry = _facade().DayBandEntry(symbol=symbol, value=rounded)
        if band == "morning":
            morning.append(entry)
        else:
            afternoon.append(entry)
    return (morning, afternoon)


def _night_overtime_entry(
    work_date: _facade().date,
    last_punch: _facade().datetime | None,
    *,
    symbol: str,
    overtime_start: _facade().time,
) -> _facade().DayBandEntry | None:
    if last_punch is None:
        return None
    base_dt = _facade().datetime.combine(work_date, overtime_start)
    if last_punch <= base_dt:
        return None
    rounded = _facade()._round_half_hour(_facade()._hours_between(base_dt, last_punch))
    if rounded <= 0:
        return None
    if rounded < 1:
        rounded = 1.0
    return _facade().DayBandEntry(symbol=symbol, value=rounded)


def _fixed_night_overtime_entry(
    work_date: _facade().date, last_punch: _facade().datetime | None, *, symbol: str
) -> _facade().DayBandEntry | None:
    """晚上加班固定从 18:00 起，按最后一次打卡时间结算；零头满 25 分钟进 0.5 小时。"""
    if last_punch is None:
        return None
    base_dt = _facade().datetime.combine(work_date, _facade().time(18, 0))
    if last_punch <= base_dt:
        return None
    rounded = _facade()._round_half_hour_with_25_minute_grace(
        _facade()._hours_between(base_dt, last_punch)
    )
    if rounded <= 0:
        return None
    return _facade().DayBandEntry(symbol=symbol, value=rounded)


def _absence_symbol(record: _facade().AttendanceDayRecord, absent_streak: int) -> str | None:
    if record.leave_hours > 0:
        return "〇"
    if not record.absent_days:
        return None
    if absent_streak >= 5:
        return "〇"
    if absent_streak >= 3:
        return "〇"
    return None


def _regular_symbol(record: _facade().AttendanceDayRecord) -> str:
    shift_text = record.shift_name
    if _facade().is_rest_shift(shift_text):
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


def _resolved_day_symbol(record: _facade().AttendanceDayRecord) -> str:
    """写入明细用的班次符号。周日不计正班：原为正班 √ 或交叉 ☆ 的一律按星期天加班 ★（可关）。"""
    from . import rules as _att_rules

    s = _facade()._regular_symbol(record)
    if not _att_rules.ACTIVE_POLICY.get("sunday_map_sqrt_to_star", True):
        return s
    if record.work_date.weekday() == 6 and s in ("√", "☆"):
        return "★"
    return s


def _install_owner_policy() -> None:
    from . import rules as _att_rules
    from .owner_config import read_policy

    _att_rules.set_attendance_policy(read_policy())


def _clear_attendance_policy() -> None:
    from . import rules as _att_rules

    _att_rules.set_attendance_policy({})


def _symbol_entry(symbol: str, value: float) -> _facade().DayBandEntry | None:
    if value <= 0:
        return None
    return _facade().DayBandEntry(symbol=symbol, value=round(value, 2))


def _append_entry(entries: list[_facade().DayBandEntry], symbol: str, value: float) -> None:
    entry = _facade()._symbol_entry(symbol, value)
    if entry is not None:
        entries.append(entry)
