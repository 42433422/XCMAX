# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.alipay_service")


def refund_order(
    *,
    out_trade_no: str | None = None,
    trade_no: str | None = None,
    refund_amount: str,
    out_request_no: str | None = None,
    refund_reason: str | None = None,
) -> dict[str, _facade().Any]:
    if not out_trade_no and (not trade_no):
        return {"ok": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
    try:
        client = _facade().build_client()
    except RuntimeError as e:
        return {"ok": False, "message": str(e), "raw": None}
    try:
        kwargs: dict[str, _facade().Any] = {"refund_amount": refund_amount}
        if out_trade_no:
            kwargs["out_trade_no"] = out_trade_no
        if trade_no:
            kwargs["trade_no"] = trade_no
        if out_request_no:
            kwargs["out_request_no"] = out_request_no
        if refund_reason:
            kwargs["refund_reason"] = refund_reason
        result = client.api_alipay_trade_refund(**kwargs)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.refund 请求异常")
        return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
    return _facade()._standard_api_result(result, "退款失败")


def close_order(
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
        result = client.api_alipay_trade_close(**kwargs)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.close 请求异常")
        return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
    return _facade()._standard_api_result(result, "关闭交易失败")


def query_refund(
    *, out_trade_no: str, out_request_no: str | None = None
) -> dict[str, _facade().Any]:
    if not out_trade_no:
        return {"ok": False, "message": "out_trade_no 必填", "raw": None}
    try:
        client = _facade().build_client()
    except RuntimeError as e:
        return {"ok": False, "message": str(e), "raw": None}
    req_no = out_request_no or out_trade_no
    try:
        result = client.api_alipay_trade_fastpay_refund_query(req_no, out_trade_no=out_trade_no)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("alipay.trade.fastpay.refund.query 请求异常")
        return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
    return _facade()._standard_api_result(result, "退款查询失败")


def diagnostics_snapshot() -> dict[str, _facade().Any]:
    sdk_err = _facade().sdk_import_error()
    notify_url = _facade().notify_url_default()
    return {
        "alipay_configured": _facade().alipay_ui_ready(),
        "sdk_installed": sdk_err is None,
        "sdk_import_error": sdk_err,
        "app_id_set": bool(_facade().alipay_app_id()),
        "private_key_source": _facade()._private_key_source(),
        "public_key_source": _facade()._public_key_source(),
        "notify_url": notify_url,
        "notify_url_path_ok": _facade()._notify_url_path_ok(notify_url),
        "debug_mode": _facade().alipay_debug(),
    }


def _private_key_source() -> str:
    if _facade()._pem_from_env("ALIPAY_APP_PRIVATE_KEY"):
        return "env"
    if _facade()._env("ALIPAY_APP_PRIVATE_KEY_PATH") and _facade()._read_file_from_env(
        "ALIPAY_APP_PRIVATE_KEY_PATH"
    ):
        return "path"
    return "missing"


def _public_key_source() -> str:
    if _facade()._pem_from_env("ALIPAY_ALIPAY_PUBLIC_KEY"):
        return "env"
    if _facade()._env("ALIPAY_ALIPAY_PUBLIC_KEY_PATH") and _facade()._read_file_from_env(
        "ALIPAY_ALIPAY_PUBLIC_KEY_PATH"
    ):
        return "path"
    if _facade()._default_bundled_alipay_public_key():
        return "bundled"
    return "missing"


def _notify_url_path_ok(url: str | None) -> bool:
    if not url:
        return False
    from urllib.parse import urlparse

    path = (urlparse(url).path or "").rstrip("/")
    return path == "/api/payment/notify/alipay"
