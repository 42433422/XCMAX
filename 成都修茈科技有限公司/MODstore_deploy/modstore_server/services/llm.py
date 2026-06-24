"""LLM chat service port.

Future state: replaced by an HTTP client to a dedicated LLM service. Today the
default implementation simply forwards to ``llm_chat_proxy.chat_dispatch`` so
existing behaviour is preserved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LlmChatRequest:
    provider: str
    model: str
    messages: List[Dict[str, str]]
    api_key: str = ""
    base_url: Optional[str] = None
    max_tokens: Optional[int] = None
    user_id: Optional[int] = None
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmChatResponse:
    ok: bool
    content: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    status: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "LlmChatResponse":
        return cls(
            ok=bool(payload.get("ok")),
            content=str(payload.get("content") or ""),
            usage=dict(payload.get("usage") or {}),
            error=str(payload.get("error") or ""),
            status=payload.get("status"),
            raw=dict(payload.get("raw") or {}),
        )


class LlmChatClient(ABC):
    @abstractmethod
    async def chat(self, request: LlmChatRequest) -> LlmChatResponse: ...

    async def chat_stream(self, request: LlmChatRequest) -> AsyncIterator[dict[str, Any]]:
        """Stream tokens / usage events; default falls back to non-streaming :meth:`chat`."""

        res = await self.chat(request)
        if res.ok and res.content:
            yield {"type": "delta", "delta": res.content}
        if res.usage:
            yield {"type": "usage", "usage": res.usage}
        if not res.ok:
            yield {"type": "error", "error": res.error or "upstream error"}


class InProcessLlmChatClient(LlmChatClient):
    """Default port wired to the existing ``llm_chat_proxy``."""

    async def chat(self, request: LlmChatRequest) -> LlmChatResponse:
        from modstore_server.llm_chat_proxy import chat_dispatch

        result = await chat_dispatch(
            request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            messages=list(request.messages),
            max_tokens=request.max_tokens,
        )
        return LlmChatResponse.from_dict(result)

    async def chat_stream(self, request: LlmChatRequest) -> AsyncIterator[dict[str, Any]]:
        from modstore_server.llm_chat_proxy import chat_dispatch_stream

        async for ev in chat_dispatch_stream(
            request.provider,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            messages=list(request.messages),
            max_tokens=request.max_tokens,
        ):
            yield ev


async def chat_dispatch_via_session(
    session: Any,
    user_id: int,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
    forbid_reasoning_fallback: bool = False,
) -> dict[str, Any]:
    """Resolve BYOK / platform keys via ``llm_key_resolver`` then call ``chat_dispatch``.

    Keeps ``employee_executor`` / ``workflow_nl_graph`` off direct ``llm_*`` imports.
    """

    # 后台 loop 平台作用域：强制平台 Key + 零配额，绝不计入任何用户。
    # 这是统一兜底——无论调用来自路由器、cognition 还是其它路径，只要处于作用域内，
    # 都改走平台 only；无平台 Key 时干净失败而不是回落到用户配额（避免钱漏）。
    try:
        from modstore_server.platform_llm_scope import platform_llm_scope_active

        _platform_scope = platform_llm_scope_active()
    except Exception:
        _platform_scope = False
    if _platform_scope:
        p_prov, p_mdl = resolve_platform_bench_llm()
        if not p_prov or not p_mdl:
            return {
                "ok": False,
                "error": (
                    "平台未配置可用 LLM（后台 loop 已跳过以避免计入用户配额；"
                    "请配置平台 API Key 或 MODSTORE_EMPLOYEE_BENCH_PROVIDER / "
                    "MODSTORE_EMPLOYEE_BENCH_MODEL）"
                ),
                "status": "platform_llm_unconfigured",
            }
        return await chat_dispatch_via_platform_only(
            p_prov, p_mdl, messages, max_tokens=max_tokens
        )

    from modstore_server.llm_chat_proxy import chat_dispatch
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )

    api_key, _source = resolve_api_key(session, user_id, provider)
    if not api_key:
        return {"ok": False, "error": f"missing api key for provider: {provider}"}
    base_url = None
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        base_url = resolve_base_url(session, user_id, provider)

    uid = int(user_id or 0)
    if uid > 0:
        from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit

        require_llm_credit(session, uid, 1)

    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        forbid_reasoning_fallback=forbid_reasoning_fallback,
    )
    if uid > 0 and result.get("ok"):
        try:
            consume_llm_credit(session, uid, 1)
        except Exception:
            pass
    return result


# ── Platform-only bench helpers ───────────────────────────────────────────────

# Sensible default model per provider when no env override is given.
_BENCH_DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-20241022",
    "google": "gemini-2.0-flash",
    "siliconflow": "deepseek-ai/DeepSeek-V3",
    "dashscope": "qwen-turbo",
    "moonshot": "moonshot-v1-8k",
    # 小米网关型号以控制台为准；flash 在部分 token 计划不可用，基准默认与别名统一到 v2.5-pro
    "xiaomi": "mimo-v2.5-pro",
    "minimax": "abab6.5s-chat",
    "doubao": "doubao-1-5-lite-32k-240828",
    "wenxin": "ernie-4.0-turbo-8k",
    "hunyuan": "hunyuan-lite",
    "zhipu": "glm-4-flash",
    "xunfei": "generalv3.5",
    "yi": "yi-lightning",
    "stepfun": "step-2-16k",
    "baichuan": "Baichuan4",
    "sensetime": "nova-ptc-xl-v2",
    "groq": "llama-3.3-70b-versatile",
    "together": "meta-llama/Llama-3-8b-chat-hf",
    "openrouter": "openai/gpt-4o-mini",
}


def resolve_platform_bench_llm() -> tuple[str, str] | tuple[None, None]:
    """Resolve provider + model for bench evaluation using platform keys only.

    Priority:
    1. Env ``MODSTORE_EMPLOYEE_BENCH_PROVIDER`` + ``MODSTORE_EMPLOYEE_BENCH_MODEL``
    2. First ``KNOWN_PROVIDERS`` entry with a ``platform_api_key`` configured,
       paired with the ``_BENCH_DEFAULT_MODELS`` fallback for that provider.

    Returns ``(provider, model)`` or ``(None, None)`` when no platform key is
    available.  Never touches user BYOK credentials.
    """
    import os

    from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, platform_api_key

    env_prov = (os.environ.get("MODSTORE_EMPLOYEE_BENCH_PROVIDER") or "").strip()
    env_mdl = (os.environ.get("MODSTORE_EMPLOYEE_BENCH_MODEL") or "").strip()

    if env_prov and env_mdl and platform_api_key(env_prov):
        return env_prov, env_mdl

    for prov in KNOWN_PROVIDERS:
        if not platform_api_key(prov):
            continue
        mdl = (env_mdl if env_prov == prov else "") or _BENCH_DEFAULT_MODELS.get(prov, "")
        if mdl:
            return prov, mdl

    return None, None


async def chat_dispatch_via_platform_only(
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """Call ``chat_dispatch`` using the server-side platform API key only.

    Does not consult user BYOK credentials.  Used for bench evaluation so
    costs are attributed to the platform, not individual users.
    """
    from modstore_server.llm_chat_proxy import chat_dispatch
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        platform_api_key,
        platform_base_url,
    )

    api_key = platform_api_key(provider)
    if not api_key:
        return {"ok": False, "error": f"no platform api key configured for provider: {provider}"}

    base_url = None
    if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS:
        base_url = platform_base_url(provider)

    return await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )


_LOCK = Lock()
_default: LlmChatClient | None = None


def get_default_llm_client() -> LlmChatClient:
    global _default
    with _LOCK:
        if _default is None:
            _default = InProcessLlmChatClient()
        return _default


def set_default_llm_client(client: Optional[LlmChatClient]) -> None:
    global _default
    with _LOCK:
        _default = client


__all__ = [
    "InProcessLlmChatClient",
    "LlmChatClient",
    "LlmChatRequest",
    "LlmChatResponse",
    "chat_dispatch_via_platform_only",
    "chat_dispatch_via_session",
    "get_default_llm_client",
    "resolve_platform_bench_llm",
    "set_default_llm_client",
]
