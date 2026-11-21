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
from .protocols import preflight_timeout as _preflight_timeout

_VISION_HINT_RE = re.compile(
    r"vision|vl-|vlm|deepseek-vl|qwen-vl|llava|omni|gpt-4o|gpt-4\.1|"
    r"gpt-4-turbo|gemini-1\.5|gemini-2|claude-3|claude-sonnet|claude-opus|多模态",
    re.IGNORECASE,
)


def public_model_capabilities(value: object) -> Payload:
    """Accept only public limits from the authenticated route/catalog response."""
    if not isinstance(value, dict):
        return {}
    limits: Payload = {
        key: value[key]
        for key in ("context_window", "max_input_tokens", "max_output_tokens")
        if type(value.get(key)) is int and value[key] > 0
    }
    resolved = value.get("resolved_model")
    if (
        isinstance(resolved, str)
        and "://" not in resolved
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@+-]{0,254}", resolved)
    ):
        limits["resolved_model"] = resolved
    if limits:
        source = value.get("source")
        limits["source"] = (
            source
            if isinstance(source, str)
            and source in {"provider_metadata", "litellm_registry", "litellm_model_info"}
            else "platform_catalog"
        )
    return limits


def model_capabilities(value: Payload, provider: str, model: str) -> Payload:
    """Look up an exact account-visible deployment, never a similarly named alias."""
    nested = value.get("data")
    payload = nested if isinstance(nested, dict) else value
    providers = payload.get("providers")
    if not isinstance(providers, list):
        return {}
    for block in providers:
        if not isinstance(block, dict) or str(block.get("provider") or "").lower() != provider:
            continue
        rows = block.get("models_detailed")
        if not isinstance(rows, list):
            return {}
        for row in rows:
            if isinstance(row, dict) and row.get("id") == model:
                return public_model_capabilities(
                    row.get("model_capabilities") or row.get("provider_metadata")
                )
    return {}


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
                timeout=_preflight_timeout(self.connection),
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
                timeout=_preflight_timeout(self.connection),
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
