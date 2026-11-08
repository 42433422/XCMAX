"""Parse reviewed price values and bind them to exact source evidence."""

from __future__ import annotations

import re
from decimal import Decimal

from app.application.elt.errors import EltError


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
