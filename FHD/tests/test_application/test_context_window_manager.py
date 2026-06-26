"""测试 :mod:`app.application.agent_orchestrator.context_window_manager` 的单元测试。

覆盖场景（遵循 ``.trae/rules/test-coverage-90-prompt.md`` 铁律 3）：

- happy path：noop / summarize / truncate 三策略
- 空值 / None：``None`` messages、空列表
- 边界值：恰好等于阈值、恰好等于 recent_keep
- 异常路径：摘要 LLM 失败、无 provider、空 result、无 choices、空 content
- 并发：多用户并发无竞态
- 记账：摘要调用独立 LLMCall、noop 不产生 LLMCall、metadata 正确
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwm_ledger(tmp_path, monkeypatch):
    """隔离账本 + 重置 CWM 单例，避免污染其他测试。"""
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "model_usage_ledger.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    from app.application.agent_orchestrator.context_window_manager import (
        reset_context_window_manager,
    )

    reset_context_window_manager()
    yield
    reset_context_window_manager()


def _make_provider(
    *,
    summary_text: str = "这是对话摘要",
    provider_id: str = "openai_compatible",
    model: str = "xcauto-summarizer",
) -> MagicMock:
    """构造 mock LLM provider，``chat_completion`` 返回摘要结果。"""
    mock = MagicMock()
    mock.provider_id = provider_id
    mock._adapter = SimpleNamespace(provider_name="xcauto", model_name=model)
    mock.model_name = model
    mock.chat_completion = AsyncMock(
        return_value={
            "choices": [{"message": {"content": summary_text}}],
            "model": model,
            "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
        }
    )
    return mock


def _make_messages(count: int, *, system: bool = False) -> list[dict[str, str]]:
    """构造 N 条消息（每条足够长，确保摘要后 token 减少）。"""
    msgs: list[dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": "你是助手"})
    for i in range(count):
        # 每条 ~20 中文字 ≈ 30 token，确保 6 条总 token 远超摘要
        msgs.append(
            {
                "role": "user",
                "content": f"这是第 {i} 条测试消息，包含足够长的内容用于触发上下文压缩和摘要功能验证。",
            }
        )
    return msgs


class TestCompressNoop:
    """``compress`` noop 策略测试。"""

    @pytest.mark.asyncio
    async def test_compress_none_messages_returns_empty(self) -> None:
        """None 输入返回 noop 空结果。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager()
        r = await m.compress(None, user_id="u1")
        assert r.strategy == "noop"
        assert r.messages == []
        assert r.pre_message_count == 0
        assert r.post_message_count == 0
        assert r.tokens_saved == 0
        assert r.summary_llm_call is None

    @pytest.mark.asyncio
    async def test_compress_empty_messages_returns_empty(self) -> None:
        """空列表返回 noop 空结果。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager()
        r = await m.compress([], user_id="u1")
        assert r.strategy == "noop"
        assert r.messages == []

    @pytest.mark.asyncio
    async def test_compress_under_threshold_returns_unchanged(self) -> None:
        """消息数 ≤ 阈值且 token ≤ 预算 → noop 原样返回。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=8000, recent_keep=6, summarize_threshold=12)
        msgs = _make_messages(5)
        r = await m.compress(msgs, user_id="u1")
        assert r.strategy == "noop"
        assert r.pre_message_count == 5
        assert r.post_message_count == 5
        assert r.tokens_saved == 0
        assert r.summary_llm_call is None
        assert r.messages == msgs

    @pytest.mark.asyncio
    async def test_compress_at_threshold_boundary_no_compression(self) -> None:
        """恰好等于阈值 → 不压缩（边界值不触发）。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=8000, recent_keep=6, summarize_threshold=12)
        msgs = _make_messages(12)
        r = await m.compress(msgs, user_id="u1")
        assert r.strategy == "noop"
        assert r.pre_message_count == 12

    @pytest.mark.asyncio
    async def test_compress_disabled_returns_noop(self) -> None:
        """``enabled=False`` 时即使超阈值也返回 noop。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(
            token_budget=100, recent_keep=2, summarize_threshold=3, enabled=False
        )
        msgs = _make_messages(20)
        r = await m.compress(msgs, user_id="u1")
        assert r.strategy == "noop"
        assert r.pre_message_count == 20
        assert r.post_message_count == 20
        assert r.tokens_saved == 0


class TestCompressSummarize:
    """``compress`` summarize 策略测试。"""

    @pytest.mark.asyncio
    async def test_compress_over_threshold_triggers_summarize(self) -> None:
        """超阈值 → 触发摘要。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=8000, recent_keep=2, summarize_threshold=3)
        provider = _make_provider()
        msgs = _make_messages(6)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.strategy == "summarize"
        assert r.pre_message_count == 6
        # system? + summary + 2 recent = 3 (no system in input) or 4 (with system)
        assert r.post_message_count == 3  # 1 summary + 2 recent
        assert r.tokens_saved > 0
        assert r.summary_llm_call is not None
        assert r.summary_llm_call.status == "completed"

    @pytest.mark.asyncio
    async def test_compress_over_token_budget_triggers_summarize(self) -> None:
        """token 超预算 → 触发摘要（即使消息数 ≤ 阈值）。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=100)
        provider = _make_provider()
        # 5 条消息，每条 ~3 token，总 ~15 token > budget 10
        msgs = _make_messages(5)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.strategy == "summarize"
        assert r.tokens_saved > 0

    @pytest.mark.asyncio
    async def test_compress_preserves_system_prompt(self) -> None:
        """system 消息永不裁剪。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = _make_provider()
        msgs = [
            {"role": "system", "content": "你是助手"},
            {"role": "system", "content": "额外系统指令"},
            *_make_messages(6),
        ]
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", provider=provider)
        # 2 system + 1 summary + 2 recent = 5
        assert r.post_message_count == 5
        system_msgs = [m for m in r.messages if m["role"] == "system"]
        assert len(system_msgs) == 3  # 2 original + 1 summary
        contents = [m["content"] for m in system_msgs]
        assert "你是助手" in contents
        assert "额外系统指令" in contents

    @pytest.mark.asyncio
    async def test_compress_preserves_recent_messages(self) -> None:
        """recent_keep 条最近消息永不裁剪。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=3, summarize_threshold=5)
        provider = _make_provider()
        msgs = _make_messages(10)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", provider=provider)
        # 最后 3 条应在结果中
        result_contents = [m["content"] for m in r.messages]
        assert any("第 9 条" in c for c in result_contents)
        assert any("第 8 条" in c for c in result_contents)
        assert any("第 7 条" in c for c in result_contents)

    @pytest.mark.asyncio
    async def test_compress_records_summary_as_separate_llm_call(self) -> None:
        """摘要调用被记为独立 LLMCall。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = _make_provider(model="xcauto-summarizer")
        msgs = _make_messages(6)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.summary_llm_call is not None
        call = r.summary_llm_call
        assert call.status == "completed"
        assert call.model == "xcauto-summarizer"
        assert call.provider_id == "openai_compatible"
        assert call.provider == "xcauto"
        assert call.prompt_tokens == 50
        assert call.completion_tokens == 20
        assert call.total_tokens == 70
        assert call.latency_ms > 0

    @pytest.mark.asyncio
    async def test_compress_noop_produces_no_llm_call(self) -> None:
        """未触发压缩时不产生 LLMCall。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=8000, recent_keep=6, summarize_threshold=12)
        msgs = _make_messages(3)
        r = await m.compress(msgs, user_id="u1")
        assert r.strategy == "noop"
        assert r.summary_llm_call is None

    @pytest.mark.asyncio
    async def test_compress_summary_llm_call_has_correct_metadata(self) -> None:
        """summary_llm_call.metadata.source 正确。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = _make_provider()
        msgs = _make_messages(6)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", trace_id="trace-abc", provider=provider)
        assert r.summary_llm_call is not None
        assert r.summary_llm_call.metadata["source"] == "context_window_manager.summarize"
        assert r.summary_llm_call.metadata["trace_id"] == "trace-abc"
        assert r.summary_llm_call.metadata["user_id"] == "u1"
        assert r.summary_llm_call.metadata["input_message_count"] == 4  # 6 - 2 recent

    @pytest.mark.asyncio
    async def test_compress_propagates_trace_id(self) -> None:
        """trace_id 正确传递到 LLMCall.metadata。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = _make_provider()
        msgs = _make_messages(6)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            r = await m.compress(msgs, user_id="u1", trace_id="trace-xyz-123", provider=provider)
        assert r.summary_llm_call is not None
        assert r.summary_llm_call.metadata["trace_id"] == "trace-xyz-123"

    @pytest.mark.asyncio
    async def test_compress_records_usage_to_ledger(self) -> None:
        """摘要调用记账到 model_usage_ledger。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )
        from app.infrastructure.billing.model_usage import model_usage_ledger_path

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = _make_provider()
        msgs = _make_messages(6)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=provider,
        ):
            await m.compress(msgs, user_id="u1", provider=provider)

        ledger_path = model_usage_ledger_path()
        assert ledger_path.exists()
        import json

        data = json.loads(ledger_path.read_text())
        entries = data.get("entries", []) if isinstance(data, dict) else data
        summary_entries = [
            e for e in entries if e.get("source") == "context_window_manager.summarize"
        ]
        assert len(summary_entries) >= 1
        entry = summary_entries[0]
        assert entry["model"] == "xcauto-summarizer"
        assert entry["total_tokens"] == 70


class TestCompressTruncateFallback:
    """``compress`` 摘要失败退化为 truncate 测试。"""

    @pytest.mark.asyncio
    async def test_compress_summarize_failure_falls_back_to_truncate(self) -> None:
        """摘要 LLM 失败 → 退化为 truncate。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = MagicMock()
        provider.provider_id = "openai_compatible"
        provider._adapter = SimpleNamespace(provider_name="xcauto", model_name="xcauto")
        provider.chat_completion = AsyncMock(side_effect=RuntimeError("LLM 超时"))
        msgs = _make_messages(6)
        r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.strategy == "truncate"
        assert r.pre_message_count == 6
        # 2 recent only (no summary)
        assert r.post_message_count == 2
        assert r.tokens_saved > 0
        assert r.summary_llm_call is not None
        assert r.summary_llm_call.status == "failed"
        assert "RuntimeError" in r.summary_llm_call.error

    @pytest.mark.asyncio
    async def test_compress_no_provider_falls_back_to_truncate(self) -> None:
        """无可用 provider → 退化为 truncate。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        msgs = _make_messages(6)
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=None,
        ):
            r = await m.compress(msgs, user_id="u1")
        assert r.strategy == "truncate"
        assert r.summary_llm_call is not None
        assert r.summary_llm_call.status == "failed"
        assert r.summary_llm_call.error == "no_active_provider"

    @pytest.mark.asyncio
    async def test_compress_empty_result_falls_back_to_truncate(self) -> None:
        """provider 返回空 result → 退化为 truncate。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = MagicMock()
        provider.provider_id = "openai_compatible"
        provider._adapter = SimpleNamespace(provider_name="xcauto", model_name="xcauto")
        provider.chat_completion = AsyncMock(return_value=None)
        msgs = _make_messages(6)
        r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.strategy == "truncate"
        assert r.summary_llm_call.status == "failed"
        assert r.summary_llm_call.error == "empty_result"

    @pytest.mark.asyncio
    async def test_compress_no_choices_falls_back_to_truncate(self) -> None:
        """provider 返回无 choices → 退化为 truncate。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = MagicMock()
        provider.provider_id = "openai_compatible"
        provider._adapter = SimpleNamespace(provider_name="xcauto", model_name="xcauto")
        provider.chat_completion = AsyncMock(return_value={"choices": []})
        msgs = _make_messages(6)
        r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.strategy == "truncate"
        assert r.summary_llm_call.status == "failed"
        assert r.summary_llm_call.error == "no_choices"

    @pytest.mark.asyncio
    async def test_compress_empty_content_falls_back_to_truncate(self) -> None:
        """provider 返回空 content → 退化为 truncate。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = MagicMock()
        provider.provider_id = "openai_compatible"
        provider._adapter = SimpleNamespace(provider_name="xcauto", model_name="xcauto")
        provider.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": ""}}]}
        )
        msgs = _make_messages(6)
        r = await m.compress(msgs, user_id="u1", provider=provider)
        assert r.strategy == "truncate"
        assert r.summary_llm_call.status == "failed"
        assert r.summary_llm_call.error == "empty_content"


class TestCompressConcurrency:
    """并发测试。"""

    @pytest.mark.asyncio
    async def test_compress_concurrent_users_no_race(self) -> None:
        """多用户并发无竞态。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        provider = _make_provider()

        async def run_one(user_id: str) -> str:
            msgs = _make_messages(6)
            with patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=provider,
            ):
                r = await m.compress(msgs, user_id=user_id, provider=provider)
            return r.strategy

        tasks = [run_one(f"u{i}") for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            assert not isinstance(r, Exception), f"concurrent compress failed: {r}"
            assert r in {"summarize", "truncate"}


class TestSingleton:
    """单例 + 环境变量配置测试。"""

    def test_get_context_window_manager_returns_singleton(self) -> None:
        """get_context_window_manager 返回同一实例。"""
        from app.application.agent_orchestrator.context_window_manager import (
            get_context_window_manager,
            reset_context_window_manager,
        )

        reset_context_window_manager()
        m1 = get_context_window_manager()
        m2 = get_context_window_manager()
        assert m1 is m2

    def test_reset_context_window_manager_clears_singleton(self) -> None:
        """reset 后获取新实例。"""
        from app.application.agent_orchestrator.context_window_manager import (
            get_context_window_manager,
            reset_context_window_manager,
        )

        m1 = get_context_window_manager()
        reset_context_window_manager()
        m2 = get_context_window_manager()
        assert m1 is not m2

    def test_singleton_reads_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """单例从环境变量读取配置。"""
        from app.application.agent_orchestrator.context_window_manager import (
            get_context_window_manager,
            reset_context_window_manager,
        )

        monkeypatch.setenv("FHD_CONTEXT_WINDOW_TOKEN_BUDGET", "12345")
        monkeypatch.setenv("FHD_CONTEXT_WINDOW_RECENT_KEEP", "8")
        monkeypatch.setenv("FHD_CONTEXT_WINDOW_SUMMARIZE_THRESHOLD", "20")
        reset_context_window_manager()
        m = get_context_window_manager()
        assert m.token_budget == 12345

    def test_singleton_disabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``FHD_CONTEXT_WINDOW_MANAGER_ENABLED=0`` 禁用。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        monkeypatch.setenv("FHD_CONTEXT_WINDOW_MANAGER_ENABLED", "0")
        m = ContextWindowManager()
        assert m.enabled is False

    @pytest.mark.asyncio
    async def test_disabled_manager_compress_returns_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """禁用的 manager 即使超阈值也返回 noop。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextWindowManager,
        )

        monkeypatch.setenv("FHD_CONTEXT_WINDOW_MANAGER_ENABLED", "0")
        m = ContextWindowManager(token_budget=10, recent_keep=2, summarize_threshold=3)
        msgs = _make_messages(20)
        r = await m.compress(msgs, user_id="u1")
        assert r.strategy == "noop"
        assert r.post_message_count == 20


class TestContextCompressionResult:
    """``ContextCompressionResult`` dataclass 测试。"""

    def test_default_values(self) -> None:
        """默认值正确。"""
        from app.application.agent_orchestrator.context_window_manager import (
            ContextCompressionResult,
        )

        r = ContextCompressionResult()
        assert r.messages == []
        assert r.strategy == "noop"
        assert r.pre_message_count == 0
        assert r.post_message_count == 0
        assert r.pre_estimated_tokens == 0
        assert r.post_estimated_tokens == 0
        assert r.tokens_saved == 0
        assert r.summary_llm_call is None
        assert r.compression_latency_ms == 0.0
