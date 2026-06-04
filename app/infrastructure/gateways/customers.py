"""客户遗留服务网关。"""

from __future__ import annotations

from app.services import customers_service as _customers_service  # type: ignore[import-not-found, attr-defined]

CustomerService = _customers_service.CustomerService  # type: ignore[attr-defined]

__all__ = ["CustomerService"]
