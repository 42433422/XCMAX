"""Catalog cross-domain client port.

Future state: HTTP client to a dedicated Catalog service. Today the default
implementation forwards to :mod:`modstore_server.catalog_store`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


class CatalogClient(ABC):
    """Public surface other domains may use to read/write the public catalog."""

    @abstractmethod
    def append_package(self, record: Dict[str, Any], src_file: Path | None) -> Dict[str, Any]: ...

    @abstractmethod
    def get_package(self, id_: str, version: str) -> Dict[str, Any] | None: ...

    @abstractmethod
    def list_packages(
        self,
        *,
        artifact: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]: ...


class InProcessCatalogClient(CatalogClient):
    """Wraps legacy :mod:`catalog_store` for in-process wiring."""

    def append_package(self, record: Dict[str, Any], src_file: Path | None) -> Dict[str, Any]:
        from modstore_server.catalog_store import append_package as _append

        return _append(record, src_file)

    def get_package(self, id_: str, version: str) -> Dict[str, Any] | None:
        from modstore_server.catalog_store import get_package as _get

        return _get(id_, version)

    def list_packages(
        self,
        *,
        artifact: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        from modstore_server.catalog_store import list_packages as _list

        return _list(artifact=artifact, q=q, limit=limit, offset=offset)


_LOCK = Lock()
_default: CatalogClient | None = None


def get_default_catalog_client() -> CatalogClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessCatalogClient()
        return _default


def set_default_catalog_client(client: Optional[CatalogClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "CatalogClient",
    "InProcessCatalogClient",
    "get_default_catalog_client",
    "set_default_catalog_client",
]
