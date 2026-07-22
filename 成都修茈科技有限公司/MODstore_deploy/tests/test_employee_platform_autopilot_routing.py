from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _hardcoded_config() -> dict:
    return {
        "cognition": {
            "agent": {
                "system_prompt": "你是平台 AI 员工",
                "model": {
                    "provider": "deepseek",
                    "model_name": "deepseek-chat",
                    "max_tokens": 128,
                },
            }
        }
    }


def test_platform_employee_ignores_hardcoded_model_and_uses_active_driver(monkeypatch):
    import modstore_server.services.llm as llm_service
    from modstore_server.employee_executor import _cognition_real

    captured = {}
    monkeypatch.setattr(
        llm_service,
        "resolve_platform_bench_llm",
        lambda: ("minimax", "MiniMax-M2.7"),
    )

    async def fake_platform(provider, model, messages, *, max_tokens=None):
        captured.update(provider=provider, model=model, messages=messages, max_tokens=max_tokens)
        return {"ok": True, "content": "自动驾驶路由已生效", "raw": {}}

    monkeypatch.setattr(llm_service, "chat_dispatch_via_platform_only", fake_platform)

    result = asyncio.run(
        _cognition_real(
            _hardcoded_config(),
            {"normalized_input": {"task": "执行后台巡检"}},
            {},
            MagicMock(),
            0,
            employee_id="legacy-hardcoded-employee",
            task="执行后台巡检",
        )
    )

    assert result["provider"] == "minimax"
    assert result["model"] == "MiniMax-M2.7"
    assert result["_bench_platform_only"] is True
    assert captured["provider"] == "minimax"


def test_user_employee_keeps_explicit_byok_model(monkeypatch):
    import modstore_server.employee_executor as executor

    captured = {}

    async def fake_session(session, user_id, provider, model, messages, *, max_tokens=None):
        captured.update(user_id=user_id, provider=provider, model=model)
        return {"ok": True, "content": "BYOK 路由", "raw": {}}

    monkeypatch.setattr(executor, "chat_dispatch_via_session", fake_session)

    result = asyncio.run(
        executor._cognition_real(
            _hardcoded_config(),
            {"normalized_input": {"task": "用户任务"}},
            {},
            MagicMock(),
            42,
            employee_id="user-installed-employee",
            task="用户任务",
        )
    )

    assert result["provider"] == "deepseek"
    assert result["model"] == "deepseek-chat"
    assert result["_bench_platform_only"] is False
    assert captured == {"user_id": 42, "provider": "deepseek", "model": "deepseek-chat"}
