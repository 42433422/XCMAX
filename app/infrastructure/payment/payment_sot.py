"""模型支付与修茈市场订单真相源（SoT）开关。

权威 SoT：FHD PostgreSQL（``MODEL_PAYMENT_BACKEND=postgres``）。
``json`` 仅迁移期；``modstore`` 走市场 Java 支付代理。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# JSON 本地订单存储计划废弃月份（运维迁移窗口，非硬删除日期）
MODEL_PAYMENT_JSON_DEPRECATED_AFTER = "2026-12"


def _database_url() -> str:
    return (os.environ.get("DATABASE_URL") or "").strip().lower()


def model_payment_backend() -> str:
    """``postgres`` | ``modstore`` | ``json``（legacy 本地 JSON）。"""
    raw = (os.environ.get("MODEL_PAYMENT_BACKEND") or "").strip().lower()
    if raw in ("postgres", "postgresql", "pg", "fhd_pg"):
        return "postgres"
    if raw in ("modstore", "java", "market"):
        return "modstore"
    if raw in ("json", "local", "fhd"):
        return "json"
    if "postgresql" in _database_url():
        return "postgres"
    if (os.environ.get("XCAGI_MARKET_BASE_URL") or "").strip():
        return "modstore"
    return "json"


def is_fhd_postgres_payment_sot() -> bool:
    return model_payment_backend() == "postgres"


def is_json_legacy_payment_sot() -> bool:
    return model_payment_backend() == "json"


def warn_json_legacy_if_active() -> None:
    if is_json_legacy_payment_sot():
        logger.warning(
            "MODEL_PAYMENT_BACKEND=json is legacy; migrate to postgres before %s. "
            "Run scripts/migrate_fhd_json_orders_to_postgres.py",
            MODEL_PAYMENT_JSON_DEPRECATED_AFTER,
        )


def is_modstore_payment_sot() -> bool:
    return model_payment_backend() == "modstore"


def is_local_model_payment_sot() -> bool:
    """FHD 宿主侧存储（PG 或 JSON），可走 /api/model-payment 支付宝 notify。"""
    return model_payment_backend() in ("postgres", "json")


def modstore_payment_hint() -> str:
    return (
        "MODEL_PAYMENT_BACKEND=modstore：请使用修茈市场统一支付 "
        "（/api/market/payment/*，含支付宝与微信）；FHD 本地订单存储已停用。"
    )
