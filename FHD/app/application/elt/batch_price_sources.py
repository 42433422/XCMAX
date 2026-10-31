"""Parse reviewed price values and bind them to exact source evidence."""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from app.application.elt.errors import EltError


def business_period(raw: str) -> tuple[date, date]:
    """Retain year/month precision; never infer a business period from clock time."""
    text = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?", text):
        text = text.split("T", 1)[0]
    chinese_period = text.endswith(("年", "月"))
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    if chinese_period:
        text = text.removesuffix("-")
    match = re.fullmatch(
        r"([0-9]{4})(?:([-/])([0-9]{1,2})(?:\2([0-9]{1,2}))?)?",
        text,
    )
    if match is None:
        raise EltError(
            "ELT_PRICE_PERIOD_INVALID", "业务期间须来自明确的年、年月或年月日；不能用上传时间代替"
        )
    try:
        year = int(match[1])
        month, day = match[3], match[4]
        start = date(year, int(month or 1), int(day or 1))
        if day:
            end = start + timedelta(days=1)
        elif month:
            end = date(year + (int(month) == 12), int(month) % 12 + 1, 1)
        else:
            end = date(year + 1, 1, 1)
    except (ValueError, OverflowError):
        raise EltError("ELT_PRICE_PERIOD_INVALID", "业务期间不是有效的日历日期") from None
    return start, end


def price_value(raw: str) -> str:
    text = raw.strip()
    if text[:1] in {"￥", "¥"}:
        text = text[1:].strip()
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?", text):
        raise EltError(
            "ELT_PRICE_VALUE_INVALID", "价格须为非负金额且最多两位小数，不自动换算单位或舍入"
        )
    return format(Decimal(text), ".2f")


def reject_conflicting_period_prices(events):
    prices_by_period = {}
    for event in events:
        if event["period_start"] is None:
            continue
        period = (event["period_start"], event["period_end"])
        price = Decimal(str(event["price"]))
        if period in prices_by_period and prices_by_period[period] != price:
            raise EltError(
                "ELT_PRICE_PERIOD_CONFLICT", "同一业务期间存在不同价格，请先核对历史来源"
            )
        prices_by_period[period] = price


def latest_period_price(events):
    dated = [event for event in events if event["period_start"] is not None]
    if not dated:
        raise EltError("ELT_PRICE_PERIOD_REQUIRED", "缺少可核对的业务期间")
    latest_start = max(event["period_start"] for event in dated)
    overlapping = [event for event in dated if event["period_end"] > latest_start]
    if len({Decimal(str(event["price"])) for event in overlapping}) != 1:
        raise EltError(
            "ELT_PRICE_PERIOD_CONFLICT",
            "最近业务期间存在重叠或同期间不同价格，请先核对，未按文件顺序选价",
        )
    return min(
        overlapping,
        key=lambda event: (
            -event["period_start"].toordinal(),
            event["period_end"],
            event["source_key"],
        ),
    )
