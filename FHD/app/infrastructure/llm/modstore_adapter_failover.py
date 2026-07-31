"""ModstorePlatformAdapter 的配额换模辅助（抽出以遵守巨文件棘轮）。"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List

import httpx

from app.infrastructure.llm.modstore_chat_failover import (
    build_chat_failover_candidates,
    chat_failover_max_attempts,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _response_status_code(response: Any, default: int = 200) -> int:
    raw = getattr(response, "status_code", default)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return default


def _failover_enabled(self) -> bool:
    raw = os.environ.get("XCAGI_LLM_CHAT_FAILOVER", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _fetch_llm_status_sync(self) -> dict[str, Any] | None:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(min(self.timeout, 15.0), connect=5.0),
            headers=self._build_headers(),
            trust_env=False,
        ) as client:
            response = client.get(f"{self.platform_url}/api/llm/status")
            if _response_status_code(response) >= 400:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
    except RECOVERABLE_ERRORS:
        return None


def _fetch_resolve_chat_default_sync(self) -> dict[str, Any] | None:
    try:
        with httpx.Client(
            timeout=httpx.Timeout(min(self.timeout, 15.0), connect=5.0),
            headers=self._build_headers(),
            trust_env=False,
        ) as client:
            response = client.get(f"{self.platform_url}/api/llm/resolve-chat-default")
            if _response_status_code(response) >= 400:
                return None
            data = response.json()
            return data if isinstance(data, dict) else None
    except RECOVERABLE_ERRORS:
        return None


def _ensure_catalog_sync(self) -> dict[str, Any] | None:
    catalog = self._cached_catalog()
    if catalog is not None:
        return catalog
    try:
        with httpx.Client(
            timeout=httpx.Timeout(min(self.timeout, 15.0), connect=5.0),
            headers=self._build_headers(),
            trust_env=False,
        ) as client:
            response = client.get(f"{self.platform_url}/api/llm/catalog")
            if _response_status_code(response) >= 400:
                return None
            raw = response.json()
        if isinstance(raw, dict):
            self._remember_catalog(raw)
            return raw
    except RECOVERABLE_ERRORS:
        return None
    return None


def _list_chat_failover_candidates_sync(
    self, primary_provider: str, primary_model: str
) -> list[tuple[str, str]]:
    if not _failover_enabled(self):
        return [(primary_provider, primary_model)]
    return build_chat_failover_candidates(
        primary_provider=primary_provider,
        primary_model=primary_model,
        status_payload=_fetch_llm_status_sync(self),
        catalog_payload=_ensure_catalog_sync(self),
        resolved_default=_fetch_resolve_chat_default_sync(self),
        max_attempts=chat_failover_max_attempts(),
    )


def _post_market_chat_sync(
    self,
    *,
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    allow_failover: bool,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    url = f"{self.platform_url}/api/llm/chat"
    payload: Dict[str, Any] = {
        "provider": provider,
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "allow_failover": bool(allow_failover),
    }
    if extra:
        payload.update(extra)
    if self.user_id:
        payload["user_id"] = self.user_id
    t0 = time.perf_counter()
    with httpx.Client(
        timeout=httpx.Timeout(self.timeout, connect=10.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
        headers=self._build_headers(),
        trust_env=False,
    ) as client:
        response = client.post(url, json=payload)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        status_code = _response_status_code(response)
        if status_code >= 400:
            error_text = response.text[:500]
            logger.error(
                "[Modstore] 平台同步返回错误 %s provider=%s/%s: %s",
                status_code,
                provider,
                model,
                error_text,
            )
            raise ValueError(f"平台错误({status_code}): {error_text}")
        result = response.json()

    used_provider = str(result.get("provider") or provider)
    used_model = str(result.get("model") or model)
    try:
        from app.neuro_bus.application_neuro_bridge import (
            neuro_notify_ai_model_roundtrip,
        )

        raw_usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        raw_total = 0
        try:
            raw_total = int(raw_usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            raw_total = 0
        neuro_notify_ai_model_roundtrip(
            model=f"modstore:{used_provider}/{used_model}",
            latency_ms=latency_ms,
            token_count=raw_total,
            user_id=str(self.user_id or ""),
        )
    except RECOVERABLE_ERRORS:
        pass

    logger.info(
        "[Modstore] 调用成功 [%.0fms] %s/%s key_source=%s billed=%s failover_from=%s",
        latency_ms,
        used_provider,
        used_model,
        result.get("key_source", "unknown"),
        result.get("billed", False),
        result.get("failover_from"),
    )
    return self._normalize_response(result, used_provider, used_model)
