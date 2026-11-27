"""中文日期与金额列的归一化辅助。

表格里的日期常见形如 ``12月27-26年1月23``、``2026/9/30``、``2月``，直接交给
``pd.to_datetime`` 会整体退化为 object。这里只做两件事：抽取单元格中的第一个
日期，以及剥离金额里的千分位/货币符号，供受限 pandas 执行环境复用。
"""

from __future__ import annotations

import numbers
import re
from datetime import date, datetime
from typing import Any, cast

import pandas as pd

_CN_DATE = re.compile(
    r"(?:(?P<year>\d{2,4})\s*年)?\s*(?P<month>\d{1,2})\s*月"
    r"(?:\s*(?P<day>\d{1,2})\s*(?:日|号)?)?"
)
_ISO_LIKE = re.compile(
    r"(?P<year>\d{4})\s*[-/.年]\s*(?P<month>\d{1,2})\s*[-/.月]\s*(?P<day>\d{1,2})"
)
_NUMBER_NOISE = re.compile(r"[,\s¥￥$元人民币]")
_DATE_HINT = re.compile(r"[-/.年月日号]")
_DATE_NAME = re.compile(r"日期|时间|date|time|账期", re.IGNORECASE)
# Excel 以 1899-12-30 为序列号原点，20000~80000 覆盖 1954~2119 年。
_SERIAL_MIN, _SERIAL_MAX = 20000, 80000
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _resolve_year(raw: str | None, default_year: int | None) -> int | None:
    if not raw:
        return default_year
    year = int(raw)
    if year < 100:
        year += 2000
    return year


def _year_from_text(text: str, *, month: int, match_start: int) -> int | None:
    """区间只在末尾写年份时，仅起始月晚于结束月才回退一年。"""
    later = [match for match in _CN_DATE.finditer(text) if match.group("year")]
    if not later:
        return None
    dated = later[0]
    year = _resolve_year(dated.group("year"), None)
    if year is not None and match_start < dated.start() and month > int(dated.group("month")):
        year -= 1
    return year


def _serial_datetime(value: float) -> datetime | None:
    if not (_SERIAL_MIN <= value <= _SERIAL_MAX):
        return None
    return cast(datetime, (_EXCEL_EPOCH + pd.Timedelta(float(value), unit="D")).to_pydatetime())


def first_date(
    value: Any, *, default_year: int | None = None, allow_serial: bool = False
) -> datetime | None:
    """返回单元格中出现的第一个日期；无法识别时返回 ``None``。"""
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return cast(datetime, pd.Timestamp(value).to_pydatetime())
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return _serial_datetime(float(value)) if allow_serial else None
    text = str(value).strip()
    if not text:
        return None
    match = _CN_DATE.search(text)
    iso_match = _ISO_LIKE.search(text)
    if iso_match and (match is None or iso_match.start() < match.start()):
        try:
            return datetime(
                int(iso_match.group("year")),
                int(iso_match.group("month")),
                int(iso_match.group("day")),
            )
        except ValueError:
            return None
    if match:
        month = int(match.group("month"))
        day = int(match.group("day") or 1)
        year = _resolve_year(match.group("year"), None)
        if year is None:
            year = _year_from_text(text, month=month, match_start=match.start())
        if year is None:
            year = default_year or datetime.now().year
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    if allow_serial and re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _serial_datetime(float(text))
    # 纯数字（金额、编号、Excel 序列号）不交给 to_datetime 猜测。
    if not _DATE_HINT.search(text):
        return None
    try:
        parsed = pd.to_datetime(text, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return cast(datetime, pd.Timestamp(parsed).to_pydatetime())


def cn_date(series: pd.Series, default_year: int | None = None) -> pd.Series:
    """把中文日期列转成 datetime64；区间值取起始日，Excel 序列号自动换算。"""
    return pd.to_datetime(
        series.map(lambda value: first_date(value, default_year=default_year, allow_serial=True)),
        errors="coerce",
    )


def to_number(series: pd.Series) -> pd.Series:
    """把带千分位/货币符号的文本列转成数值列。"""
    return pd.to_numeric(
        series.map(lambda value: _NUMBER_NOISE.sub("", value) if isinstance(value, str) else value),
        errors="coerce",
    )


def normalize_excel_dates(df: pd.DataFrame) -> pd.DataFrame:
    """把「日期」类列里的 Excel 序列号转成 datetime，供后续语义查询复用。"""
    for name in list(df.columns):
        if not _DATE_NAME.search(str(name)):
            continue
        column = df[name]
        if column.dtype.kind in "iuf":
            numeric = column
        elif column.dtype.kind == "O":
            # 混合列（序列号 + 文本日期）保持 object，交给 cn_date 逐值解析。
            numeric = pd.to_numeric(column, errors="coerce")
            if numeric.notna().sum() != column.notna().sum():
                continue
        else:
            continue
        valid = numeric.dropna()
        if valid.empty or float(valid.between(_SERIAL_MIN, _SERIAL_MAX).mean()) < 0.99:
            continue
        df[name] = _EXCEL_EPOCH + pd.to_timedelta(numeric, unit="D")
    return df


def date_like_columns(df: pd.DataFrame, *, threshold: float = 0.8) -> list[str]:
    """返回可被中文日期解析覆盖超过阈值的列名。"""
    columns: list[str] = []
    for name in df.columns:
        column = df[name]
        if column.dtype.kind in "iuf":
            valid = column.dropna()
            if (
                _DATE_NAME.search(str(name))
                and not valid.empty
                and float(valid.between(_SERIAL_MIN, _SERIAL_MAX).mean()) >= threshold
            ):
                columns.append(str(name))
            continue
        if column.dtype.kind == "b":
            continue
        if column.dtype.kind == "M":
            columns.append(str(name))
            continue
        sample = column.dropna().astype(str)
        if sample.empty:
            continue
        allow_serial = bool(_DATE_NAME.search(str(name)))
        parsed = sample.map(lambda value: first_date(value, allow_serial=allow_serial) is not None)
        if float(parsed.mean()) >= threshold:
            columns.append(str(name))
    return columns


__all__ = ["first_date", "cn_date", "to_number", "normalize_excel_dates", "date_like_columns"]
