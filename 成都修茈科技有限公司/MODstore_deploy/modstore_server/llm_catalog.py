"""拉取各厂商模型列表，带进程内 TTL 缓存；失败时合并本地兜底。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.llm_catalog_data import (
    cache_key as _cache_key,
    filter_openai_style as _filter_openai_style,
    load_fallback as _load_fallback,
    merge_model_records,
    metadata_by_model_records,
    model_id as _model_id,
    openai_style_items as _openai_style_items,
    runtime_model_ids as _runtime_model_ids,
)
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    is_minimax_token_plan_key,
    minimax_anthropic_base_url,
    normalize_minimax_api_key,
    openai_compat_default_root,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.llm_model_taxonomy import build_models_detailed

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 600.0
_FORCE_REFRESH_MIN_INTERVAL = 45.0


def clear_all_catalog_cache() -> None:
    """BYOK 变更后丢弃进程内模型列表缓存。"""
    _cache.clear()


# cache_key -> {"mono": float, "models": list[str], "error": str|None, "source": str}
_cache: Dict[str, Dict[str, Any]] = {}
_last_force_refresh: Dict[int, float] = {}

# 能力目录需保留 TTS/STT/嵌入/图像/视频等非对话模型；
# 只排除用户私有微调别名，避免混入平台公共能力目录。


async def _fetch_openai_compatible_records(
    base_url: str,
    api_key: str,
    *,
    provider: str = "",
    httpx_timeout: float = 30.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    # base 已由调用方规范为以 /v1 或 /v3（火山方舟）结尾的根，此处只拼 /models
    url = f"{base_url.rstrip('/')}/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        params = {"output_modalities": "all"} if provider == "openrouter" else None
        r = await client.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            timeout=httpx_timeout,
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

        items = _openai_style_items(data)
        if items is None:
            return [], "unexpected models response shape"

        # OpenRouter 的视频模型使用独立目录；失败时不影响主目录。
        if provider == "openrouter":
            try:
                video_response = await client.get(
                    f"{base_url.rstrip('/')}/videos/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=httpx_timeout,
                )
                if video_response.status_code < 400:
                    video_items = _openai_style_items(video_response.json()) or []
                    for video_item in video_items:
                        architecture = video_item.get("architecture")
                        if not isinstance(architecture, dict):
                            architecture = {}
                            video_item["architecture"] = architecture
                        architecture.setdefault("output_modalities", ["video"])
                        video_item.setdefault("type", "video")
                    items.extend(video_items)
            except Exception as exc:  # noqa: BLE001
                logger.debug("openrouter video catalog fetch failed: %s", type(exc).__name__)

        # SiliconFlow 支持按 type 动态筛选，筛选结果比模型名更可靠。
        if provider == "siliconflow":

            async def _typed_items(model_type: str) -> List[Dict[str, Any]]:
                try:
                    typed_response = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        params={"type": model_type},
                        timeout=httpx_timeout,
                    )
                    if typed_response.status_code >= 400:
                        return []
                    typed_items = _openai_style_items(typed_response.json()) or []
                    for typed_item in typed_items:
                        typed_item.setdefault("type", model_type)
                    return typed_items
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "siliconflow %s catalog fetch failed: %s",
                        model_type,
                        type(exc).__name__,
                    )
                    return []

            typed_groups = await asyncio.gather(
                *[_typed_items(model_type) for model_type in ("text", "image", "audio", "video")]
            )
            for typed_items in typed_groups:
                items.extend(typed_items)
        allowed = set(
            _filter_openai_style(
                [str(x.get("id", "")).strip() for x in items if isinstance(x, dict)]
            )
        )
        records_by_id: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or "").strip()
            if mid not in allowed:
                continue
            record = dict(item)
            record["id"] = mid
            record["_catalog_origin"] = "provider_api"
            previous = records_by_id.get(mid) or {}
            records_by_id[mid] = {**previous, **record}
        records = list(records_by_id.values())
        if not records:
            return [], "empty model list"
        return records, None
    except Exception as e:
        logger.warning("openai_compatible models fetch failed: %s", type(e).__name__)
        return [], str(e)


async def _fetch_openai_compatible(
    base_url: str,
    api_key: str,
    *,
    provider: str = "",
    httpx_timeout: float = 30.0,
) -> Tuple[List[str], Optional[str]]:
    records, error = await _fetch_openai_compatible_records(
        base_url,
        api_key,
        provider=provider,
        httpx_timeout=httpx_timeout,
    )
    return sorted({str(item.get("id") or "") for item in records}), error


async def _fetch_anthropic_compatible_records(
    api_key: str,
    *,
    base_url: str,
    provider_label: str,
    httpx_timeout: float = 30.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    url = f"{base_url.rstrip('/')}/v1/models"
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
        records: List[Dict[str, Any]] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            mid = str(x.get("id") or x.get("name") or "").strip()
            if mid:
                record = dict(x)
                record["id"] = mid
                record["_catalog_origin"] = "provider_api"
                records.append(record)
        return records, None
    except Exception as e:
        logger.warning(
            "%s anthropic-compatible models fetch failed: %s",
            provider_label,
            type(e).__name__,
        )
        return [], str(e)


async def _fetch_anthropic_records(
    api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return await _fetch_anthropic_compatible_records(
        api_key,
        base_url="https://api.anthropic.com",
        provider_label="anthropic",
        httpx_timeout=httpx_timeout,
    )


async def _fetch_minimax_token_plan_records(
    api_key: str,
    *,
    base_url: Optional[str] = None,
    httpx_timeout: float = 30.0,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    return await _fetch_anthropic_compatible_records(
        normalize_minimax_api_key(api_key),
        base_url=minimax_anthropic_base_url(base_url),
        provider_label="minimax_token_plan",
        httpx_timeout=httpx_timeout,
    )


async def _fetch_anthropic(
    api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[str], Optional[str]]:
    records, error = await _fetch_anthropic_records(api_key, httpx_timeout=httpx_timeout)
    return sorted({str(item.get("id") or "") for item in records}), error


async def _fetch_google_records(
    api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        r = await client.get(url, params={"key": api_key}, timeout=httpx_timeout)
        if r.status_code >= 400:
            return [], f"http {r.status_code}"
        data = r.json()
        items = data.get("models") or []
        records: List[Dict[str, Any]] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            name = str(x.get("name") or "")
            if name.startswith("models/"):
                short = name.split("/", 1)[1]
                record = dict(x)
                record["id"] = short
                record["_catalog_origin"] = "provider_api"
                records.append(record)
        return records, None
    except Exception as e:
        logger.warning("google models fetch failed: %s", type(e).__name__)
        return [], str(e)


async def _fetch_google(
    api_key: str, *, httpx_timeout: float = 30.0
) -> Tuple[List[str], Optional[str]]:
    records, error = await _fetch_google_records(api_key, httpx_timeout=httpx_timeout)
    return sorted({str(item.get("id") or "") for item in records}), error


def _merge_fallback(provider: str, remote: List[str]) -> List[str]:
    return merge_model_records(remote, _load_fallback().get(provider) or [])


def _metadata_by_model(
    provider: str, remote_records: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    return metadata_by_model_records(_load_fallback().get(provider) or [], remote_records)


def _models_detailed(
    provider: str,
    model_ids: List[str],
    remote_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    return build_models_detailed(
        provider,
        model_ids,
        metadata_by_id=_metadata_by_model(provider, remote_records or []),
    )


async def get_models_for_provider(
    session,
    user_id: int,
    provider: str,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """返回模型 ID 与标准化能力详情，并带 TTL 缓存。"""
    api_key, _src = resolve_api_key(session, user_id, provider)
    if not api_key:
        models = _merge_fallback(provider, [])
        detailed = _models_detailed(provider, models)
        return {
            "models": models,
            "models_detailed": detailed,
            "runtime_models": _runtime_model_ids(detailed),
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
                "models_detailed": ent.get("models_detailed")
                or _models_detailed(provider, ent["models"]),
                "runtime_models": ent.get("runtime_models")
                or _runtime_model_ids(
                    ent.get("models_detailed") or _models_detailed(provider, ent["models"])
                ),
                "source": ent.get("source", "cache"),
                "fetched_at": ent.get("fetched_at_wall"),
                "error": ent.get("error"),
                "from_cache": True,
            }

    remote: List[str] = []
    remote_records: List[Dict[str, Any]] = []
    err: Optional[str] = None
    src = "remote"

    if provider == "minimax" and is_minimax_token_plan_key(api_key):
        raw_base = resolve_base_url(session, user_id, provider)
        remote_records, err = await _fetch_minimax_token_plan_records(
            api_key,
            base_url=raw_base,
        )
    elif provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        raw_base = resolve_base_url(session, user_id, provider)
        b = (raw_base or openai_compat_default_root(provider)).rstrip("/")
        if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
            b = b + "/v1"
        remote_records, err = await _fetch_openai_compatible_records(b, api_key, provider=provider)
    elif provider == "anthropic":
        remote_records, err = await _fetch_anthropic_records(api_key)
    elif provider == "google":
        remote_records, err = await _fetch_google_records(api_key)
    else:
        return {
            "models": [],
            "models_detailed": [],
            "runtime_models": [],
            "source": "unknown_provider",
            "fetched_at": None,
            "error": "unknown",
            "from_cache": False,
        }

    remote = sorted(
        {
            _model_id(item)
            for item in remote_records
            if _model_id(item) and not _model_id(item).startswith("ft:")
        }
    )

    merged = _merge_fallback(provider, remote)
    detailed = _models_detailed(provider, merged, remote_records)
    runtime_models = _runtime_model_ids(detailed)
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
        "models_detailed": detailed,
        "runtime_models": runtime_models,
        "error": err,
        "source": src,
        "fetched_at_wall": wall,
    }
    return {
        "models": merged,
        "models_detailed": detailed,
        "runtime_models": runtime_models,
        "source": src,
        "fetched_at": wall,
        "error": err,
        "from_cache": False,
    }


_PROBE_HTTPX_TIMEOUT = 10.0


async def _probe_one_provider_list(provider: str, api_key: str) -> Tuple[str, List[str]]:
    """BYOK 裸钥探测用：不合并本地 fallback，以远程拉到的非空模型 id 为准。"""
    if provider == "minimax" and is_minimax_token_plan_key(api_key):
        records, _ = await _fetch_minimax_token_plan_records(
            api_key,
            httpx_timeout=_PROBE_HTTPX_TIMEOUT,
        )
        return provider, sorted({str(item.get("id") or "") for item in records if item.get("id")})
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        b = openai_compat_default_root(provider).rstrip("/")
        if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
            b = b + "/v1"
        remote, _ = await _fetch_openai_compatible(
            b,
            api_key,
            provider=provider,
            httpx_timeout=_PROBE_HTTPX_TIMEOUT,
        )
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
        *[_probe_one_provider_list(p, key) for p in KNOWN_PROVIDERS],
        return_exceptions=True,
    )
    for p, res in zip(KNOWN_PROVIDERS, results):
        if isinstance(res, Exception):
            logger.debug("byok probe %s: %s", p, res)
            continue
        _pid, models = res
        if models and len(models) > 0:
            return p
    return None
