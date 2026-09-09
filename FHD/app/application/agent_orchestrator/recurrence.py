"""Validated interval/daily rules; daily schedules retain the user's timezone."""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.application.agent_orchestrator.task_schedule import normalize_scheduled_at


def normalize_recurrence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("recurrence 必须是对象")
    kind = value.get("kind")
    if kind == "interval":
        seconds = value.get("seconds")
        if type(seconds) is not int or not 60 <= seconds <= 366 * 86400:
            raise ValueError("周期秒数必须是 60 到 31622400 的整数")
        return {"kind": kind, "seconds": seconds}
    if kind == "daily":
        hour, minute = value.get("hour"), value.get("minute", 0)
        if (
            type(hour) is not int
            or type(minute) is not int
            or not (0 <= hour < 24 and 0 <= minute < 60)
        ):
            raise ValueError("每日时间必须是合法时分")
        timezone = value.get("timezone")
        if not isinstance(timezone, str) or not timezone:
            raise ValueError("每日周期必须指定 IANA 时区")
        ZoneInfo(timezone)
        return {"kind": kind, "hour": hour, "minute": minute, "timezone": timezone}
    raise ValueError("仅支持 interval 或 daily 周期")


def next_occurrence(rule: dict[str, Any], previous: str, now: str) -> str:
    """Coalesce missed occurrences; DST gaps skip a day, folds run only once."""
    rule = normalize_recurrence(rule)
    anchor = datetime.fromisoformat(normalize_scheduled_at(previous))
    current = datetime.fromisoformat(normalize_scheduled_at(now))
    after = max(anchor, current)
    if rule["kind"] == "interval":
        seconds = rule["seconds"]
        periods = max(1, int((after - anchor).total_seconds() // seconds) + 1)
        return (anchor + timedelta(seconds=periods * seconds)).isoformat()
    zone = ZoneInfo(rule["timezone"])
    local_date = after.astimezone(zone).date()
    for offset in range(370):
        date = local_date + timedelta(days=offset)
        candidate = datetime(
            date.year, date.month, date.day, rule["hour"], rule["minute"], tzinfo=zone
        )
        utc = candidate.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if utc > after:
            return utc.isoformat()
    raise ValueError("找不到下一次执行时间")
