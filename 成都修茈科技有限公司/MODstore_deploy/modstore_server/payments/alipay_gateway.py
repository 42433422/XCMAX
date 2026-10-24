"""SDK boundary for creating, verifying and maintaining Alipay transactions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("modstore_server.alipay_service")


class AlipayClient(Protocol):

    def api_alipay_trade_precreate(self, **kwargs: Any) -> object: ...

    def api_alipay_trade_page_pay(self, **kwargs: Any) -> object: ...

    def api_alipay_trade_wap_pay(self, **kwargs: Any) -> object: ...

    def api_alipay_trade_query(self, **kwargs: Any) -> object: ...

    def api_alipay_trade_refund(self, **kwargs: Any) -> object: ...

    def api_alipay_trade_close(self, **kwargs: Any) -> object: ...

    def api_alipay_trade_fastpay_refund_query(
        self, out_request_no: str, **kwargs: Any
    ) -> object: ...

    def verify(self, data: dict[str, str], signature: str) -> bool: ...


@dataclass(frozen=True)
class AlipayGateway:
    client_factory: Callable[[], AlipayClient]
    credentials_ready: Callable[[], bool]
    debug: Callable[[], bool]
    notify_url: Callable[[], str | None]

    def common_kwargs(
        self, *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "out_trade_no": out_trade_no,
            "total_amount": total_amount,
            "subject": subject[:256],
        }
        nu = notify_url or self.notify_url()
        if nu:
            kwargs["notify_url"] = nu
        return kwargs

    def precreate(
        self, *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
    ) -> dict[str, Any]:
        if not self.credentials_ready():
            return {"ok": False, "qr_code": None, "message": "支付宝密钥未配全", "raw": None}
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {"ok": False, "qr_code": None, "message": str(e), "raw": None}
        kwargs = self.common_kwargs(
            out_trade_no=out_trade_no,
            subject=subject,
            total_amount=total_amount,
            notify_url=notify_url,
        )
        try:
            result = client.api_alipay_trade_precreate(**kwargs)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.precreate 请求异常")
            return {"ok": False, "qr_code": None, "message": f"请求支付宝异常: {e}", "raw": None}
        if not isinstance(result, dict):
            return {"ok": False, "qr_code": None, "message": "支付宝返回格式异常", "raw": None}
        if result.get("code") == "10000" and result.get("qr_code"):
            return {"ok": True, "qr_code": str(result["qr_code"]), "message": None, "raw": result}
        msg = result.get("sub_msg") or result.get("msg") or "预下单失败"
        return {"ok": False, "qr_code": None, "message": str(msg), "raw": result}

    def page_pay(
        self,
        *,
        out_trade_no: str,
        subject: str,
        total_amount: str,
        return_url: str | None = None,
        notify_url: str | None = None,
    ) -> dict[str, Any]:
        if not self.credentials_ready():
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": "支付宝密钥未配全",
                "raw": None,
            }
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": str(e),
                "raw": None,
            }
        kwargs = self.common_kwargs(
            out_trade_no=out_trade_no,
            subject=subject,
            total_amount=total_amount,
            notify_url=notify_url,
        )
        if return_url:
            kwargs["return_url"] = return_url
        try:
            order_string = client.api_alipay_trade_page_pay(**kwargs)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.page.pay 请求异常")
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": f"请求支付宝异常: {e}",
                "raw": None,
            }
        if not isinstance(order_string, str) or not order_string.strip():
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": "支付宝返回格式异常",
                "raw": None,
            }
        gateway = "https://openapi.alipay.com/gateway.do"
        if self.debug():
            gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
        return {
            "ok": True,
            "order_string": order_string,
            "gateway": gateway,
            "message": None,
            "raw": {"order_string": order_string},
        }

    def wap_pay(
        self,
        *,
        out_trade_no: str,
        subject: str,
        total_amount: str,
        quit_url: str | None = None,
        return_url: str | None = None,
        notify_url: str | None = None,
    ) -> dict[str, Any]:
        if not self.credentials_ready():
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": "支付宝密钥未配全",
                "raw": None,
            }
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": str(e),
                "raw": None,
            }
        kwargs = self.common_kwargs(
            out_trade_no=out_trade_no,
            subject=subject,
            total_amount=total_amount,
            notify_url=notify_url,
        )
        if quit_url:
            kwargs["quit_url"] = quit_url
        if return_url:
            kwargs["return_url"] = return_url
        try:
            order_string = client.api_alipay_trade_wap_pay(**kwargs)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.wap.pay 请求异常")
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": f"请求支付宝异常: {e}",
                "raw": None,
            }
        if not isinstance(order_string, str) or not order_string.strip():
            return {
                "ok": False,
                "order_string": None,
                "gateway": "",
                "message": "支付宝返回格式异常",
                "raw": None,
            }
        gateway = "https://openapi.alipay.com/gateway.do"
        if self.debug():
            gateway = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
        return {
            "ok": True,
            "order_string": order_string,
            "gateway": gateway,
            "message": None,
            "raw": {"order_string": order_string},
        }

    def verify(self, data: dict[str, str], signature: str) -> bool:
        client = self.client_factory()
        return bool(client.verify(data, signature))

    def query(
        self, *, out_trade_no: str | None = None, trade_no: str | None = None
    ) -> dict[str, Any]:
        if not out_trade_no and (not trade_no):
            return {"ok": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {"ok": False, "message": str(e), "raw": None}
        try:
            kwargs: dict[str, Any] = {}
            if out_trade_no:
                kwargs["out_trade_no"] = out_trade_no
            if trade_no:
                kwargs["trade_no"] = trade_no
            result = client.api_alipay_trade_query(**kwargs)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.query 请求异常")
            return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
        return standard_api_result(result, "交易查询失败")

    def refund(
        self,
        *,
        out_trade_no: str | None = None,
        trade_no: str | None = None,
        refund_amount: str,
        out_request_no: str | None = None,
        refund_reason: str | None = None,
    ) -> dict[str, Any]:
        if not out_trade_no and (not trade_no):
            return {"ok": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {"ok": False, "message": str(e), "raw": None}
        try:
            kwargs: dict[str, Any] = {"refund_amount": refund_amount}
            if out_trade_no:
                kwargs["out_trade_no"] = out_trade_no
            if trade_no:
                kwargs["trade_no"] = trade_no
            if out_request_no:
                kwargs["out_request_no"] = out_request_no
            if refund_reason:
                kwargs["refund_reason"] = refund_reason
            result = client.api_alipay_trade_refund(**kwargs)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.refund 请求异常")
            return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
        return standard_api_result(result, "退款失败")

    def close(
        self, *, out_trade_no: str | None = None, trade_no: str | None = None
    ) -> dict[str, Any]:
        if not out_trade_no and (not trade_no):
            return {"ok": False, "message": "out_trade_no 与 trade_no 至少提供一个", "raw": None}
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {"ok": False, "message": str(e), "raw": None}
        try:
            kwargs: dict[str, Any] = {}
            if out_trade_no:
                kwargs["out_trade_no"] = out_trade_no
            if trade_no:
                kwargs["trade_no"] = trade_no
            result = client.api_alipay_trade_close(**kwargs)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.close 请求异常")
            return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
        return standard_api_result(result, "关闭交易失败")

    def query_refund(
        self, *, out_trade_no: str, out_request_no: str | None = None
    ) -> dict[str, Any]:
        if not out_trade_no:
            return {"ok": False, "message": "out_trade_no 必填", "raw": None}
        try:
            client = self.client_factory()
        except RuntimeError as e:
            return {"ok": False, "message": str(e), "raw": None}
        req_no = out_request_no or out_trade_no
        try:
            result = client.api_alipay_trade_fastpay_refund_query(req_no, out_trade_no=out_trade_no)
        except RECOVERABLE_ERRORS as e:
            logger.exception("alipay.trade.fastpay.refund.query 请求异常")
            return {"ok": False, "message": f"请求支付宝异常: {e}", "raw": None}
        return standard_api_result(result, "退款查询失败")


def standard_api_result(result: Any, default_error: str) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"ok": False, "message": "支付宝返回格式异常", "raw": None}
    if result.get("code") == "10000":
        return {"ok": True, "message": None, "raw": result}
    msg = result.get("sub_msg") or result.get("msg") or default_error
    return {"ok": False, "message": str(msg), "raw": result}
