"""模型支付后端 SOT（Source of Truth）选择器。

由环境变量 ``MODEL_PAYMENT_BACKEND`` 决定模型支付路由（``/api/model-payment/*``）
使用哪个后端作为订单/权益的唯一事实来源：

- ``json``（默认）：本地 JSON 落盘（见 ``order_store.py``），直连支付宝；单机/沙箱够用。
- ``postgres``：FHD PostgreSQL 订单表（生产推荐）。
- ``modstore``：代理到修茈市场（MODstore）统一收银台（``/api/market/payment/*``）。

本模块**仅做"当前用哪个后端"的判定**，不含任何扣款、验签或发货逻辑；
那些逻辑分别位于 ``alipay.py`` / ``order_store.py`` / ``modstore_payment_proxy.py``。
未配置或无法识别的取值一律回退到 ``json``，与既有本地实现保持一致。
"""

from __future__ import annotations

import os

# JSON 本地订单存储的弃用提示日期（仅用于 checkout 文案，可被环境变量覆盖）。
MODEL_PAYMENT_JSON_DEPRECATED_AFTER = (
    os.environ.get("MODEL_PAYMENT_JSON_DEPRECATED_AFTER") or "2026-12-31"
).strip()

_MODSTORE_ALIASES = {"modstore", "market", "xcagi_market"}
_POSTGRES_ALIASES = {"postgres", "postgresql", "pg", "fhd_postgres"}


def model_payment_backend() -> str:
    """返回规范化后端标识：``json`` | ``postgres`` | ``modstore``。

    读取 ``MODEL_PAYMENT_BACKEND``；未配置或取值无法识别时回退 ``json``
    （本地 JSON 订单存储，与 ``order_store`` 实现一致）。
    """
    raw = (os.environ.get("MODEL_PAYMENT_BACKEND") or "").strip().lower()
    if raw in _MODSTORE_ALIASES:
        return "modstore"
    if raw in _POSTGRES_ALIASES:
        return "postgres"
    return "json"


def is_modstore_payment_sot() -> bool:
    """是否由修茈市场（MODstore）统一收银台接管模型支付。"""
    return model_payment_backend() == "modstore"


def is_fhd_postgres_payment_sot() -> bool:
    """是否由 FHD PostgreSQL 订单表作为支付 SOT。"""
    return model_payment_backend() == "postgres"


def is_json_legacy_payment_sot() -> bool:
    """是否由本地 JSON 订单存储（遗留）作为支付 SOT。"""
    return model_payment_backend() == "json"


def is_local_model_payment_sot() -> bool:
    """本地直连支付宝（``json`` / ``postgres``，即非 ``modstore``）。

    支付宝异步通知（notify）仅在本地后端下处理；``modstore`` 模式的支付与回调
    由市场侧负责，本机不接收。
    """
    return not is_modstore_payment_sot()


def modstore_payment_hint() -> str:
    """``modstore`` 模式下引导调用方改用市场统一支付 API 的提示文案。"""
    return (
        "当前模型支付由修茈市场（MODstore）统一收银台接管，"
        "请改用 /api/market/payment/checkout 与 /api/market/payment/plans。"
    )


__all__ = [
    "MODEL_PAYMENT_JSON_DEPRECATED_AFTER",
    "is_fhd_postgres_payment_sot",
    "is_json_legacy_payment_sot",
    "is_local_model_payment_sot",
    "is_modstore_payment_sot",
    "model_payment_backend",
    "modstore_payment_hint",
]
