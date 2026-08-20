# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.alipay_service")


def _build_common_kwargs(
    *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
) -> dict[str, _facade().Any]:
    kwargs: dict[str, _facade().Any] = {
        "out_trade_no": out_trade_no,
        "total_amount": total_amount,
        "subject": subject[:256],
    }
    nu = notify_url or _facade().notify_url_default()
    if nu:
        kwargs["notify_url"] = nu
    return kwargs


def _try_precreate(
    *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
) -> dict[str, _facade().Any]:
    if not _facade().credentials_ready():
        return {"ok": False, "qr_code": None, "message": "支付宝密钥未配全", "raw": None}
    try:
        client = _facade().build_client()
    except RuntimeError as e:
        return {"ok": False, "qr_code": None, "message": str(e), "raw": None}
    kwargs = _facade()._build_common_kwargs(
        out_trade_no=out_trade_no, subject=subject, total_amount=total_amount, notify_url=notify_url
    )
    try:
        result = client.api_alipay_trade_precreate(**kwargs)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.precreate 请求异常")
        return {"ok": False, "qr_code": None, "message": f"请求支付宝异常: {e}", "raw": None}
    if not isinstance(result, dict):
        return {"ok": False, "qr_code": None, "message": "支付宝返回格式异常", "raw": None}
    if result.get("code") == "10000" and result.get("qr_code"):
        return {"ok": True, "qr_code": str(result["qr_code"]), "message": None, "raw": result}
    msg = result.get("sub_msg") or result.get("msg") or "预下单失败"
    return {"ok": False, "qr_code": None, "message": str(msg), "raw": result}


def precreate_order(
    *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
) -> dict[str, _facade().Any]:
    return _facade()._try_precreate(
        out_trade_no=out_trade_no, subject=subject, total_amount=total_amount, notify_url=notify_url
    )


def _try_page_pay(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    return_url: str | None = None,
    notify_url: str | None = None,
) -> dict[str, _facade().Any]:
    if not _facade().credentials_ready():
        return {
            "ok": False,
            "order_string": None,
            "gateway": "",
            "message": "支付宝密钥未配全",
            "raw": None,
        }
    try:
        client = _facade().build_client()
    except RuntimeError as e:
        return {"ok": False, "order_string": None, "gateway": "", "message": str(e), "raw": None}
    kwargs = _facade()._build_common_kwargs(
        out_trade_no=out_trade_no, subject=subject, total_amount=total_amount, notify_url=notify_url
    )
    if return_url:
        kwargs["return_url"] = return_url
    try:
        order_string = client.api_alipay_trade_page_pay(**kwargs)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.page.pay 请求异常")
        return {
            "ok": False,
            "order_string": None,
            "gateway": "",
            "message": f"请求支付宝异常: {e}",
            "raw": None,
        }
    gateway = "https://openapi.alipay.com/gateway.do"
    if _facade().alipay_debug():
        gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    return {
        "ok": True,
        "order_string": order_string,
        "gateway": gateway,
        "message": None,
        "raw": {"order_string": order_string},
    }


def _try_wap_pay(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    quit_url: str | None = None,
    return_url: str | None = None,
    notify_url: str | None = None,
) -> dict[str, _facade().Any]:
    if not _facade().credentials_ready():
        return {
            "ok": False,
            "order_string": None,
            "gateway": "",
            "message": "支付宝密钥未配全",
            "raw": None,
        }
    try:
        client = _facade().build_client()
    except RuntimeError as e:
        return {"ok": False, "order_string": None, "gateway": "", "message": str(e), "raw": None}
    kwargs = _facade()._build_common_kwargs(
        out_trade_no=out_trade_no, subject=subject, total_amount=total_amount, notify_url=notify_url
    )
    if quit_url:
        kwargs["quit_url"] = quit_url
    if return_url:
        kwargs["return_url"] = return_url
    try:
        order_string = client.api_alipay_trade_wap_pay(**kwargs)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.wap.pay 请求异常")
        return {
            "ok": False,
            "order_string": None,
            "gateway": "",
            "message": f"请求支付宝异常: {e}",
            "raw": None,
        }
    gateway = "https://openapi.alipay.com/gateway.do"
    if _facade().alipay_debug():
        gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    return {
        "ok": True,
        "order_string": order_string,
        "gateway": gateway,
        "message": None,
        "raw": {"order_string": order_string},
    }


def create_pay_order(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    user_agent: str = "",
    return_url: str | None = None,
    quit_url: str | None = None,
    notify_url: str | None = None,
) -> dict[str, _facade().Any]:
    ua = (user_agent or "").lower()
    is_mobile = any(
        (k in ua for k in ("mobile", "android", "iphone", "ipad", "ipod", "windows phone"))
    )
    if is_mobile:
        _facade().logger.info("[alipay] 检测到移动端 UA，使用 wap.pay")
        res = _facade()._try_wap_pay(
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
        _facade().logger.warning("[alipay] wap.pay 失败，尝试 page.pay: %s", res.get("message"))
    res = _facade()._try_page_pay(
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
    _facade().logger.warning("[alipay] page.pay 失败，回退尝试 precreate: %s", res.get("message"))
    pr = _facade()._try_precreate(
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


def verify_notify(data: dict[str, str], signature: str) -> bool:
    client = _facade().build_client()
    return bool(client.verify(data, signature))


def _standard_api_result(result: _facade().Any, default_error: str) -> dict[str, _facade().Any]:
    if not isinstance(result, dict):
        return {"ok": False, "message": "支付宝返回格式异常", "raw": None}
    if result.get("code") == "10000":
        return {"ok": True, "message": None, "raw": result}
    msg = result.get("sub_msg") or result.get("msg") or default_error
    return {"ok": False, "message": str(msg), "raw": result}


def query_order(
    *, out_trade_no: str | None = None, trade_no: str | None = None
) -> dict[str, _facade().Any]:
    if not out_trade_no and (not trade_no):
        return {"ok": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
    try:
        client = _facade().build_client()
    except RuntimeError as e:
        return {"ok": False, "message": str(e), "raw": None}
    try:
        kwargs: dict[str, _facade().Any] = {}
        if out_trade_no:
            kwargs["out_trade_no"] = out_trade_no
        if trade_no:
            kwargs["trade_no"] = trade_no
        result = client.api_alipay_trade_query(**kwargs)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.query 请求异常")
        return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
    return _facade()._standard_api_result(result, "交易查询失败")
