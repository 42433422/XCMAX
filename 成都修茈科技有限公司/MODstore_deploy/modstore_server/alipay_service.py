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
from modstore_server.alipay_config import env as _env
from modstore_server.alipay_config import notify_url_default as notify_url_default
from modstore_server.alipay_config import pem_from_env as _pem_from_env
from modstore_server.alipay_config import read_file_from_env as _read_file_from_env
from modstore_server.alipay_config import sdk_import_error as sdk_import_error
from modstore_server.alipay_config import warn_notify_url_path_once as warn_notify_url_path_once
from modstore_server.operational_errors import RECOVERABLE_ERRORS

try:
    from dotenv import load_dotenv

    _repo_root = Path(__file__).resolve().parents[1]
    for _env_file in (_repo_root / ".env",):
        if _env_file.is_file():
            load_dotenv(_env_file, override=False)
except RECOVERABLE_ERRORS:
    pass

logger = logging.getLogger(__name__)


from modstore_server.alipay_service_part01 import _build_common_kwargs as _build_common_kwargs
from modstore_server.alipay_service_part01 import _standard_api_result as _standard_api_result
from modstore_server.alipay_service_part01 import _try_page_pay as _try_page_pay
from modstore_server.alipay_service_part01 import _try_precreate as _try_precreate
from modstore_server.alipay_service_part01 import _try_wap_pay as _try_wap_pay
from modstore_server.alipay_service_part01 import create_pay_order as create_pay_order
from modstore_server.alipay_service_part01 import precreate_order as precreate_order
from modstore_server.alipay_service_part01 import query_order as query_order
from modstore_server.alipay_service_part01 import verify_notify as verify_notify
from modstore_server.alipay_service_part02 import _notify_url_path_ok as _notify_url_path_ok
from modstore_server.alipay_service_part02 import _private_key_source as _private_key_source
from modstore_server.alipay_service_part02 import _public_key_source as _public_key_source
from modstore_server.alipay_service_part02 import close_order as close_order
from modstore_server.alipay_service_part02 import diagnostics_snapshot as diagnostics_snapshot
from modstore_server.alipay_service_part02 import query_refund as query_refund
from modstore_server.alipay_service_part02 import refund_order as refund_order
