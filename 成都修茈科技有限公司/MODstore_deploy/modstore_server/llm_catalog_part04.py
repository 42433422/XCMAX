# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.llm_catalog")


async def _probe_one_provider_list(
    provider: str, api_key: str
) -> _facade().Tuple[str, _facade().List[str]]:
    """BYOK 裸钥探测用：不合并本地 fallback，以远程拉到的非空模型 id 为准。"""
    if provider == "minimax" and _facade().is_minimax_token_plan_key(api_key):
        records, _ = await _facade()._fetch_minimax_token_plan_records(
            api_key, httpx_timeout=_facade()._PROBE_HTTPX_TIMEOUT
        )
        return (
            provider,
            sorted({str(item.get("id") or "") for item in records if item.get("id")}),
        )
    if provider in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        b = _facade().openai_compat_default_root(provider).rstrip("/")
        if not (b.endswith("/v1") or b.endswith("/v2") or b.endswith("/v3") or b.endswith("/v4")):
            b = b + "/v1"
        remote, _ = await _facade()._fetch_openai_compatible(
            b, api_key, provider=provider, httpx_timeout=_facade()._PROBE_HTTPX_TIMEOUT
        )
        return (provider, remote)
    if provider == "anthropic":
        remote, _ = await _facade()._fetch_anthropic(
            api_key, httpx_timeout=_facade()._PROBE_HTTPX_TIMEOUT
        )
        return (provider, remote)
    if provider == "google":
        remote, _ = await _facade()._fetch_google(
            api_key, httpx_timeout=_facade()._PROBE_HTTPX_TIMEOUT
        )
        return (provider, remote)
    return (provider, [])


async def probe_first_matching_provider(api_key: str) -> _facade().Optional[str]:
    """
    对裸 API Key 在 KNOWN_PROVIDERS 上并行试拉 /models，按列表顺序取首个返回非空模型列表的厂商。
    不访问用户库、不合并兜底列表。
    """
    key = (api_key or "").strip()
    if not key or len(key) < 8:
        return None
    results = await _facade().asyncio.gather(
        *[_facade()._probe_one_provider_list(p, key) for p in _facade().KNOWN_PROVIDERS],
        return_exceptions=True,
    )
    for p, res in zip(_facade().KNOWN_PROVIDERS, results):
        if isinstance(res, Exception):
            _facade().logger.debug("byok probe %s: %s", p, res)
            continue
        _pid, models = res
        if models and len(models) > 0:
            return p
    return None
