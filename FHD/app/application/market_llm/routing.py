"""Discover account-visible fallback routes through explicit HTTP and catalog capabilities."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.infrastructure.llm.modstore_chat_failover import (
    build_chat_failover_candidates,
    chat_failover_max_attempts,
)
from app.infrastructure.modstore_transport import MarketModelError
from app.infrastructure.modstore_transport import safe_route_metadata as route_metadata
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import Connection, Payload, Route, SyncClientFactory
from .responses import _response_status_code


def resolve_account_route(
    connection: Connection, client_factory: SyncClientFactory, route: Route | None = None
) -> Payload:
    """Resolve account preferences/BYOK/platform defaults at their server-owned source."""
    with client_factory(
        timeout=httpx.Timeout(min(connection.timeout, 15.0), connect=5.0),
        headers=connection.headers(),
    ) as client:
        url = f"{connection.platform_url}/api/llm/resolve-chat-default"
        response = (
            client.get(url, params={"provider": route[0], "model": route[1]})
            if route
            else client.get(url)
        )
        status = _response_status_code(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise MarketModelError({"status": 502}) from exc
    if status >= 400:
        detail = data.get("detail", data) if isinstance(data, dict) else {}
        error = MarketModelError({"status": status})
        if isinstance(detail, dict) and detail.get("code") in {
            "INVALID_CHAT_PREFERENCE",
            "NO_BYOK_CHAT_MODEL",
        }:
            error.code = detail["code"]
            error.recovery = "choose_chat_model_or_follow_platform"
        raise error
    if isinstance(data, dict) and data.get("ok") is not False:
        provider, model = data.get("provider"), data.get("model")
        if (
            isinstance(provider, str)
            and isinstance(model, str)
            and provider.strip()
            and model.strip()
        ):
            return {
                **route_metadata(data),
                "provider": provider.strip().lower(),
                "model": model.strip(),
                "route_source": data.get("route_source") or data.get("source") or "unknown",
                **(
                    {"route_token": data["route_token"]}
                    if isinstance(data.get("route_token"), str)
                    else {}
                ),
            }
    raise MarketModelError({"status": 502})


def resolve_account_default(connection: Connection, client_factory: SyncClientFactory) -> Route:
    resolved = resolve_account_route(connection, client_factory)
    return resolved["provider"], resolved["model"]


def follow_platform_default(connection: Connection, client_factory: SyncClientFactory) -> None:
    """Apply only the caller's explicit recovery action with their own authorization."""
    with client_factory(
        timeout=httpx.Timeout(min(connection.timeout, 15.0), connect=5.0),
        headers=connection.headers(),
    ) as client:
        response = client.put(
            f"{connection.platform_url}/api/llm/preferences", json={"mode": "platform"}
        )
        status = _response_status_code(response)
        if status >= 400:
            raise MarketModelError({"status": status})


@dataclass(frozen=True)
class FailoverDiscovery:
    connection: Connection
    read_catalog: Callable[[], Payload | None]
    client: SyncClientFactory
    resolved_default: Payload | None = None

    def _fetch(self, path: str) -> Payload | None:
        try:
            with self.client(
                timeout=httpx.Timeout(min(self.connection.timeout, 15.0), connect=5.0),
                headers=self.connection.headers(),
            ) as client:
                response = client.get(f"{self.connection.platform_url}{path}")
                if _response_status_code(response) >= 400:
                    return None
                data = response.json()
                return data if isinstance(data, dict) else None
        except RECOVERABLE_ERRORS:
            return None

    def candidates(self, primary_provider: str, primary_model: str) -> list[Route]:
        if os.environ.get("XCAGI_LLM_CHAT_FAILOVER", "1").strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            return [(primary_provider, primary_model)]
        return build_chat_failover_candidates(
            primary_provider=primary_provider,
            primary_model=primary_model,
            status_payload=self._fetch("/api/llm/status"),
            catalog_payload=self.read_catalog(),
            resolved_default=self.resolved_default or self._fetch("/api/llm/resolve-chat-default"),
            max_attempts=chat_failover_max_attempts(),
        )
