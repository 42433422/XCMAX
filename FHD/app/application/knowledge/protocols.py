"""Small callable interfaces between the HTTP adapter and its services."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import JSONResponse

from app.application.dataset_rag.models import DatasetAccessContext

AccessResolver = Callable[[Request], DatasetAccessContext | None]


class DatasetAction(Protocol):
    def __call__(
        self, *, request: Request, action: str, params: dict[str, Any], route_path: str
    ) -> JSONResponse: ...


class MemoryResponse(Protocol):
    def __call__(
        self, payload: dict[str, Any], *, request: Request, action: str
    ) -> JSONResponse: ...


class RecallMerger(Protocol):
    def __call__(
        self, payload: dict[str, Any], *, request: Request, params: dict[str, Any]
    ) -> dict[str, Any]: ...
