"""Kitten 报表 / AI 文档 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import kitten as kitten_gw

_kitten_app_service: "KittenApplicationService | None" = None


class KittenApplicationService:
    """委托 infrastructure.gateways.kitten（实现仍在 services 包，迁移中）。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(kitten_gw, name)


def get_kitten_app_service() -> KittenApplicationService:
    global _kitten_app_service
    if _kitten_app_service is None:
        _kitten_app_service = KittenApplicationService()
    return _kitten_app_service
