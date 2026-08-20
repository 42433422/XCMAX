# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


async def _employee_chat(user_text: str, *, employee_id: str) -> str:
    """为指定员工跑一次 LLM 对话，返回文本。优先用管家自己的 LLM 凭证（共享）。"""
    from modstore_server.llm_chat_proxy import chat_dispatch

    provider, model, api_key, base_url = await _facade()._resolve_llm_for_butler()
    persona = _facade()._EMPLOYEE_PERSONAS.get(employee_id, _facade()._EMPLOYEE_FALLBACK_PERSONA)
    msgs: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {"role": "system", "content": persona},
        {
            "role": "system",
            "content": "本次对话来自 QQ 官方机器人入口。回答简洁，不超过 200 字，不要要求用户操作 web UI。",
        },
        {"role": "user", "content": user_text},
    ]
    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=msgs,
        max_tokens=600,
    )
    return str(result.get("content") or "").strip()


async def _resolve_llm_for_butler() -> _facade().Tuple[str, str, str, _facade().Optional[str]]:
    """解析数字管家自己用的 LLM 凭证。优先用员工自带的（``BUTLER_QQ_LLM_*``），
    其次才退回 ``BUTLER_QQ_BRIDGE_USER_ID`` 名下挂的真人钥匙。

    返回 ``(provider, model, api_key, base_url)``。
    """
    provider, model, api_key, base_url = _facade()._own_llm()
    if provider and api_key:
        return (provider, model or "gpt-4o-mini", api_key, base_url)
    bridge_uid = _facade()._bridge_user_id()
    if not bridge_uid:
        raise RuntimeError(
            "数字管家没有 LLM 钥匙：请配 BUTLER_QQ_LLM_PROVIDER + BUTLER_QQ_LLM_API_KEY（推荐，AI 员工自持），或退而求其次给 BUTLER_QQ_BRIDGE_USER_ID 指向一个有 API Key 的真人。"
        )
    from modstore_server.infrastructure.db import get_db
    from modstore_server.llm_key_resolver import (
        KNOWN_PROVIDERS,
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        resolve_api_key,
        resolve_base_url,
    )
    from modstore_server.models import User

    db_gen = get_db()
    db = next(db_gen)
    try:
        user = db.query(User).filter(User.id == bridge_uid).first()
        if not user:
            raise RuntimeError(f"BUTLER_QQ_BRIDGE_USER_ID={bridge_uid} 在 users 表中找不到")
        prefs: _facade().Dict[str, _facade().Any] = {}
        raw = getattr(user, "default_llm_json", None) or ""
        if raw.strip():
            try:
                prefs = _facade().json.loads(raw)
            except RECOVERABLE_ERRORS:
                prefs = {}
        provider = str(prefs.get("provider") or "").strip()
        model = str(prefs.get("model") or "").strip()
        if not provider or provider not in KNOWN_PROVIDERS:
            for p in KNOWN_PROVIDERS:
                key, _src = resolve_api_key(db, bridge_uid, p)
                if key:
                    provider = p
                    break
        if not provider:
            raise RuntimeError("数字管家：bridge user 名下未配任何 LLM 供应商")
        if not model:
            model = "gpt-4o-mini"
        api_key, _src = resolve_api_key(db, bridge_uid, provider)
        if not api_key:
            raise RuntimeError(f"数字管家：bridge user 在 {provider} 下没有 API Key")
        base_url = (
            resolve_base_url(db, bridge_uid, provider)
            if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
            else None
        )
        return (provider, model, api_key, base_url)
    finally:
        try:
            next(db_gen, None)
        except RECOVERABLE_ERRORS:
            pass


async def _butler_chat(user_text: str) -> str:
    """复用 ``agent_butler_api`` 的 system prompt，跑一次 LLM 拿一段文本回复。"""
    from modstore_server.agent_butler_api import BUTLER_SYSTEM_PROMPT
    from modstore_server.llm_chat_proxy import chat_dispatch

    provider, model, api_key, base_url = await _facade()._resolve_llm_for_butler()
    msgs: _facade().List[_facade().Dict[str, _facade().Any]] = [
        {"role": "system", "content": BUTLER_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "本次对话来自 QQ 官方机器人入口，不是网页。回答尽量简短，不要要求用户操作 web UI。",
        },
        {"role": "user", "content": user_text},
    ]
    result = await chat_dispatch(
        provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=msgs,
        max_tokens=800,
    )
    return str(result.get("content") or "").strip()
