"""Credential-scoped catalog caching and model-capability queries."""

from __future__ import annotations

import hashlib
import re
from _thread import LockType
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from logging import Logger

import httpx

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .protocols import CacheKey, Connection, Payload, SyncClientFactory

_VISION_HINT_RE = re.compile(
    r"vision|vl-|vlm|deepseek-vl|qwen-vl|llava|omni|gpt-4o|gpt-4\.1|"
    r"gpt-4-turbo|gemini-1\.5|gemini-2|claude-3|claude-sonnet|claude-opus|多模态",
    re.IGNORECASE,
)


def cache_key(connection: Connection) -> CacheKey:
    fingerprint = hashlib.sha256(connection.auth_token.encode("utf-8")).hexdigest()[:16]
    return connection.platform_url, fingerprint


@dataclass
class CatalogCache:
    entries: MutableMapping[CacheKey, tuple[float, Payload]]
    lock: LockType
    clock: Callable[[], float]
    ttl: float

    def read(self, key: CacheKey) -> Payload | None:
        now = self.clock()
        with self.lock:
            cached = self.entries.get(key)
            if cached and cached[0] > now:
                return cached[1]
            if cached:
                self.entries.pop(key, None)
        return None

    def remember(self, key: CacheKey, value: Payload) -> None:
        with self.lock:
            self.entries[key] = self.clock() + self.ttl, value


@dataclass
class CatalogGateway:
    connection: Connection
    cache: CatalogCache
    sync_client: SyncClientFactory
    async_client: Callable[[], Awaitable[httpx.AsyncClient]]
    logger: Logger

    def read_sync(self) -> Payload | None:
        key = cache_key(self.connection)
        cached = self.cache.read(key)
        if cached is not None:
            return cached
        try:
            with self.sync_client(
                timeout=httpx.Timeout(min(self.connection.timeout, 15.0), connect=5.0),
                headers=self.connection.headers(),
            ) as client:
                response = client.get(f"{self.connection.platform_url}/api/llm/catalog")
                response.raise_for_status()
                raw = response.json()
            if isinstance(raw, dict):
                self.cache.remember(key, raw)
                return raw
        except RECOVERABLE_ERRORS as exc:
            self.logger.info("[Modstore] 无法读取模型目录，图片请求将尝试本地 OCR: %s", exc)
        return None

    async def read_async(self) -> Payload | None:
        key = cache_key(self.connection)
        cached = self.cache.read(key)
        if cached is not None:
            return cached
        try:
            client = await self.async_client()
            response = await client.get(
                f"{self.connection.platform_url}/api/llm/catalog",
                headers=self.connection.headers(),
            )
            response.raise_for_status()
            raw = response.json()
            if isinstance(raw, dict):
                self.cache.remember(key, raw)
                return raw
        except RECOVERABLE_ERRORS as exc:
            self.logger.info("[Modstore] 无法读取模型目录，图片请求将尝试本地 OCR: %s", exc)
        return None


def _catalog_model_vision_support(catalog: Payload, provider: str, model: str) -> bool | None:
    payload = catalog.get("data") if isinstance(catalog.get("data"), dict) else catalog
    providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(providers, list):
        return True if _VISION_HINT_RE.search(model or "") else None
    for block in providers:
        if not isinstance(block, dict) or str(block.get("provider") or "").lower() != provider:
            continue
        detailed = block.get("models_detailed")
        if not isinstance(detailed, list):
            break
        for row in detailed:
            if not isinstance(row, dict) or str(row.get("id") or "") != model:
                continue
            capability = row.get("capability")
            effective = (
                str(capability.get("effective_category") or "").lower()
                if isinstance(capability, dict)
                else ""
            )
            category = str(row.get("category") or effective).lower()
            if category == "vlm" or effective == "vlm" or _VISION_HINT_RE.search(model or ""):
                return True
            return False if category or effective else None
    return True if _VISION_HINT_RE.search(model or "") else None
