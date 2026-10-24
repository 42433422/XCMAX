# mypy: disable-error-code="no-any-return"
"""Agent routing, async boundaries and handler delegation regressions."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.employee_runtime.agent_runner import (
    _chat_completion,
    _run_async,
    run_agent_handler,
)

AGENT_LOOP_PATH = "app.application.employee_runtime.agent_loop.run_employee_agent_loop"


class TestRunAsync:
    def test_no_running_loop_uses_asyncio_run(self):
        async def coro() -> int:
            return 42

        assert _run_async(coro()) == 42

    def test_running_loop_uses_thread_pool(self):
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


class TestChatCompletion:
    @pytest.mark.parametrize("completion", [{"choices": [{"message": {"content": "hello"}}]}, None])
    async def test_uses_common_provider(self, monkeypatch, completion):
        from app.infrastructure.llm.providers import registry

        provider = MagicMock()
        provider.chat_completion = AsyncMock(return_value=completion)
        monkeypatch.setattr(registry, "get_active_provider", lambda: provider)
        result = await _chat_completion([{"role": "user", "content": "hi"}], max_tokens=500)
        provider.chat_completion.assert_awaited_once_with(
            [{"role": "user", "content": "hi"}], max_tokens=500
        )
        assert (
            result == completion
            if completion
            else result["error_code"] == "employee_llm_not_configured"
        )

    async def test_unavailable_provider_is_not_replaced_with_another_users_credentials(
        self, monkeypatch
    ):
        from app.infrastructure.llm.providers import registry

        monkeypatch.setattr(registry, "get_active_provider", lambda: None)
        assert (await _chat_completion([]))["error_code"] == "employee_llm_not_configured"

    async def test_provider_error_does_not_expose_credentials(self, monkeypatch):
        from app.infrastructure.llm.providers import registry

        provider = MagicMock()
        provider.chat_completion = AsyncMock(side_effect=RuntimeError("private provider detail"))
        monkeypatch.setattr(registry, "get_active_provider", lambda: provider)
        result = await _chat_completion([])
        assert "private provider detail" not in result["error"]


class TestRunAgentHandler:
    def test_basic_delegation_with_full_reasoning(self):
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
