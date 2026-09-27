"""UTC 时间工具，替代已弃用的 ``datetime.utcnow()``。"""

from __future__ import annotations

from datetime import UTC, date, datetime


def coerce_date(value: object) -> date | None:
    """把字符串日期规范化为 ``date``；空值返回 None，非法格式抛 ValueError。

    SQLite 的 DATE 列只接受 ``datetime.date``，直接写入字符串会抛 TypeError
    并变成 500（#2068），因此写库前必须经此规范化。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    raise ValueError(f"无法解析日期: {value!r}")


def utc_now_naive() -> datetime:
    """返回表示当前 UTC 的 naive ``datetime``，用于 ``DateTime`` 无时区列的读写与比较。"""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_now_iso_z(*, timespec: str = "seconds") -> str:
    """当前 UTC 的 ISO 8601 字符串，固定以 ``Z`` 结尾（用于 JSON、日志文件名等）。"""
    s = datetime.now(UTC).isoformat(timespec=timespec)
    return s.replace("+00:00", "Z")
