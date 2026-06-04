"""统一查询 V1 应用服务。"""

from __future__ import annotations

from typing import Any

from app.infrastructure.gateways import query as query_gw

_query_app_service: "QueryApplicationService | None" = None


class QueryApplicationService:
    def find_product(self, *args: Any, **kwargs: Any) -> Any:
        return query_gw.find_product(*args, **kwargs)

    def find_purchase_unit(self, *args: Any, **kwargs: Any) -> Any:
        return query_gw.find_purchase_unit(*args, **kwargs)

    def get_product_names(self, *args: Any, **kwargs: Any) -> Any:
        return query_gw.get_product_names(*args, **kwargs)

    def get_purchase_units(self, *args: Any, **kwargs: Any) -> Any:
        return query_gw.get_purchase_units(*args, **kwargs)

    @property
    def query_service(self) -> Any:
        return query_gw.query_service


def get_query_app_service() -> QueryApplicationService:
    global _query_app_service
    if _query_app_service is None:
        _query_app_service = QueryApplicationService()
    return _query_app_service
