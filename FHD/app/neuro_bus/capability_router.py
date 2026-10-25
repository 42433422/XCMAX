"""Route capability requests to NeuroBus domains."""
from __future__ import annotations

from typing import Any, Callable


class CapabilityRouter:
    def __init__(self) -> None:
        self._routes: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def bind(self, capability: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self._routes[capability] = handler

    def route(self, capability: str, payload: dict[str, Any]) -> Any:
        handler = self._routes.get(capability)
        if handler is None:
            raise KeyError(f"no route for capability {capability!r}")
        return handler(payload)

    def capabilities(self) -> list[str]:
        return sorted(self._routes)
