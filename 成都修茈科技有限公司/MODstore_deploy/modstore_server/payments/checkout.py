"""Select a usable checkout transport while preserving Alipay fallback order."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("modstore_server.alipay_service")


@dataclass(frozen=True)
class CheckoutMethods:
    wap: Callable[..., dict[str, Any]]
    page: Callable[..., dict[str, Any]]
    precreate: Callable[..., dict[str, Any]]


def create_pay_order(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    user_agent: str = "",
    return_url: str | None = None,
    quit_url: str | None = None,
    notify_url: str | None = None,
    methods: CheckoutMethods,
) -> dict[str, Any]:
    ua = (user_agent or "").lower()
    is_mobile = any(
        (k in ua for k in ("mobile", "android", "iphone", "ipad", "ipod", "windows phone"))
    )
    if is_mobile:
        logger.info("[alipay] 检测到移动端 UA，使用 wap.pay")
        res = methods.wap(
            out_trade_no=out_trade_no,
            subject=subject,
            total_amount=total_amount,
            quit_url=quit_url,
            return_url=return_url,
            notify_url=notify_url,
        )
        if res["ok"]:
            gateway = res.get("gateway", "")
            order_string = res.get("order_string", "")
            redirect_url = f"{gateway}?{order_string}" if gateway and order_string else None
            return {
                "ok": True,
                "type": "wap",
                "redirect_url": redirect_url,
                "qr_code": None,
                "message": None,
                "raw": res.get("raw"),
            }
        logger.warning("[alipay] wap.pay 失败，尝试 page.pay: %s", res.get("message"))
    res = methods.page(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        return_url=return_url,
        notify_url=notify_url,
    )
    if res["ok"]:
        gateway = res.get("gateway", "")
        order_string = res.get("order_string", "")
        redirect_url = f"{gateway}?{order_string}" if gateway and order_string else None
        return {
            "ok": True,
            "type": "page",
            "redirect_url": redirect_url,
            "qr_code": None,
            "message": None,
            "raw": res.get("raw"),
        }
    logger.warning("[alipay] page.pay 失败，回退尝试 precreate: %s", res.get("message"))
    pr = methods.precreate(
        out_trade_no=out_trade_no, subject=subject, total_amount=total_amount, notify_url=notify_url
    )
    if pr["ok"]:
        return {
            "ok": True,
            "type": "precreate",
            "redirect_url": None,
            "qr_code": pr.get("qr_code"),
            "message": None,
            "raw": pr.get("raw"),
        }
    return {
        "ok": False,
        "type": "",
        "redirect_url": None,
        "qr_code": None,
        "message": res.get("message") or pr.get("message") or "支付下单失败",
        "raw": res.get("raw") or pr.get("raw"),
    }
