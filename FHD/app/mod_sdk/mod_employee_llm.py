"""
Mod 员工脚本用的窄 LLM 入口（经 ``app.mod_sdk`` 暴露）。

由 MODstore 生成的 ``mods/<id>/backend/blueprints.py`` 内 ``_call_llm`` 优先调用本模块，
避免 Mod 代码直接依赖 ``app.services.*`` 或 ``modstore_server``。

支持 OpenAI 兼容 Chat Completions：
- 默认委托 ``AIConversationService.call_deepseek_api`` 兼容别名（实际走宿主统一 LLM Provider）。
- 可选：设置 ``XCAGI_LLM_PROVIDER`` + ``{PROVIDER}_API_KEY`` + ``{PROVIDER}_BASE_URL``（或内置默认 URL）
  时，对该 URL 直接发起 ``httpx`` 请求（真正切换供应商，而非仅改文案）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DEFAULT_CHAT_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "xcauto": "https://xiu-ci.com/v1/chat/completions",
    "xiuci": "https://xiu-ci.com/v1/chat/completions",
}


def _chat_url_from_base_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    if any(base.endswith(f"/v{i}") for i in range(1, 6)):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _resolve_provider_override() -> dict[str, Any]:
    """若配置了 provider + key（及可选 base_url），则走直连 OpenAI 兼容 API。"""
    provider = os.environ.get("XCAGI_LLM_PROVIDER", "").strip().lower()
    api_key = ""
    base_url: str | None = None
    model: str | None = None

    if provider:
        env_key = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(env_key, "").strip()
        env_base = f"{provider.upper()}_BASE_URL"
        bu = os.environ.get(env_base, "").strip()
        if bu:
            base_url = bu.rstrip("/")
        model = os.environ.get(f"{provider.upper()}_MODEL", "").strip() or None
    else:
        try:
            from app.infrastructure.llm.providers.credentials import (
                resolve_default_chat_model,
                resolve_default_openai_provider,
                resolve_openai_env_credentials,
            )

            api_key, base_url = resolve_openai_env_credentials()
            provider = resolve_default_openai_provider()
            model = resolve_default_chat_model()
        except RECOVERABLE_ERRORS:
            logger.debug(
                "mod_employee_complete: unified LLM credentials unavailable", exc_info=True
            )

    if not api_key or not provider:
        return {"use_direct": False}

    if not base_url:
        base_url = _DEFAULT_CHAT_URLS.get(provider)
    if not base_url:
        return {
            "use_direct": False,
            "error": f"未设置 {provider.upper()}_BASE_URL，且无内置默认 chat/completions URL",
        }

    chat_url = _chat_url_from_base_url(base_url)

    if not model:
        model = os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "").strip() or (
            "xcauto-account"
            if provider in {"xcauto", "xiuci"}
            else "gpt-4o-mini"
            if provider == "openai"
            else "deepseek-chat"
        )

    return {
        "use_direct": True,
        "api_key": api_key,
        "chat_url": chat_url,
        "model": model,
        "provider": provider,
    }


# 自动故障转移候选 provider（按优先级）。主出口不可用时，自动改用其他已配置且可用的 provider。
_FALLBACK_PROVIDERS: tuple[str, ...] = (
    "mimo",
    "openai",
    "deepseek",
    "qwen",
    "moonshot",
    "xcauto",
    "xiuci",
)


def _resolve_fallback_overrides(exclude_provider: str = "") -> list[dict[str, Any]]:
    """收集其它已配置的 OpenAI 兼容 provider，作为主出口失败时的自动切换候选。"""
    exclude = (exclude_provider or "").strip().lower()
    out: list[dict[str, Any]] = []
    for prov in _FALLBACK_PROVIDERS:
        if prov == exclude:
            continue
        key = os.environ.get(f"{prov.upper()}_API_KEY", "").strip()
        base = os.environ.get(f"{prov.upper()}_BASE_URL", "").strip()
        if not key or not base:
            continue
        model = (
            os.environ.get(f"{prov.upper()}_MODEL", "").strip()
            or os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "").strip()
        )
        if not model:
            continue
        out.append(
            {
                "use_direct": True,
                "api_key": key,
                "chat_url": _chat_url_from_base_url(base.rstrip("/")),
                "model": model,
                "provider": prov,
            }
        )
    return out


async def _call_openai_compatible_chat(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    chat_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    response_format: Any,
) -> dict[str, Any] | None:
    import httpx

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }
    if response_format is not None:
        payload["response_format"] = response_format

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            r = await client.post(chat_url, headers=headers, json=payload)
            r.raise_for_status()
            return cast("dict[str, Any] | None", r.json())
    except RECOVERABLE_ERRORS as e:  # noqa: BLE001
        logger.exception("mod_employee_complete: OpenAI-compatible chat 请求失败: %s", e)
        return None


async def mod_employee_complete(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    response_format: Any = None,
) -> dict[str, Any]:
    """
    为员工 ``run(payload, ctx)`` 提供单次补全，返回形状与 MODstore ``chat_dispatch`` 对齐::

        {"success": bool, "content": str, "error": str}

    ``response_format`` 若不为 None，会原样传入底层 API（若上游支持）。
    """
    if not isinstance(messages, list) or not messages:
        return {"success": False, "content": "", "error": "messages 必须为非空列表"}

    override = _resolve_provider_override()
    if override.get("error"):
        return {"success": False, "content": "", "error": str(override["error"])[:500]}

    # 直连候选：主 provider + 其他已配置 provider 作为自动故障转移。
    # 主出口（如 api.b.ai）连不上/失败时，自动切换到下一个可用的（如 MIMO），不再直接报错。
    direct_candidates: list[dict[str, Any]] = []
    primary_provider = str(override.get("provider") or "")
    if override.get("use_direct"):
        direct_candidates.append(override)
    direct_candidates.extend(_resolve_fallback_overrides(exclude_provider=primary_provider))

    for cand in direct_candidates:
        raw = await _call_openai_compatible_chat(
            messages,
            api_key=str(cand["api_key"]),
            chat_url=str(cand["chat_url"]),
            model=str(cand["model"]),
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        if raw:
            parsed = _parse_chat_completions_response(raw)
            if parsed.get("success"):
                if str(cand.get("provider") or "") != primary_provider:
                    logger.warning(
                        "mod_employee_complete: 主 LLM(%s) 不可用，已自动切换到 %s",
                        primary_provider or "default",
                        cand.get("provider"),
                    )
                return parsed
    if direct_candidates:
        logger.warning("mod_employee_complete: 所有直连 LLM 候选均失败，回退宿主通道")
    # 全部直连候选失败 → 落到下方宿主 AIConversationService 通道。

    try:
        from app.services.ai_conversation_service import get_ai_conversation_service
    except ImportError as e:
        logger.warning("mod_employee_complete: get_ai_conversation_service 不可用: %s", e)
        return {
            "success": False,
            "content": "",
            "error": "get_ai_conversation_service not available",
        }

    svc = get_ai_conversation_service()
    try:
        from app.infrastructure.llm.providers.registry import get_active_provider

        active_provider = get_active_provider(conversation_service=svc)
    except RECOVERABLE_ERRORS:
        active_provider = None
    if active_provider is None:
        return {
            "success": False,
            "content": "",
            "error": "宿主未配置 OpenAI-compatible/XCauto LLM 凭证，无法为员工调用 LLM",
        }

    kwargs: dict[str, Any] = {}
    if response_format is not None:
        kwargs["response_format"] = response_format

    try:
        raw: dict[str, Any] | None = await svc.call_deepseek_api(
            messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
            **kwargs,
        )
    except RECOVERABLE_ERRORS as e:  # noqa: BLE001
        logger.exception("mod_employee_complete: call_deepseek_api 异常")
        return {"success": False, "content": "", "error": str(e)[:500]}

    if not raw:
        return {"success": False, "content": "", "error": "LLM 返回空（请检查密钥与网络）"}

    return _parse_chat_completions_response(raw)


def _parse_chat_completions_response(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        choices = raw.get("choices")
        if not choices:
            return {"success": False, "content": "", "error": "LLM 响应缺少 choices"}
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            return {"success": False, "content": "", "error": "LLM 响应缺少 message.content"}
        return {"success": True, "content": str(content), "error": ""}
    except (KeyError, IndexError, TypeError) as e:
        return {"success": False, "content": "", "error": f"无法解析 LLM 响应: {e}"[:500]}
