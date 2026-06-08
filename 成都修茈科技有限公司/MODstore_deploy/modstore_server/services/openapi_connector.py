"""OpenAPI connector service port.

The connector domain holds outbound HTTP calls to user-imported OpenAPI
specs. When it splits into a dedicated process (after the LLM service),
callers will keep using ``call_operation`` and the implementation will
swap to an HTTP client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class ConnectorOperationCall:
    connector_id: int
    user_id: int
    operation_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    body: Optional[Any] = None
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout: Optional[float] = None
    source: str = "in-process"


@dataclass(frozen=True)
class ConnectorOperationResult:
    ok: bool
    status_code: Optional[int]
    body: Any
    headers: Dict[str, str] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str = ""


class OpenApiConnectorClient(ABC):
    @abstractmethod
    def call_operation(self, call: ConnectorOperationCall) -> ConnectorOperationResult: ...


class InProcessOpenApiConnectorClient(OpenApiConnectorClient):
    """Default port wired to ``openapi_connector_runtime``.

    Lazily imports the runtime module to keep this services package cheap
    to import for callers that just need the type definitions.
    """

    def call_operation(self, call: ConnectorOperationCall) -> ConnectorOperationResult:
        from modstore_server.openapi_connector_runtime import (
            call_generated_operation,
        )

        result = call_generated_operation(
            connector_id=call.connector_id,
            user_id=call.user_id,
            operation_id=call.operation_id,
            params=dict(call.params or {}),
            body=call.body,
            headers=dict(call.headers or {}),
            timeout=call.timeout,
            source=call.source,
        )
        if not isinstance(result, dict):
            return ConnectorOperationResult(
                ok=False,
                status_code=None,
                body=None,
                headers={},
                duration_ms=0.0,
                error=f"unexpected runtime payload: {type(result).__name__}",
            )
        return ConnectorOperationResult(
            ok=bool(result.get("ok")),
            status_code=result.get("status_code"),
            body=result.get("body"),
            headers={str(k): str(v) for k, v in (result.get("headers") or {}).items()},
            duration_ms=float(result.get("duration_ms") or 0.0),
            error=str(result.get("error") or ""),
        )


_LOCK = Lock()
_default: OpenApiConnectorClient | None = None


def get_default_connector_client() -> OpenApiConnectorClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessOpenApiConnectorClient()
        return _default


def set_default_connector_client(client: Optional[OpenApiConnectorClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "ConnectorOperationCall",
    "ConnectorOperationResult",
    "InProcessOpenApiConnectorClient",
    "OpenApiConnectorClient",
    "get_default_connector_client",
    "set_default_connector_client",
]
