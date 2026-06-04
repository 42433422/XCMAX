"""采购 V1 应用服务：HTTP / 工具链唯一入口。"""

from __future__ import annotations

from typing import Any

_purchase_app_service: "PurchaseApplicationService | None" = None


class PurchaseApplicationService:
    """采购用例编排（迁移期委托 ``PurchaseService``）。"""

    def __init__(self) -> None:
        from app.infrastructure.gateways.purchase_legacy import PurchaseService

        self._inner = PurchaseService()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def get_purchase_app_service() -> PurchaseApplicationService:
    global _purchase_app_service
    if _purchase_app_service is None:
        _purchase_app_service = PurchaseApplicationService()
    return _purchase_app_service
