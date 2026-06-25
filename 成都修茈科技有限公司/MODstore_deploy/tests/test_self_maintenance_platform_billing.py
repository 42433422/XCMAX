"""平台身份计费旁路：自维护 loop 以 user_id=0 跑时不应过个人 llm_calls 配额闸。

验证 ``chat_dispatch_via_session`` 的契约（``services/llm.py``）：
- ``uid > 0`` → 调 ``require_llm_credit`` / ``consume_llm_credit``（按真实用户配额计费）。
- ``uid == 0`` → 完全跳过配额闸，改用平台密钥。即便用户配额已耗尽（require 抛
  ``403: 配额不足: llm_calls``），平台身份也不受影响——这正是修复
  ``self_maintenance_loop_runner`` 历史 99.6% 失败（记到 owner 配额）的根因路径。
"""

import asyncio

from fastapi import HTTPException

import modstore_server.llm_billing as llm_billing
import modstore_server.llm_chat_proxy as llm_chat_proxy
import modstore_server.llm_key_resolver as llm_key_resolver
import modstore_server.quota_middleware as quota_middleware
from modstore_server.services.llm import chat_dispatch_via_session


def _patch_llm(monkeypatch, *, require_raises=False):
    """打桩 LLM 解析/分发/配额，返回记录调用的 spy 容器。"""
    calls = {"require": [], "consume": []}

    monkeypatch.setattr(
        llm_key_resolver, "resolve_api_key", lambda *a, **k: ("platform-key", "platform")
    )
    monkeypatch.setattr(llm_key_resolver, "resolve_base_url", lambda *a, **k: None)

    async def _fake_chat_dispatch(*a, **k):
        return {"ok": True, "text": "ok"}

    monkeypatch.setattr(llm_chat_proxy, "chat_dispatch", _fake_chat_dispatch)

    # 新版按 token 计费：consume 走 calculate_charge/usage_from_response 旁路。
    # 打桩这两者使 consume 路径可达且不依赖真实 DB/定价（否则被 services.llm
    # 里的 try/except 吞掉，consume 永不触发）。
    monkeypatch.setattr(llm_billing, "usage_from_response", lambda *a, **k: {})
    monkeypatch.setattr(llm_billing, "calculate_charge", lambda *a, **k: 0)

    def _require(session, uid, amount=1):
        calls["require"].append((uid, amount))
        if require_raises:
            raise HTTPException(403, "配额不足: llm_calls")
        return "quota"

    def _consume(session, uid, amount=1, *, charge=None):
        calls["consume"].append((uid, amount))
        return "quota"

    monkeypatch.setattr(quota_middleware, "require_llm_credit", _require)
    monkeypatch.setattr(quota_middleware, "consume_llm_credit", _consume)
    return calls


def _dispatch(user_id):
    return asyncio.run(
        chat_dispatch_via_session(
            session=object(),
            user_id=user_id,
            provider="anthropic",
            model="claude-3-5-haiku-20241022",
            messages=[{"role": "user", "content": "hi"}],
        )
    )


def test_platform_identity_skips_quota_gate(monkeypatch):
    calls = _patch_llm(monkeypatch)

    result = _dispatch(0)

    assert result["ok"] is True
    assert calls["require"] == []  # 平台身份不查配额
    assert calls["consume"] == []  # 平台身份不计费


def test_real_user_passes_through_quota_gate(monkeypatch):
    calls = _patch_llm(monkeypatch)

    result = _dispatch(5)

    assert result["ok"] is True
    assert calls["require"] == [(5, 1)]
    assert calls["consume"] == [(5, 1)]


def test_platform_identity_escapes_quota_exhaustion_403(monkeypatch):
    # 配额耗尽场景：真实用户撞 403，平台身份照常返回（即修复后的自维护 loop 路径）。
    _patch_llm(monkeypatch, require_raises=True)

    raised = False
    try:
        _dispatch(5)
    except HTTPException as exc:
        raised = exc.status_code == 403
    assert raised, "真实用户在配额耗尽时应抛 403"

    # 平台身份（user_id=0）不触发 require_llm_credit，故不会 403。
    result = _dispatch(0)
    assert result["ok"] is True
