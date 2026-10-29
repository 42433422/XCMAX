"""企业版通用 ETL 应用层。"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.application.etl.service import EtlService, get_etl_service

__all__ = ["EtlService", "get_etl_service"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.application.etl import service

        return getattr(service, name)
    raise AttributeError(name)
