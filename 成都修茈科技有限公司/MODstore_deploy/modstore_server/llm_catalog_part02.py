# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_catalog")


async def _fetch_openai_compatible_records(
    base_url: str, api_key: str, *, provider: str = "", httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str]]:
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
        except _facade().RECOVERABLE_ERRORS:
            return ([], "invalid json in models response")
        if isinstance(data, dict) and data.get("error") is not None:
            err_o = data["error"]
            if isinstance(err_o, dict):
                parts: _facade().List[str] = []
                for k in ("type", "code", "param", "message"):
                    v = err_o.get(k)
                    if v is not None and str(v).strip():
                        parts.append(f"{k}={str(v).strip()[:200]}")
                summary = ";".join(parts) if parts else str(err_o)[:300]
            else:
                summary = str(err_o)[:300]
            return ([], f"openai_error:{summary}")
        items = _facade()._openai_style_items(data)
        if items is None:
            return ([], "unexpected models response shape")
        if provider == "openrouter":
            try:
                video_response = await client.get(
                    f"{base_url.rstrip('/')}/videos/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=httpx_timeout,
                )
                if video_response.status_code < 400:
                    video_items = _facade()._openai_style_items(video_response.json()) or []
                    for video_item in video_items:
                        architecture = video_item.get("architecture")
                        if not isinstance(architecture, dict):
                            architecture = {}
                            video_item["architecture"] = architecture
                        architecture.setdefault("output_modalities", ["video"])
                        video_item.setdefault("type", "video")
                    items.extend(video_items)
            except _facade().BOUNDARY_ERRORS as exc:
                _facade().logger.debug(
                    "openrouter video catalog fetch failed: %s", type(exc).__name__
                )
        if provider == "siliconflow":

            async def _typed_items(
                model_type: str,
            ) -> _facade().List[_facade().Dict[str, _facade().Any]]:
                try:
                    typed_response = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        params={"type": model_type},
                        timeout=httpx_timeout,
                    )
                    if typed_response.status_code >= 400:
                        return []
                    typed_items = _facade()._openai_style_items(typed_response.json()) or []
                    for typed_item in typed_items:
                        typed_item.setdefault("type", model_type)
                    return typed_items
                except _facade().BOUNDARY_ERRORS as exc:
                    _facade().logger.debug(
                        "siliconflow %s catalog fetch failed: %s",
                        model_type,
                        type(exc).__name__,
                    )
                    return []

            typed_groups = await _facade().asyncio.gather(
                *[_typed_items(model_type) for model_type in ("text", "image", "audio", "video")]
            )
            for typed_items in typed_groups:
                items.extend(typed_items)
        allowed = set(
            _facade()._filter_openai_style(
                [str(x.get("id", "")).strip() for x in items if isinstance(x, dict)]
            )
        )
        records_by_id: _facade().Dict[str, _facade().Dict[str, _facade().Any]] = {}
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
            return ([], "empty model list")
        return (records, None)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("openai_compatible models fetch failed: %s", type(e).__name__)
        return ([], str(e))


async def _fetch_openai_compatible(
    base_url: str, api_key: str, *, provider: str = "", httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[str], _facade().Optional[str]]:
    records, error = await _facade()._fetch_openai_compatible_records(
        base_url, api_key, provider=provider, httpx_timeout=httpx_timeout
    )
    return (sorted({str(item.get("id") or "") for item in records}), error)


async def _fetch_anthropic_compatible_records(
    api_key: str, *, base_url: str, provider_label: str, httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str]]:
    url = f"{base_url.rstrip('/')}/v1/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        r = await client.get(
            url,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=httpx_timeout,
        )
        if r.status_code >= 400:
            return ([], f"http {r.status_code}")
        data = r.json()
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return ([], "unexpected response")
        records: _facade().List[_facade().Dict[str, _facade().Any]] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            mid = str(x.get("id") or x.get("name") or "").strip()
            if mid:
                record = dict(x)
                record["id"] = mid
                record["_catalog_origin"] = "provider_api"
                records.append(record)
        return (records, None)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning(
            "%s anthropic-compatible models fetch failed: %s",
            provider_label,
            type(e).__name__,
        )
        return ([], str(e))


async def _fetch_anthropic_records(
    api_key: str, *, httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str]]:
    return await _facade()._fetch_anthropic_compatible_records(
        api_key,
        base_url="https://api.anthropic.com",
        provider_label="anthropic",
        httpx_timeout=httpx_timeout,
    )


async def _fetch_minimax_token_plan_records(
    api_key: str,
    *,
    base_url: _facade().Optional[str] = None,
    httpx_timeout: float = 30.0,
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str]]:
    return await _facade()._fetch_anthropic_compatible_records(
        _facade().normalize_minimax_api_key(api_key),
        base_url=_facade().minimax_anthropic_base_url(base_url),
        provider_label="minimax_token_plan",
        httpx_timeout=httpx_timeout,
    )


async def _fetch_anthropic(
    api_key: str, *, httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[str], _facade().Optional[str]]:
    records, error = await _facade()._fetch_anthropic_records(api_key, httpx_timeout=httpx_timeout)
    return (sorted({str(item.get("id") or "") for item in records}), error)


async def _fetch_google_records(
    api_key: str, *, httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[_facade().Dict[str, _facade().Any]], _facade().Optional[str]]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    from modstore_server.infrastructure.http_clients import get_external_client

    try:
        client = get_external_client()
        r = await client.get(url, params={"key": api_key}, timeout=httpx_timeout)
        if r.status_code >= 400:
            return ([], f"http {r.status_code}")
        data = r.json()
        items = data.get("models") or []
        records: _facade().List[_facade().Dict[str, _facade().Any]] = []
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
        return (records, None)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.warning("google models fetch failed: %s", type(e).__name__)
        return ([], str(e))


async def _fetch_google(
    api_key: str, *, httpx_timeout: float = 30.0
) -> _facade().Tuple[_facade().List[str], _facade().Optional[str]]:
    records, error = await _facade()._fetch_google_records(api_key, httpx_timeout=httpx_timeout)
    return (sorted({str(item.get("id") or "") for item in records}), error)


def _merge_fallback(provider: str, remote: _facade().List[str]) -> _facade().List[str]:
    return _facade().merge_model_records(remote, _facade()._load_fallback().get(provider) or [])


def _metadata_by_model(
    provider: str, remote_records: _facade().List[_facade().Dict[str, _facade().Any]]
) -> _facade().Dict[str, _facade().Dict[str, _facade().Any]]:
    return _facade().metadata_by_model_records(
        _facade()._load_fallback().get(provider) or [], remote_records
    )


def _models_detailed(
    provider: str,
    model_ids: _facade().List[str],
    remote_records: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().List[_facade().Dict[str, _facade().Any]]:
    return _facade().build_models_detailed(
        provider,
        model_ids,
        metadata_by_id=_facade()._metadata_by_model(provider, remote_records or []),
    )
