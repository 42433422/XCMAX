"""MODstore 支付宝支付服务：基于 python-alipay-sdk 的完整封装。

⚠️ 兼容层：在 ``PAYMENT_BACKEND=java`` 模式下，下单 / 回调 / 退款全部由 Java 支付服务
（``com.modstore.controller.AlipayController`` 等）处理；本模块仅作为
``PAYMENT_BACKEND=python`` 的本地回滚 fallback 使用，不再接入新的支付宝能力。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from modstore_server.alipay_config import alipay_app_id as alipay_app_id
from modstore_server.alipay_config import alipay_debug as alipay_debug
from modstore_server.alipay_config import alipay_public_key_pem as alipay_public_key_pem
from modstore_server.alipay_config import alipay_ui_ready as alipay_ui_ready
from modstore_server.alipay_config import app_private_key_pem as app_private_key_pem
from modstore_server.alipay_config import build_client as build_client
from modstore_server.alipay_config import credentials_ready as credentials_ready
from modstore_server.alipay_config import (
    default_bundled_alipay_public_key as _default_bundled_alipay_public_key,
)
from modstore_server.alipay_config import diagnostics_snapshot as diagnostics_snapshot
from modstore_server.alipay_config import env as _env
from modstore_server.alipay_config import notify_url_default as notify_url_default
from modstore_server.alipay_config import notify_url_path_ok as _notify_url_path_ok
from modstore_server.alipay_config import pem_from_env as _pem_from_env
from modstore_server.alipay_config import private_key_source as _private_key_source
from modstore_server.alipay_config import public_key_source as _public_key_source
from modstore_server.alipay_config import read_file_from_env as _read_file_from_env
from modstore_server.alipay_config import sdk_import_error as sdk_import_error
from modstore_server.alipay_config import (
    warn_notify_url_path_once as warn_notify_url_path_once,
)
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.payments.alipay_gateway import AlipayGateway
from modstore_server.payments.alipay_gateway import (
    standard_api_result as _standard_api_result,
)
from modstore_server.payments.checkout import CheckoutMethods
from modstore_server.payments.checkout import create_pay_order as _select_checkout

__all__ = [
    "_build_common_kwargs",
    "_default_bundled_alipay_public_key",
    "_env",
    "_notify_url_path_ok",
    "_pem_from_env",
    "_private_key_source",
    "_public_key_source",
    "_read_file_from_env",
    "_standard_api_result",
    "_try_page_pay",
    "_try_precreate",
    "_try_wap_pay",
    "alipay_app_id",
    "alipay_debug",
    "alipay_public_key_pem",
    "alipay_ui_ready",
    "app_private_key_pem",
    "build_client",
    "close_order",
    "create_pay_order",
    "credentials_ready",
    "diagnostics_snapshot",
    "notify_url_default",
    "precreate_order",
    "query_order",
    "query_refund",
    "refund_order",
    "sdk_import_error",
    "verify_notify",
    "warn_notify_url_path_once",
]
try:
    from dotenv import load_dotenv

    _repo_root = Path(__file__).resolve().parents[1]
    for _env_file in (_repo_root / ".env",):
        if _env_file.is_file():
            load_dotenv(_env_file, override=False)
except RECOVERABLE_ERRORS:
    pass
logger = logging.getLogger(__name__)


def _gateway() -> AlipayGateway:
    return AlipayGateway(build_client, credentials_ready, alipay_debug, notify_url_default)


def _build_common_kwargs(
    *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
) -> dict[str, Any]:
    return _gateway().common_kwargs(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        notify_url=notify_url,
    )


def _try_precreate(
    *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
) -> dict[str, Any]:
    return _gateway().precreate(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        notify_url=notify_url,
    )


def _try_page_pay(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    return_url: str | None = None,
    notify_url: str | None = None,
) -> dict[str, Any]:
    return _gateway().page_pay(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        return_url=return_url,
        notify_url=notify_url,
    )


def _try_wap_pay(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    quit_url: str | None = None,
    return_url: str | None = None,
    notify_url: str | None = None,
) -> dict[str, Any]:
    return _gateway().wap_pay(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        quit_url=quit_url,
        return_url=return_url,
        notify_url=notify_url,
    )


def verify_notify(data: dict[str, str], signature: str) -> bool:
    return _gateway().verify(data, signature)


def query_order(*, out_trade_no: str | None = None, trade_no: str | None = None) -> dict[str, Any]:
    return _gateway().query(out_trade_no=out_trade_no, trade_no=trade_no)


def refund_order(
    *,
    out_trade_no: str | None = None,
    trade_no: str | None = None,
    refund_amount: str,
    out_request_no: str | None = None,
    refund_reason: str | None = None,
) -> dict[str, Any]:
    return _gateway().refund(
        out_trade_no=out_trade_no,
        trade_no=trade_no,
        refund_amount=refund_amount,
        out_request_no=out_request_no,
        refund_reason=refund_reason,
    )


def close_order(*, out_trade_no: str | None = None, trade_no: str | None = None) -> dict[str, Any]:
    return _gateway().close(out_trade_no=out_trade_no, trade_no=trade_no)


def query_refund(*, out_trade_no: str, out_request_no: str | None = None) -> dict[str, Any]:
    return _gateway().query_refund(out_trade_no=out_trade_no, out_request_no=out_request_no)


def precreate_order(
    *, out_trade_no: str, subject: str, total_amount: str, notify_url: str | None = None
) -> dict[str, Any]:
    return _try_precreate(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        notify_url=notify_url,
    )


def create_pay_order(
    *,
    out_trade_no: str,
    subject: str,
    total_amount: str,
    user_agent: str = "",
    return_url: str | None = None,
    quit_url: str | None = None,
    notify_url: str | None = None,
) -> dict[str, Any]:
    return _select_checkout(
        out_trade_no=out_trade_no,
        subject=subject,
        total_amount=total_amount,
        user_agent=user_agent,
        return_url=return_url,
        quit_url=quit_url,
        notify_url=notify_url,
        methods=CheckoutMethods(_try_wap_pay, _try_page_pay, _try_precreate),
    )
