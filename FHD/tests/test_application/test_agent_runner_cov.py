# mypy: disable-error-code="no-any-return"
"""覆盖率补强测试：app.application.employee_runtime.agent_runner。

聚焦于 _run_async / _resolve_employee_llm_config / _chat_completion /
run_agent_handler 四个函数的边界与异常分支。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.employee_runtime.agent_runner import (
    _chat_completion,
    _resolve_employee_llm_config,
    _run_async,
    run_agent_handler,
)

CREDS_PATH = "app.infrastructure.llm.providers.credentials"
ADAPTER_PATH = "app.services.conversation.llm_adapter.OpenAICompatibleAdapter"
AGENT_LOOP_PATH = "app.application.employee_runtime.agent_loop.run_employee_agent_loop"


class TestRunAsync:
    """_run_async：在同步上下文中调度协程。"""

    def test_no_running_loop_uses_asyncio_run(self):
        async def coro() -> int:
            return 42

        assert _run_async(coro()) == 42

    def test_running_loop_uses_thread_pool(self):
        """已在事件循环内时，通过 ThreadPoolExecutor 在新线程里跑 asyncio.run。"""

        async def inner() -> str:
            return "from-thread"

        async def outer() -> str:
            return _run_async(inner())

        assert asyncio.run(outer()) == "from-thread"

    def test_propagates_exception_no_loop(self):
        async def coro() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            _run_async(coro())

    def test_propagates_exception_with_running_loop(self):
        async def inner() -> None:
            raise RuntimeError("inner-fail")

        async def outer() -> Any:
            return _run_async(inner())

        with pytest.raises(RuntimeError, match="inner-fail"):
            asyncio.run(outer())


class TestResolveEmployeeLlmConfig:
    """_resolve_employee_llm_config：环境变量覆盖 vs 默认凭据解析。"""

    def test_provider_override_with_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "openai")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "gpt-4o")

        cfg = _resolve_employee_llm_config()

        assert cfg == {
            "provider": "openai",
            "model": "gpt-4o",
            "api_key": None,
            "base_url": None,
        }

    def test_provider_override_without_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "azure")
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_MODEL", raising=False)

        cfg = _resolve_employee_llm_config()

        assert cfg == {
            "provider": "azure",
            "model": None,
            "api_key": None,
            "base_url": None,
        }

    def test_provider_override_whitespace_falls_through(self, monkeypatch: pytest.MonkeyPatch):
        """空白字符串的 provider 视为未设置，走默认凭据路径。"""
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "   ")
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_MODEL", raising=False)

        with (
            patch(f"{CREDS_PATH}.resolve_openai_env_credentials") as mock_creds,
            patch(f"{CREDS_PATH}.resolve_default_openai_provider") as mock_provider,
            patch(f"{CREDS_PATH}.resolve_default_chat_model") as mock_model,
        ):
            mock_creds.return_value = ("api-key-123", "https://api.example.com")
            mock_provider.return_value = "openai"
            mock_model.return_value = "gpt-4-turbo"

            cfg = _resolve_employee_llm_config()

        assert cfg == {
            "provider": "openai",
            "model": "gpt-4-turbo",
            "api_key": "api-key-123",
            "base_url": "https://api.example.com",
        }

    def test_default_path_with_credentials(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_MODEL", raising=False)

        with (
            patch(f"{CREDS_PATH}.resolve_openai_env_credentials") as mock_creds,
            patch(f"{CREDS_PATH}.resolve_default_openai_provider") as mock_provider,
            patch(f"{CREDS_PATH}.resolve_default_chat_model") as mock_model,
        ):
            mock_creds.return_value = ("api-key-123", "https://api.example.com")
            mock_provider.return_value = "openai"
            mock_model.return_value = "gpt-4-turbo"

            cfg = _resolve_employee_llm_config()

        assert cfg == {
            "provider": "openai",
            "model": "gpt-4-turbo",
            "api_key": "api-key-123",
            "base_url": "https://api.example.com",
        }

    def test_default_path_with_model_override(self, monkeypatch: pytest.MonkeyPatch):
        """默认 provider 路径下，FHD_EMPLOYEE_LLM_MODEL 仍可覆盖默认模型。"""
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_PROVIDER", raising=False)
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "custom-model")

        with (
            patch(f"{CREDS_PATH}.resolve_openai_env_credentials") as mock_creds,
            patch(f"{CREDS_PATH}.resolve_default_openai_provider") as mock_provider,
            patch(f"{CREDS_PATH}.resolve_default_chat_model") as mock_model,
        ):
            mock_creds.return_value = ("", None)
            mock_provider.return_value = "xcauto"
            mock_model.return_value = "default-model"

            cfg = _resolve_employee_llm_config()

        assert cfg == {
            "provider": "xcauto",
            "model": "custom-model",
            "api_key": None,
            "base_url": None,
        }


class TestChatCompletion:
    """_chat_completion：单轮补全的配置/错误路径。"""

    async def test_adapter_not_configured_returns_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "openai")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "gpt-4o")

        adapter = MagicMock()
        adapter.is_configured = False
        adapter.model_name = "gpt-4o"

        with patch(ADAPTER_PATH, return_value=adapter) as mock_cls:
            result = await _chat_completion([{"role": "user", "content": "hi"}])

        assert "error" in result
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4o"
        mock_cls.assert_called_once()

    async def test_adapter_configured_returns_completion(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "openai")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "gpt-4o")

        adapter = MagicMock()
        adapter.is_configured = True
        adapter.chat_completion = AsyncMock(return_value={"content": "hello back"})

        with patch(ADAPTER_PATH, return_value=adapter) as mock_cls:
            result = await _chat_completion([{"role": "user", "content": "hi"}], max_tokens=500)

        assert result == {"content": "hello back"}
        adapter.chat_completion.assert_awaited_once()
        # 验证 max_tokens 透传
        _, kwargs = adapter.chat_completion.call_args
        assert kwargs.get("max_tokens") == 500
        # 验证 provider/model 透传给 adapter 构造器
        _, ctor_kwargs = mock_cls.call_args
        assert ctor_kwargs.get("provider") == "openai"
        assert ctor_kwargs.get("model") == "gpt-4o"

    async def test_empty_provider_defaults_to_xcauto(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_PROVIDER", raising=False)
        monkeypatch.delenv("FHD_EMPLOYEE_LLM_MODEL", raising=False)

        adapter = MagicMock()
        adapter.is_configured = False
        adapter.model_name = "default-model"

        with (
            patch(f"{CREDS_PATH}.resolve_openai_env_credentials", return_value=("", None)),
            patch(f"{CREDS_PATH}.resolve_default_openai_provider", return_value=""),
            patch(f"{CREDS_PATH}.resolve_default_chat_model", return_value="default-model"),
            patch(ADAPTER_PATH, return_value=adapter) as mock_cls,
        ):
            result = await _chat_completion([{"role": "user", "content": "hi"}])

        # provider 空字符串 → 默认 "xcauto"
        _, ctor_kwargs = mock_cls.call_args
        assert ctor_kwargs.get("provider") == "xcauto"
        assert "error" in result
        assert result["provider"] == "xcauto"

    async def test_recoverable_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "openai")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "gpt-4o")

        adapter = MagicMock()
        adapter.is_configured = True
        adapter.chat_completion = AsyncMock(side_effect=ConnectionError("net down"))

        with patch(ADAPTER_PATH, return_value=adapter):
            result = await _chat_completion([{"role": "user", "content": "hi"}])

        assert "error" in result
        assert "net down" in result["error"]

    async def test_primary_429_falls_back_to_minimax(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "xiaomi")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "mimo-v2.5-pro")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_FALLBACK_PROVIDER", "minimax")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_FALLBACK_MODEL", "MiniMax-M2.7")

        primary = MagicMock(is_configured=True, model_name="mimo-v2.5-pro")
        primary.chat_completion = AsyncMock(side_effect=ConnectionError("429 quota exhausted"))
        fallback = MagicMock(is_configured=True, model_name="MiniMax-M2.7")
        fallback.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": "fallback ok"}}]}
        )

        with patch(ADAPTER_PATH, side_effect=[primary, fallback]) as mock_cls:
            result = await _chat_completion([{"role": "user", "content": "hi"}])

        assert result["choices"][0]["message"]["content"] == "fallback ok"
        assert result["_fallback_used"] is True
        assert result["_primary_provider"] == "xiaomi"
        assert result["_fallback_provider"] == "minimax"
        assert mock_cls.call_count == 2

    async def test_recoverable_value_error_truncated(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_PROVIDER", "openai")
        monkeypatch.setenv("FHD_EMPLOYEE_LLM_MODEL", "gpt-4o")

        long_msg = "x" * 2000
        adapter = MagicMock()
        adapter.is_configured = True
        adapter.chat_completion = AsyncMock(side_effect=ValueError(long_msg))

        with patch(ADAPTER_PATH, return_value=adapter):
            result = await _chat_completion([{"role": "user", "content": "hi"}])

        # str(exc)[:800] 截断
        assert len(result["error"]) <= 800
        assert result["error"] == long_msg[:800]


class TestRunAgentHandler:
    """run_agent_handler：参数解析与委托调用。"""

    def test_basic_delegation_with_full_reasoning(self):
        """reasoning 携带 system_prompt / input / reasoning 时全部解析并透传。"""
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"handler": "agent", "ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop) as mock_loop:
            result = run_agent_handler(
                actions_cfg={"max_iterations": 5, "wall_time_limit_sec": 120.0, "repeat_limit": 4},
                reasoning={
                    "system_prompt": "你是测试助手。",
                    "input": {"foo": "bar"},
                    "reasoning": "prior thought",
                },
                task="do something",
                employee_id="emp-1",
                workspace_root="/tmp/ws",
                tools=[{"name": "tool1"}],
                gate=lambda content, ctx: {"ok": True},
            )

        assert result == {"handler": "agent", "ok": True}
        mock_loop.assert_called_once()
        assert captured["employee_id"] == "emp-1"
        assert captured["system_prompt"] == "你是测试助手。"
        assert captured["task"] == "do something"
        assert captured["input_data"] == {"foo": "bar", "_prior_reasoning": "prior thought"}
        assert captured["tools"] == [{"name": "tool1"}]
        assert captured["workspace_root"] == "/tmp/ws"
        assert captured["gate"] is not None
        assert captured["max_iterations"] == 5
        assert captured["wall_time_limit_sec"] == 120.0
        assert captured["repeat_limit"] == 4

    def test_reasoning_not_dict_uses_defaults(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            result = run_agent_handler(
                actions_cfg={},
                reasoning=None,  # type: ignore[arg-type]
                task="t",
                employee_id="emp-1",
            )

        assert result == {"ok": True}
        assert captured["system_prompt"] == "你是智能员工助手。"
        assert captured["input_data"] == {}
        assert "_prior_reasoning" not in captured["input_data"]

    def test_empty_system_prompt_uses_default(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={},
                reasoning={"system_prompt": "", "input": None, "reasoning": ""},
                task="t",
                employee_id="emp-1",
            )

        assert captured["system_prompt"] == "你是智能员工助手。"
        assert captured["input_data"] == {}

    def test_prior_reasoning_truncated_to_2000(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        long_prior = "p" * 3000
        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={},
                reasoning={"reasoning": long_prior},
                task="t",
                employee_id="emp-1",
            )

        assert captured["input_data"]["_prior_reasoning"] == long_prior[:2000]

    def test_prior_reasoning_whitespace_only_skipped(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={},
                reasoning={"reasoning": "   "},
                task="t",
                employee_id="emp-1",
            )

        assert "_prior_reasoning" not in captured["input_data"]

    def test_explicit_max_iterations_overrides_actions_cfg(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"max_iterations": 99},
                reasoning={},
                task="t",
                employee_id="emp-1",
                max_iterations=7,
            )

        assert captured["max_iterations"] == 7

    def test_max_iterations_from_actions_cfg(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"max_iterations": 12},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        assert captured["max_iterations"] == 12

    def test_max_iterations_invalid_falls_back_to_default_6(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"max_iterations": "not-a-number"},  # type: ignore[dict-item]
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        # max_iters 解析失败 → None → max_iters or 6 → 6
        assert captured["max_iterations"] == 6

    def test_max_iterations_zero_falls_back_to_default_6(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"max_iterations": 0},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        assert captured["max_iterations"] == 6

    def test_wall_time_limit_sec_invalid_falls_back_to_300(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"wall_time_limit_sec": "bad"},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        assert captured["wall_time_limit_sec"] == 300.0

    def test_wall_time_limit_sec_below_one_bumped_to_one(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"wall_time_limit_sec": 0.5},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        # max(1.0, 0.5) → 1.0
        assert captured["wall_time_limit_sec"] == 1.0

    def test_repeat_limit_invalid_falls_back_to_3(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"repeat_limit": "bad"},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        # max(2, 3) → 3
        assert captured["repeat_limit"] == 3

    def test_repeat_limit_below_two_bumped_to_two(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={"repeat_limit": 1},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        # max(2, 1) → 2
        assert captured["repeat_limit"] == 2

    def test_actions_cfg_none_uses_all_defaults(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg=None,  # type: ignore[arg-type]
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        # actions_cfg None → 全部默认值
        assert captured["max_iterations"] == 6
        assert captured["wall_time_limit_sec"] == 300.0
        assert captured["repeat_limit"] == 3

    def test_tools_and_gate_default_none_propagated(self):
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={},
                reasoning={},
                task="t",
                employee_id="emp-1",
            )

        assert captured["tools"] is None
        assert captured["gate"] is None
        assert captured["workspace_root"] is None

    def test_input_data_setdefault_does_not_overwrite_existing_prior(self):
        """input_data 已含 _prior_reasoning 时，setdefault 不覆盖。"""
        captured: dict[str, Any] = {}

        def fake_loop(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {"ok": True}

        with patch(AGENT_LOOP_PATH, side_effect=fake_loop):
            run_agent_handler(
                actions_cfg={},
                reasoning={
                    "input": {"_prior_reasoning": "existing", "other": 1},
                    "reasoning": "new-prior",
                },
                task="t",
                employee_id="emp-1",
            )

        # setdefault 不覆盖已有值
        assert captured["input_data"]["_prior_reasoning"] == "existing"
        assert captured["input_data"]["other"] == 1
