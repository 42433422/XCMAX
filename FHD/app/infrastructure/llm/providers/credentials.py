"""统一凭证解析：env → XCauto/OPENAI/DEEPSEEK → 可选 resources 配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass

XCAUTO_DEFAULT_BASE_URL = "https://xiu-ci.com/v1"
XCAUTO_DEFAULT_MODEL = "xcauto-account"
_XCAUTO_PROVIDER_ALIASES = {"xcauto", "xcauto-account", "xcauto-default", "xiuci", "xiuci-account"}


@dataclass(frozen=True)
class LLMCredentials:
    api_key: str
    api_url: str
    model: str


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _chat_url_from_base(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _base_url_from_chat_url(api_url: str) -> str:
    url = str(api_url or "").strip().rstrip("/")
    suffix = "/chat/completions"
    if url.endswith(suffix):
        return url[: -len(suffix)]
    return url


def _env_wants_xcauto() -> bool:
    provider = (
        (os.environ.get("LLM_PROVIDER") or os.environ.get("XCAGI_LLM_PROVIDER") or "")
        .strip()
        .lower()
    )
    model = (
        (
            os.environ.get("XCAUTO_MODEL")
            or os.environ.get("LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or ""
        )
        .strip()
        .lower()
    )
    base = (
        (
            os.environ.get("XCAUTO_BASE_URL")
            or os.environ.get("XCAUTO_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
            or ""
        )
        .strip()
        .lower()
    )
    return (
        provider in _XCAUTO_PROVIDER_ALIASES
        or model in _XCAUTO_PROVIDER_ALIASES
        or "xiu-ci.com" in base
        or "xiuci" in base
    )


def resolve_xcauto_credentials() -> LLMCredentials | None:
    """解析修茈 XCauto OpenAI-compatible 网关配置。

    支持两种常见配置方式：
    - 显式：``XCAUTO_API_KEY`` / ``XCAUTO_BASE_URL`` / ``XCAUTO_MODEL``
    - OpenAI SDK 兼容：``OPENAI_API_KEY`` + ``OPENAI_BASE_URL=https://xiu-ci.com/v1``
    """
    key = _first_env(("XCAUTO_API_KEY", "XCAUTO_PAT", "XIUCI_API_KEY"))
    if not key and _env_wants_xcauto():
        key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None

    explicit_url = _first_env(("XCAUTO_API_URL", "XCAUTO_CHAT_COMPLETIONS_URL"))
    base = _first_env(("XCAUTO_BASE_URL", "XCAUTO_API_BASE"))
    if not base and _env_wants_xcauto():
        base = (os.environ.get("OPENAI_BASE_URL") or "").strip()
    if not explicit_url:
        explicit_url = _chat_url_from_base(base or XCAUTO_DEFAULT_BASE_URL)

    model = _first_env(("XCAUTO_MODEL",))
    if not model and _env_wants_xcauto():
        model = (
            os.environ.get("LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("DEEPSEEK_MODEL")
            or ""
        ).strip()
    return LLMCredentials(
        api_key=key,
        api_url=explicit_url,
        model=model or XCAUTO_DEFAULT_MODEL,
    )


def default_chat_completions_url() -> str:
    creds = resolve_xcauto_credentials()
    if creds:
        return creds.api_url
    creds = resolve_deepseek_credentials()
    return creds.api_url if creds else "https://api.deepseek.com/v1/chat/completions"


def resolve_deepseek_credentials() -> LLMCredentials | None:
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        return None
    url = (
        os.environ.get("DEEPSEEK_API_URL") or ""
    ).strip() or "https://api.deepseek.com/v1/chat/completions"
    model = (os.environ.get("DEEPSEEK_MODEL") or "").strip() or "deepseek-chat"
    return LLMCredentials(api_key=key, api_url=url, model=model)


def resolve_openai_env_credentials() -> tuple[str, str | None]:
    """与 infrastructure.llm.client._first_api_key 一致。"""
    explicit_xc_key = _first_env(("XCAUTO_API_KEY", "XCAUTO_PAT", "XIUCI_API_KEY"))
    if explicit_xc_key:
        xc = resolve_xcauto_credentials()
        if xc:
            return xc.api_key, _base_url_from_chat_url(xc.api_url) or XCAUTO_DEFAULT_BASE_URL

    oa = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if oa:
        base = (os.environ.get("OPENAI_BASE_URL") or "").strip()
        if not base and _env_wants_xcauto():
            base = XCAUTO_DEFAULT_BASE_URL
        return oa, base or None
    xc = resolve_xcauto_credentials()
    if xc:
        return xc.api_key, _base_url_from_chat_url(xc.api_url) or XCAUTO_DEFAULT_BASE_URL
    ds = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if ds:
        base = (os.environ.get("OPENAI_BASE_URL") or "").strip() or "https://api.deepseek.com"
        return ds, base
    return "", None


def resolve_default_chat_model() -> str:
    xc = resolve_xcauto_credentials()
    if xc:
        return xc.model
    return (
        os.environ.get("DP_MODEL")
        or os.environ.get("DEEPSEEK_MODEL")
        or os.environ.get("LLM_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "deepseek-chat"
    )


def resolve_default_openai_provider() -> str:
    provider = (
        os.environ.get("LLM_PROVIDER") or os.environ.get("XCAGI_LLM_PROVIDER") or ""
    ).strip()
    if provider:
        return provider.lower()
    _key, base = resolve_openai_env_credentials()
    if base and ("xiu-ci.com" in base.lower() or "xiuci" in base.lower()):
        return "xcauto"
    if (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        return "deepseek"
    return "openai"
