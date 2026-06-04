# -*- coding: utf-8 -*-
"""运营管理员 session 上下文：enterprise 安装包 + 管理员登录时使用 operator host profile。"""

from __future__ import annotations

import contextvars
import os
from contextvars import Token
from typing import Any

_session_account_meta_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "session_account_meta",
    default=None,
)


def set_session_account_meta(meta: dict[str, Any] | None) -> Token:
    return _session_account_meta_ctx.set(meta)


def reset_session_account_meta(token: Token) -> None:
    _session_account_meta_ctx.reset(token)


def get_session_account_meta() -> dict[str, Any] | None:
    return _session_account_meta_ctx.get()


def is_operator_session(meta: dict[str, Any] | None = None) -> bool:
    row = meta if meta is not None else get_session_account_meta()
    if not row:
        return False
    return str(row.get("account_kind") or "").strip().lower() == "admin" and bool(
        row.get("market_is_admin")
    )


def resolve_effective_host_profile_sku(product_sku: str | None = None) -> str:
    """解析当前应使用的 host profile SKU（operator / enterprise / personal / admin）。"""
    if product_sku:
        product = product_sku.strip().lower()
    else:
        # 勿 import product_skus：platform_shell 模块初始化时会经 host_profile 回调至此。
        product = os.environ.get("XCAGI_PRODUCT_SKU", "enterprise").strip().lower()
        if product not in ("personal", "enterprise", "admin"):
            product = "enterprise"
    if is_operator_session():
        return "operator"
    if product == "admin":
        return "operator"
    return product


__all__ = [
    "set_session_account_meta",
    "reset_session_account_meta",
    "get_session_account_meta",
    "is_operator_session",
    "resolve_effective_host_profile_sku",
]
