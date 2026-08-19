"""Business-date parsing for historical shipment and quote workbooks."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.application.etl.parser_structure import clean_cell_text

_DATE_TEXT_RE = re.compile(
    r"(?P<year>(?:19|20)\d{2})[年./-](?P<month>\d{1,2})(?:[月./-](?P<day>\d{1,2}))?"
)


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def source_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = clean_cell_text(value)
    if match := _DATE_TEXT_RE.search(text):
        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day") or 1),
            ).isoformat()
        except ValueError:
            return ""
    serial = number(value)
    if serial is None or not 30_000 <= serial <= 70_000:
        return ""
    try:
        from openpyxl.utils.datetime import from_excel

        converted = from_excel(serial)
        if isinstance(converted, datetime):
            return converted.date().isoformat()
        if isinstance(converted, date):
            return converted.isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""
    return ""


def source_date_from_values(values: tuple[Any, ...], *, max_columns: int = 4) -> tuple[str, int]:
    for index, value in enumerate(values[:max_columns], start=1):
        if parsed := source_date(value):
            return parsed, index
    return "", 0


__all__ = ["number", "source_date", "source_date_from_values"]
