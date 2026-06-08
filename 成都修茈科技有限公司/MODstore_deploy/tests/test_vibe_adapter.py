"""测试 :mod:`modstore_server.integrations.vibe_adapter`。

只覆盖纯逻辑层(LLMClient 桥接、租户路径白名单、缓存),不打真实 LLM。
当 :mod:`vibe_coding` 不可导入时整体跳过,避免在 CI 环境抹掉信号。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

if importlib.util.find_spec("vibe_coding") is None:
    pytest.skip("vibe-coding 未安装,跳过适配器测试", allow_module_level=True)


def test_chat_dispatch_client_strips_markdown_fence(monkeypatch):
    from modstore_server.integrations.vibe_adapter import ChatDispatchLLMClient

    captured = {}

    async def fake_dispatch(provider, *, api_key, base_url, model, messages, max_tokens=None):
        captured["provider"] = provider
        captured["messages"] = messages
        return {"ok": True, "content": '```json\n{"k": 1}\n```\n'}

    monkeypatch.setattr("modstore_server.llm_chat_proxy.chat_dispatch", fake_dispatch)

    client = ChatDispatchLLMClient("openai", api_key="fake", model="gpt-4o-mini")
    out = client.chat("you are helpful", "produce JSON", json_mode=True)
    assert out == '{"k": 1}'
    assert captured["provider"] == "openai"
    # json_mode=True 会在 system 里追加 JSON 限制
    assert any("只输出一个合法 JSON" in (m.get("content") or "") for m in captured["messages"])


def test_chat_dispatch_client_raises_on_failure(monkeypatch):
    from vibe_coding import LLMError

    from modstore_server.integrations.vibe_adapter import ChatDispatchLLMClient

    async def failing_dispatch(*args, **kwargs):
        return {"ok": False, "error": "boom", "status": 500}

    monkeypatch.setattr("modstore_server.llm_chat_proxy.chat_dispatch", failing_dispatch)

    client = ChatDispatchLLMClient("openai", api_key="fake", model="gpt-4o-mini")
    with pytest.raises(LLMError):
        client.chat("s", "u", json_mode=False)


def test_ensure_within_workspace_rejects_traversal(tmp_path, monkeypatch):
    from modstore_server.integrations.vibe_adapter import (
        VibePathError,
        ensure_within_workspace,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MODSTORE_TENANT_WORKSPACE_ROOT", str(workspace / "{user_id}"))

    user_root = workspace / "42"
    user_root.mkdir()
    (user_root / "app").mkdir()

    resolved = ensure_within_workspace(user_root / "app", user_id=42)
    assert resolved == (user_root / "app").resolve()

    with pytest.raises(VibePathError):
        ensure_within_workspace(tmp_path / "outside", user_id=42)

    # 越界:试图访问别的用户工作区
    other = workspace / "99"
    other.mkdir()
    with pytest.raises(VibePathError):
        ensure_within_workspace(other, user_id=42)


def test_get_vibe_coder_caches_per_user_provider(monkeypatch, tmp_path):
    from modstore_server.integrations import vibe_adapter

    monkeypatch.setenv("VIBE_CODING_STORE_DIR", str(tmp_path / "vibe-data"))
    vibe_adapter.reset_vibe_coder_cache()

    constructed = []

    class _StubVibeCoder:
        def __init__(self, *, llm, store_dir, **kwargs):
            constructed.append((id(llm), str(store_dir)))
            self.llm = llm
            self.store_dir = Path(store_dir)

    def fake_import_facade():
        return (_StubVibeCoder, object)

    def fake_from_user(session, user_id, provider, model, *, default_max_tokens=4096):
        return object()

    monkeypatch.setattr(vibe_adapter, "_import_facade", fake_import_facade)
    monkeypatch.setattr(
        vibe_adapter.ChatDispatchLLMClient, "from_user", classmethod(lambda cls, *a, **k: object())
    )

    c1 = vibe_adapter.get_vibe_coder(user_id=1, provider="openai", model="gpt-4o-mini")
    c2 = vibe_adapter.get_vibe_coder(user_id=1, provider="openai", model="gpt-4o-mini")
    c3 = vibe_adapter.get_vibe_coder(user_id=2, provider="openai", model="gpt-4o-mini")
    c4 = vibe_adapter.get_vibe_coder(user_id=1, provider="deepseek", model="deepseek-chat")

    assert c1 is c2  # 同 user + 同 provider/model => 命中缓存
    assert c1 is not c3
    assert c1 is not c4
    assert len(constructed) == 3


def test_get_vibe_coder_requires_provider_model(monkeypatch):
    from modstore_server.integrations.vibe_adapter import (
        VibeIntegrationError,
        get_vibe_coder,
    )

    with pytest.raises(VibeIntegrationError):
        get_vibe_coder(user_id=1, provider="", model="gpt-4o-mini")
    with pytest.raises(VibeIntegrationError):
        get_vibe_coder(user_id=1, provider="openai", model="")
