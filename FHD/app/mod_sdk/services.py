"""主程高层 Application / Domain 服务（SDK re-export）。

这些是 Mod 允许依赖的**稳定服务入口**。它们的实现可能在内部多次搬家
（``app.bootstrap`` → ``app.application.*`` → ``app.domain.*``），但
``app.mod_sdk.services`` 的符号名与返回对象的外部 API 应保持稳定。
"""

from __future__ import annotations


def get_ai_chat_app_service():
    from app.application.ai_chat_app_service import get_ai_chat_app_service as impl

    return impl()


def get_products_service():
    from app.services import get_products_service as impl

    return impl()


def get_unified_intent_recognizer():
    from app.services.unified_intent_recognizer import (
        get_unified_intent_recognizer as impl,
    )

    return impl()


__all__ = [
    "get_ai_chat_app_service",
    "get_products_service",
    "get_unified_intent_recognizer",
]
