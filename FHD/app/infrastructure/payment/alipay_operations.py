"""AliPay web-order and transaction operations behind the configuration facade."""

from __future__ import annotations

from typing import Any, Callable


def _web_failure(message: str) -> dict[str, Any]:
    return {
        "success": False,
        "order_string": None,
        "gateway": "",
        "message": message,
        "raw": None,
    }


def try_precreate(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    notify_url: str | None,
    credentials_ready: Callable[[], bool],
    build_client: Callable[[], Any],
    build_common_kwargs: Callable[..., dict[str, Any]],
    transient_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    if not credentials_ready():
        return {
            "success": False,
            "qr_code": None,
            "message": (
                "支付宝密钥未配全：需要 ALIPAY_APP_ID、ALIPAY_APP_PRIVATE_KEY（或 _PATH）、"
                "以及 ALIPAY_ALIPAY_PUBLIC_KEY / _PATH 或 424/alipayPublicKey_RSA2.txt"
            ),
            "raw": None,
        }
    try:
        client = build_client()
    except RuntimeError:
        logger.exception("alipay client initialization failed")
        return {"success": False, "qr_code": None, "message": "支付宝服务暂时不可用", "raw": None}
    kwargs = build_common_kwargs(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        notify_url=notify_url,
    )
    try:
        result = client.api_alipay_trade_precreate(**kwargs)
    except transient_errors:
        logger.exception("alipay.trade.precreate 请求异常")
        return {
            "success": False,
            "qr_code": None,
            "message": "支付宝服务暂时不可用",
            "raw": None,
        }
    if not isinstance(result, dict):
        return {"success": False, "qr_code": None, "message": "支付宝返回格式异常", "raw": None}
    if result.get("code") == "10000" and result.get("qr_code"):
        return {"success": True, "qr_code": str(result["qr_code"]), "message": None, "raw": result}
    message = result.get("sub_msg") or result.get("msg") or "预下单失败"
    return {"success": False, "qr_code": None, "message": str(message), "raw": result}


def try_web_pay(
    channel: str,
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    return_url: str | None,
    notify_url: str | None,
    quit_url: str | None = None,
    credentials_ready: Callable[[], bool],
    build_client: Callable[[], Any],
    build_common_kwargs: Callable[..., dict[str, Any]],
    debug_enabled: Callable[[], bool],
    transient_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    """Create a page or WAP order using a common fail-soft contract."""
    if not credentials_ready():
        return _web_failure("支付宝密钥未配全")
    try:
        client = build_client()
    except RuntimeError:
        logger.exception("alipay client initialization failed")
        return _web_failure("支付宝服务暂时不可用")

    kwargs = build_common_kwargs(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        notify_url=notify_url,
    )
    if quit_url and channel == "wap":
        kwargs["quit_url"] = quit_url
    if return_url:
        kwargs["return_url"] = return_url
    try:
        if channel == "wap":
            order_string = client.api_alipay_trade_wap_pay(**kwargs)
        else:
            order_string = client.api_alipay_trade_page_pay(**kwargs)
    except transient_errors:
        logger.exception("alipay.trade.%s.pay 请求异常", channel)
        return _web_failure("支付宝服务暂时不可用")

    gateway = (
        "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
        if debug_enabled()
        else "https://openapi.alipay.com/gateway.do"
    )
    return {
        "success": True,
        "order_string": order_string,
        "gateway": gateway,
        "message": None,
        "raw": {"order_string": order_string},
    }


def query_order(
    *,
    out_trade_no: str | None,
    trade_no: str | None,
    build_client: Callable[[], Any],
    standard_result: Callable[[Any, str], dict[str, Any]],
    transient_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    if not out_trade_no and not trade_no:
        return {"success": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
    try:
        client = build_client()
    except RuntimeError:
        logger.exception("alipay client initialization failed")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    kwargs = {
        key: value
        for key, value in (("out_trade_no", out_trade_no), ("trade_no", trade_no))
        if value
    }
    try:
        result = client.api_alipay_trade_query(**kwargs)
    except transient_errors:
        logger.exception("alipay.trade.query 请求异常")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    return standard_result(result, "交易查询失败")


def refund_order(
    *,
    out_trade_no: str | None,
    trade_no: str | None,
    refund_amount: str,
    out_request_no: str | None,
    refund_reason: str | None,
    build_client: Callable[[], Any],
    standard_result: Callable[[Any, str], dict[str, Any]],
    transient_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    if not out_trade_no and not trade_no:
        return {"success": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
    try:
        client = build_client()
    except RuntimeError:
        logger.exception("alipay client initialization failed")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    kwargs: dict[str, Any] = {"refund_amount": refund_amount}
    for key, value in (
        ("out_trade_no", out_trade_no),
        ("trade_no", trade_no),
        ("out_request_no", out_request_no),
        ("refund_reason", refund_reason),
    ):
        if value:
            kwargs[key] = value
    try:
        result = client.api_alipay_trade_refund(**kwargs)
    except transient_errors:
        logger.exception("alipay.trade.refund 请求异常")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    return standard_result(result, "退款失败")


def close_order(
    *,
    out_trade_no: str | None,
    trade_no: str | None,
    build_client: Callable[[], Any],
    standard_result: Callable[[Any, str], dict[str, Any]],
    transient_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    if not out_trade_no and not trade_no:
        return {"success": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
    try:
        client = build_client()
    except RuntimeError:
        logger.exception("alipay client initialization failed")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    kwargs = {
        key: value
        for key, value in (("out_trade_no", out_trade_no), ("trade_no", trade_no))
        if value
    }
    try:
        result = client.api_alipay_trade_close(**kwargs)
    except transient_errors:
        logger.exception("alipay.trade.close 请求异常")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    return standard_result(result, "关闭交易失败")


def query_refund(
    *,
    out_trade_no: str,
    out_request_no: str | None,
    build_client: Callable[[], Any],
    standard_result: Callable[[Any, str], dict[str, Any]],
    transient_errors: tuple[type[BaseException], ...],
    logger: Any,
) -> dict[str, Any]:
    if not out_trade_no:
        return {"success": False, "message": "out_trade_no 必填", "raw": None}
    try:
        client = build_client()
    except RuntimeError:
        logger.exception("alipay client initialization failed")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    request_no = out_request_no or out_trade_no
    try:
        result = client.api_alipay_trade_fastpay_refund_query(request_no, out_trade_no=out_trade_no)
    except transient_errors:
        logger.exception("alipay.trade.fastpay.refund.query 请求异常")
        return {"success": False, "message": "支付宝服务暂时不可用", "raw": None}
    return standard_result(result, "退款查询失败")
