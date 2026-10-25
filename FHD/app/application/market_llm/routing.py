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
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import Connection, Payload, Route, SyncClientFactory
from .responses import _response_status_code


@dataclass(frozen=True)
class FailoverDiscovery:
    connection: Connection
    read_catalog: Callable[[], Payload | None]
    client: SyncClientFactory

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
            resolved_default=self._fetch("/api/llm/resolve-chat-default"),
            max_attempts=chat_failover_max_attempts(),
        )
