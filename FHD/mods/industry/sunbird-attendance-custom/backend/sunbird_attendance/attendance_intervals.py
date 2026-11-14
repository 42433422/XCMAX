"""Pure time interval, schedule clipping and rounding operations."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

from .rules import TimeRange, is_company_factory_group


def _band_windows() -> dict[str, TimeRange]:
    return {
        "morning": TimeRange(time(0, 0), time(12, 30)),
        "afternoon": TimeRange(time(12, 30), time(18, 0)),
        "night": TimeRange(time(18, 0), time(23, 59)),
    }


def _hours_between(start: datetime, end: datetime) -> float:
    return max((end - start).total_seconds() / 3600.0, 0.0)


def _overlap_hours(
    interval_start: datetime,
    interval_end: datetime,
    range_start: time,
    range_end: time,
) -> float:
    start = max(interval_start, datetime.combine(interval_start.date(), range_start))
    end = min(interval_end, datetime.combine(interval_end.date(), range_end))
    return _hours_between(start, end)


def _unique_sorted(values: list[datetime]) -> list[datetime]:
    seen: set[datetime] = set()
    result: list[datetime] = []
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
    whole_half_hours = math.floor(value * 2)
    remainder_hours = value - whole_half_hours / 2
    if remainder_hours * 60 >= 25:
        whole_half_hours += 1
    return round(whole_half_hours / 2, 2)


def _round_whole_hour(value: float) -> float:
    if value <= 0:
        return 0.0
    return float(int(math.floor(value + 0.5)))


def _time_plus_hours(t: time, hours: float) -> time:
    return (datetime.combine(date.min, t) + timedelta(hours=hours)).time()


def _primary_interval(
    punches: list[datetime],
) -> tuple[datetime, datetime] | None:
    if len(punches) < 2:
        return None
    start = punches[0]
    end = punches[-1]
    return (start, end) if end > start else None


def _work_intervals(
    punches: list[datetime],
) -> list[tuple[datetime, datetime]]:
    """按相邻两卡拆成多段在岗时间（钉钉常见「上班1/下班1/上班2/下班2」）。

    偶数次打卡依次两两配对，午休落在两段之间，不会被单段「首末卡」吞进正班重叠。
    奇数次打卡无法可靠配对，退回首尾单段，与历史 `_primary_interval` 行为一致。
    """
    n = len(punches)
    if n < 2:
        return []
    if n % 2 == 1:
        span = _primary_interval(punches)
        return [span] if span else []
    intervals: list[tuple[datetime, datetime]] = []
    for i in range(0, n, 2):
        start, end = (punches[i], punches[i + 1])
        if end > start:
            intervals.append((start, end))
    return intervals


def _clip_work_intervals_to_schedule(
    work_date: date,
    work_intervals: list[tuple[datetime, datetime]],
    schedule_ranges: tuple[TimeRange, ...],
) -> list[tuple[datetime, datetime]]:
    """把实际上班区间与「应计正班的日历时段」求交（如周六配置班段仅 13:30–16:00）。"""
    clipped: list[tuple[datetime, datetime]] = []
    for wi_start, wi_end in work_intervals:
        for sr in schedule_ranges:
            cs = max(wi_start, datetime.combine(work_date, sr.start))
            ce = min(wi_end, datetime.combine(work_date, sr.end))
            if ce > cs:
                clipped.append((cs, ce))
    return clipped


def _saturday_factory_outside_regular_hours(
    work_date: date,
    work_intervals: list[tuple[datetime, datetime]],
    schedule_ranges: tuple[TimeRange, ...],
    *,
    group_name: str | None,
    shift_name: str | None,
) -> float:
    """公司/工厂周六：正班以解析/回退日程为准，窗口外时长计平常加班。"""
    if work_date.weekday() != 5 or not is_company_factory_group(group_name, shift_name):
        return 0.0
    if not schedule_ranges:
        return 0.0
    clipped = _clip_work_intervals_to_schedule(work_date, work_intervals, schedule_ranges)
    total = sum(_hours_between(a, b) for (a, b) in work_intervals)
    inside = sum(_hours_between(a, b) for (a, b) in clipped)
    return max(0.0, total - inside)
