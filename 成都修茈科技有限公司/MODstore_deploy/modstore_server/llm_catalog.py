"""拉取各厂商模型列表，带进程内 TTL 缓存；失败时合并本地兜底。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    openai_compat_default_root,
    resolve_api_key,
    resolve_base_url,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 600.0
_FORCE_REFRESH_MIN_INTERVAL = 45.0


def clear_all_catalog_cache() -> None:
    """BYOK 变更后丢弃进程内模型列表缓存。"""
    _cache.clear()


# cache_key -> {"mono": float, "models": list[str], "error": str|None, "source": str}
_cache: Dict[str, Dict[str, Any]] = {}
_last_force_refresh: Dict[int, float] = {}

# 仅剔除明显非「模型目录」条目；生图/视频等改由 taxonomy 分类，不再在此丢弃。
_OPENAI_STYLE_EXCLUDE_SUBSTR = (
    "embedding",
    "text-embedding",
    "whisper",
    "tts",
    "moderation",
    "davinci",
    "babbage",
    "text-search",
    "transcribe",
    "realtime",
    "speech",
    "ada-002",
    "ada-001",
    "rerank",
)


def _fallback_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "llm_fallback_models.json"


def _load_fallback() -> Dict[str, List[str]]:
    p = _fallback_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {k: list(v) for k, v in raw.items() if isinstance(v, list)}
    except Exception:
        return {}


def _cache_key(user_id: int, provider: str, api_key: str) -> str:
    h = hashlib.sha256(f"{user_id}:{provider}:{api_key}".encode()).hexdigest()[:20]
    return f"{provider}:{h}"


def _filter_openai_style(ids: List[str]) -> List[str]:
    out: List[str] = []
    for mid in ids:
        m = (mid or "").strip()
        if not m or m.startswith("ft:"):
            continue
        low = m.lower()
        if any(b in low for b in _OPENAI_STYLE_EXCLUDE_SUBSTR):
            continue
        out.append(m)
    return sorted(set(out))


async def _fetch_openai_compatible(
    base_url: str, api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[str], Optional[str]]:
    # base 已由调用方规范为以 /v1 或 /v3（火山方舟）结尾的根，此处只拼 /models
    url = f"{base_url.rstrip('/')}/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        r = await client.get(
            url, headers={"Authorization": f"Bearer {api_key}"}, timeout=httpx_timeout
        )
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            return [], "invalid json in models response"

        if isinstance(data, dict) and data.get("error") is not None:
            err_o = data["error"]
            if isinstance(err_o, dict):
                parts: List[str] = []
                for k in ("type", "code", "param", "message"):
                    v = err_o.get(k)
                    if v is not None and str(v).strip():
                        parts.append(f"{k}={str(v).strip()[:200]}")
                summary = ";".join(parts) if parts else str(err_o)[:300]
            else:
                summary = str(err_o)[:300]
            return [], f"openai_error:{summary}"

        if not isinstance(data, dict):
            return [], "unexpected models response shape"
        items = data.get("data")
        if not isinstance(items, list):
            return [], "unexpected models response shape"
        ids = [str(x.get("id", "")).strip() for x in items if isinstance(x, dict)]
        filtered = _filter_openai_style(ids)
        if not filtered:
            return [], "empty model list"
        return filtered, None
    except Exception as e:
        logger.warning("openai_compatible models fetch failed: %s", type(e).__name__)
        return [], str(e)


async def _fetch_anthropic(
    api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[str], Optional[str]]:
    url = "https://api.anthropic.com/v1/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        r = await client.get(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=httpx_timeout,
        )
        if r.status_code >= 400:
            return [], f"http {r.status_code}"
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], "unexpected response"
        ids: List[str] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            mid = str(x.get("id") or x.get("name") or "").strip()
            if mid:
                ids.append(mid)
        return sorted(set(ids)), None
    except Exception as e:
        logger.warning("anthropic models fetch failed: %s", type(e).__name__)
        return [], str(e)


async def _fetch_google(
    api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[str], Optional[str]]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        r = await client.get(url, params={"key": api_key}, timeout=httpx_timeout)
        if r.status_code >= 400:
            return [], f"http {r.status_code}"
        data = r.json()
        items = data.get("models") or []
        ids: List[str] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            name = str(x.get("name") or "")
            if name.startswith("models/"):
                short = name.split("/", 1)[1]
                # 仅保留生成模型常见前缀
                if "embed" in short.lower():
                    continue
                ids.append(short)
        return sorted(set(ids)), None
    except Exception as e:
        logger.warning("google models fetch failed: %s", type(e).__name__)
        return [], str(e)


def _merge_fallback(provider: str, remote: List[str]) -> List[str]:
    fb = _load_fallback().get(provider) or []
    return sorted(set(remote + fb))


async def get_models_for_provider(
    session,
    user_id: int,
    provider: str,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """返回 { models, source, fetched_at, error, from_cache }"""
    api_key, _src = resolve_api_key(session, user_id, provider)
    if not api_key:
        return {
            "models": _merge_fallback(provider, []),
            "source": "fallback_only",
            "fetched_at": None,
            "error": "no_api_key",
            "from_cache": False,
        }

    ck = _cache_key(user_id, provider, api_key)
    now = time.monotonic()

    if force_refresh:
        last = _last_force_refresh.get(user_id, 0.0)
        if now - last < _FORCE_REFRESH_MIN_INTERVAL:
            force_refresh = False
        else:
            _last_force_refresh[user_id] = now

    if not force_refresh and ck in _cache:
        ent = _cache[ck]
        if now - ent["mono"] < _CACHE_TTL_SEC:
            return {
                "models": ent["models"],
                "source": ent.get("source", "cache"),
                "fetched_at": ent.get("fetched_at_wall"),
                "error": ent.get("error"),
                "from_cache": True,
            }

    remote: List[str] = []
    err: Optional[str] = None
    src = "remote"

    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        raw_base = resolve_base_url(session, user_id, provider)
        b = (raw_base or openai_compat_default_root(provider)).rstrip("/")
        if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
            b = b + "/v1"
        remote, err = await _fetch_openai_compatible(b, api_key)
    elif provider == "anthropic":
        remote, err = await _fetch_anthropic(api_key)
    elif provider == "google":
        remote, err = await _fetch_google(api_key)
    else:
        return {
            "models": [],
            "source": "unknown_provider",
            "fetched_at": None,
            "error": "unknown",
            "from_cache": False,
        }

    merged = _merge_fallback(provider, remote)
    fb = _load_fallback().get(provider) or []
    if not remote:
        if merged and fb:
            if err:
                src = "fallback_after_error"
            else:
                src = "static_fallback_merged"
                err = err or "catalog_static_fallback_only"
        elif err:
            src = "fallback_after_error"

    wall = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat() + "Z"
    _cache[ck] = {
        "mono": now,
        "models": merged,
        "error": err,
        "source": src,
        "fetched_at_wall": wall,
    }
    return {
        "models": merged,
        "source": src,
        "fetched_at": wall,
        "error": err,
        "from_cache": False,
    }


_PROBE_HTTPX_TIMEOUT = 10.0


async def _probe_one_provider_list(provider: str, api_key: str) -> Tuple[str, List[str]]:
    """BYOK 裸钥探测用：不合并本地 fallback，以远程拉到的非空模型 id 为准。"""
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        b = openai_compat_default_root(provider).rstrip("/")
        if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
            b = b + "/v1"
        remote, _ = await _fetch_openai_compatible(b, api_key, httpx_timeout=_PROBE_HTTPX_TIMEOUT)
        return provider, remote
    if provider == "anthropic":
        remote, _ = await _fetch_anthropic(api_key, httpx_timeout=_PROBE_HTTPX_TIMEOUT)
        return provider, remote
    if provider == "google":
        remote, _ = await _fetch_google(api_key, httpx_timeout=_PROBE_HTTPX_TIMEOUT)
        return provider, remote
    return provider, []


async def probe_first_matching_provider(api_key: str) -> Optional[str]:
    """
    对裸 API Key 在 KNOWN_PROVIDERS 上并行试拉 /models，按列表顺序取首个返回非空模型列表的厂商。
    不访问用户库、不合并兜底列表。
    """
    key = (api_key or "").strip()
    if not key or len(key) < 8:
        return None
    results = await asyncio.gather(
        *[_probe_one_provider_list(p, key) for p in KNOWN_PROVIDERS], return_exceptions=True
    )
    for p, res in zip(KNOWN_PROVIDERS, results):
        if isinstance(res, Exception):
            logger.debug("byok probe %s: %s", p, res)
            continue
        _pid, models = res
        if models and len(models) > 0:
            return p
    return None
