"""Source-first ingestion; business interpretation remains downstream.

企业版通用 ELT 应用层（原 ETL 产品面）。
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.application.elt.service import EltService, get_elt_service

__all__ = ["EltService", "get_elt_service"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.application.elt import service

        return getattr(service, name)
    raise AttributeError(name)
