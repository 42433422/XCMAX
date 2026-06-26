"""认知层（Cognition Layer）Phase 2 组件测试。

覆盖：
- ``LLMPort``：LLM 端口适配器（provider 选型、失败降级）
- ``WorkingMemory``：工作记忆（短期召回、长期可选、best-effort）
- ``AttentionSelector``：注意力选择器（相关性评分、token 预算、位置衰减）
- ``ConsciousLLMHandler``：Conscious LLM 处理器（端到端流程、降级路径）
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.neuro.cognition.attention_selector import (
    AttentionResult,
    AttentionSelector,
    _jaccard,
    _tokenize,
)
from app.domain.neuro.cognition.conscious_llm_handler import ConsciousLLMHandler
from app.domain.neuro.cognition.llm_port import LLMPort, get_llm_port, reset_llm_port
from app.domain.neuro.cognition.working_memory import (
    MemoryItem,
    WorkingMemory,
    WorkingMemorySnapshot,
    get_working_memory,
    reset_working_memory,
)
from app.infrastructure.llm.token_estimator import estimate_tokens

# ============================================================================
# LLMPort 测试
# ============================================================================


class TestLLMPort:
    """LLM 端口适配器测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_llm_port()
        yield
        reset_llm_port()

    async def test_chat_returns_none_when_no_provider(self):
        """无可用 provider 时返回 None。"""
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=None,
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result is None

    async def test_chat_returns_content_on_success(self):
        """LLM 调用成功时返回 content 字符串。"""
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": "Hello from LLM"}}]}
        )
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=mock_provider,
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello from LLM"

    async def test_chat_returns_none_on_empty_choices(self):
        """LLM 返回空 choices 时返回 None。"""
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.chat_completion = AsyncMock(return_value={"choices": []})
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=mock_provider,
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result is None

    async def test_chat_returns_none_on_empty_content(self):
        """LLM 返回空 content 时返回 None。"""
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": ""}}]}
        )
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=mock_provider,
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result is None

    async def test_chat_swallows_exceptions(self):
        """LLM 调用异常时不抛出，返回 None。"""
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.chat_completion = AsyncMock(side_effect=RuntimeError("boom"))
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=mock_provider,
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result is None

    async def test_chat_with_explicit_provider(self):
        """指定 provider 时使用该 provider。"""
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        mock_provider.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": "ok"}}]}
        )
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_provider

        port = LLMPort(default_provider="openai_compatible")
        with patch(
            "app.infrastructure.llm.providers.registry.get_llm_registry",
            return_value=mock_registry,
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result == "ok"
        mock_registry.get.assert_called_once_with("openai_compatible")

    async def test_chat_falls_back_to_active_when_provider_not_configured(self):
        """指定 provider 未配置时回退到 active provider。"""
        mock_provider_default = MagicMock()
        mock_provider_default.is_configured = False

        mock_provider_active = MagicMock()
        mock_provider_active.is_configured = True
        mock_provider_active.chat_completion = AsyncMock(
            return_value={"choices": [{"message": {"content": "fallback"}}]}
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_provider_default

        port = LLMPort(default_provider="deepseek_legacy")
        with (
            patch(
                "app.infrastructure.llm.providers.registry.get_llm_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.infrastructure.llm.providers.registry.get_active_provider",
                return_value=mock_provider_active,
            ),
        ):
            result = await port.chat([{"role": "user", "content": "hi"}])
        assert result == "fallback"

    def test_is_available_true_when_provider_configured(self):
        """有 provider 配置时 is_available=True。"""
        mock_provider = MagicMock()
        mock_provider.is_configured = True
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=mock_provider,
        ):
            assert port.is_available is True

    def test_is_available_false_when_no_provider(self):
        """无 provider 时 is_available=False。"""
        port = LLMPort()
        with patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=None,
        ):
            assert port.is_available is False

    def test_singleton_returns_same_instance(self):
        """get_llm_port 返回同一单例。"""
        p1 = get_llm_port()
        p2 = get_llm_port()
        assert p1 is p2

    def test_reset_clears_singleton(self):
        """reset_llm_port 清除单例。"""
        p1 = get_llm_port()
        reset_llm_port()
        p2 = get_llm_port()
        assert p1 is not p2


# ============================================================================
# WorkingMemory 测试
# ============================================================================


class TestWorkingMemory:
    """工作记忆测试。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_working_memory()
        yield
        reset_working_memory()

    def test_recall_returns_empty_when_no_session(self):
        """无 session_id 时返回空快照。"""
        wm = WorkingMemory(session_id="", user_id="")
        snapshot = wm.recall("query")
        assert snapshot.is_empty
        assert snapshot.items == []

    def test_recall_short_term_returns_messages(self):
        """短期召回返回会话消息。"""
        mock_rows = [
            ("id1", "sess1", "2024-01-01", "user", "你好", "", ""),
            ("id2", "sess1", "2024-01-01", "assistant", "你好，有什么可以帮你？", "", ""),
            ("id3", "sess1", "2024-01-01", "user", "查询订单", "", ""),
        ]
        wm = WorkingMemory(session_id="sess1", user_id="")
        with patch(
            "app.services.conversation_service.ConversationService.get_session_messages",
            return_value=mock_rows,
        ):
            snapshot = wm.recall("查询")
        assert len(snapshot.items) == 3
        assert snapshot.items[0].role == "user"
        assert snapshot.items[0].content == "你好"
        assert snapshot.items[0].source == "session"

    def test_recall_short_term_skips_empty_content(self):
        """空内容的消息被跳过。"""
        mock_rows = [
            ("id1", "sess1", "2024-01-01", "user", "", "", ""),
            ("id2", "sess1", "2024-01-01", "assistant", "有内容", "", ""),
        ]
        wm = WorkingMemory(session_id="sess1")
        with patch(
            "app.services.conversation_service.ConversationService.get_session_messages",
            return_value=mock_rows,
        ):
            snapshot = wm.recall()
        assert len(snapshot.items) == 1
        assert snapshot.items[0].content == "有内容"

    def test_recall_short_term_limits_to_8(self):
        """短期召回最多返回 8 条。"""
        mock_rows = [
            (f"id{i}", "sess1", "2024-01-01", "user", f"msg{i}", "", "") for i in range(20)
        ]
        wm = WorkingMemory(session_id="sess1")
        with patch(
            "app.services.conversation_service.ConversationService.get_session_messages",
            return_value=mock_rows,
        ):
            snapshot = wm.recall()
        assert len(snapshot.items) == 8
        # 取最近 8 条
        assert snapshot.items[-1].content == "msg19"

    def test_recall_swallows_exceptions(self):
        """ConversationService 异常时返回空。"""
        wm = WorkingMemory(session_id="sess1")
        with patch(
            "app.services.conversation_service.ConversationService.get_session_messages",
            side_effect=RuntimeError("db down"),
        ):
            snapshot = wm.recall()
        assert snapshot.is_empty

    def test_recall_long_term_disabled_by_default(self):
        """默认不启用长期记忆。"""
        wm = WorkingMemory(session_id="sess1", user_id="u1")
        assert wm._enable_long_term is False

    def test_recall_long_term_returns_items(self):
        """启用长期记忆时返回向量召回结果。"""
        mock_result = {
            "hits": [
                {"content": "历史记忆1", "score": 0.9, "metadata": {"src": "doc"}},
                {"content": "历史记忆2", "score": 0.7, "metadata": {}},
            ]
        }
        mock_svc = MagicMock()
        mock_svc.query = MagicMock(return_value=mock_result)

        wm = WorkingMemory(session_id="sess1", user_id="u1", enable_long_term=True)
        with (
            patch(
                "app.services.conversation_service.ConversationService.get_session_messages",
                return_value=[],
            ),
            patch(
                "app.application.user_memory_vector_app_service.get_user_memory_rag_app_service",
                return_value=mock_svc,
            ),
        ):
            snapshot = wm.recall("查询")
        assert len(snapshot.items) == 2
        assert snapshot.items[0].source == "long_term"
        assert snapshot.items[0].score == 0.9
        assert snapshot.items[0].role == "system"

    def test_recall_long_term_skips_empty_content(self):
        """长期记忆中空内容被跳过。"""
        mock_result = {
            "hits": [
                {"content": "", "score": 0.9},
                {"content": "有内容", "score": 0.7},
            ]
        }
        mock_svc = MagicMock()
        mock_svc.query = MagicMock(return_value=mock_result)

        wm = WorkingMemory(session_id="sess1", user_id="u1", enable_long_term=True)
        with (
            patch(
                "app.services.conversation_service.ConversationService.get_session_messages",
                return_value=[],
            ),
            patch(
                "app.application.user_memory_vector_app_service.get_user_memory_rag_app_service",
                return_value=mock_svc,
            ),
        ):
            snapshot = wm.recall("查询")
        assert len(snapshot.items) == 1

    def test_remember_skips_when_no_session(self):
        """无 session_id 时 remember 不执行。"""
        wm = WorkingMemory(session_id="")
        wm.remember("user", "test")  # 不应抛异常

    def test_remember_calls_save_message(self):
        """remember 调用 ConversationService.save_message。"""
        wm = WorkingMemory(session_id="sess1", user_id="u1")
        with patch(
            "app.services.conversation_service.ConversationService.save_message"
        ) as mock_save:
            wm.remember("user", "hello", metadata={"k": "v"})
        # save_message(session_id, user_id, role, content, metadata=json_str)
        call_args = mock_save.call_args
        assert call_args.args[0] == "sess1"
        assert call_args.args[1] == "u1"
        assert call_args.args[2] == "user"
        assert call_args.args[3] == "hello"
        # metadata 被序列化为 JSON 字符串
        import json as _json

        assert _json.loads(call_args.kwargs["metadata"]) == {"k": "v"}

    def test_remember_swallows_exceptions(self):
        """remember 异常时不抛出。"""
        wm = WorkingMemory(session_id="sess1")
        with patch(
            "app.services.conversation_service.ConversationService.save_message",
            side_effect=RuntimeError("db down"),
        ):
            wm.remember("user", "hello")  # 不应抛异常

    def test_snapshot_as_messages(self):
        """snapshot.as_messages() 返回 OpenAI 格式。"""
        snapshot = WorkingMemorySnapshot(
            items=[
                MemoryItem(role="user", content="hi"),
                MemoryItem(role="assistant", content="hello"),
            ],
        )
        msgs = snapshot.as_messages()
        assert msgs == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_singleton_respects_session_id(self):
        """get_working_memory 按 session_id 初始化。"""
        wm1 = get_working_memory(session_id="s1", user_id="u1")
        wm2 = get_working_memory(session_id="s1", user_id="u1")
        assert wm1 is wm2

        reset_working_memory()
        wm3 = get_working_memory(session_id="s2", user_id="u1")
        assert wm3 is not wm1


# ============================================================================
# AttentionSelector 测试
# ============================================================================


class TestTokenize:
    """分词函数测试。"""

    def test_english_words(self):
        tokens = _tokenize("hello world foo")
        assert tokens == {"hello", "world", "foo"}

    def test_chinese_chars(self):
        tokens = _tokenize("你好世界")
        assert tokens == {"你", "好", "世", "界"}

    def test_mixed(self):
        tokens = _tokenize("hello 你好")
        assert "hello" in tokens
        assert "你" in tokens
        assert "好" in tokens

    def test_empty(self):
        assert _tokenize("") == set()

    def test_case_insensitive(self):
        tokens = _tokenize("Hello HELLO")
        assert tokens == {"hello"}


class TestJaccard:
    """Jaccard 系数测试。"""

    def test_identical_sets(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        # {a,b} ∩ {b,c} = {b}, {a,b} ∪ {b,c} = {a,b,c} → 1/3
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1.0 / 3.0)

    def test_empty_sets(self):
        assert _jaccard(set(), set()) == 0.0
        assert _jaccard({"a"}, set()) == 0.0


class TestEstimateTokens:
    """Token 估算测试。"""

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_chinese(self):
        # 4 个汉字 ≈ 6 token
        result = estimate_tokens("你好世界")
        assert result == 6

    def test_english(self):
        # 2 个英文词 ≈ 2 token (2 * 1.3 = 2.6 → 2)
        result = estimate_tokens("hello world")
        assert result == 2

    def test_mixed(self):
        # 2 汉字 + 1 英文词 = 3 + 1 = 4
        result = estimate_tokens("你好 hello")
        assert result == 4


class TestAttentionSelector:
    """注意力选择器测试。"""

    def test_select_returns_empty_when_no_candidates(self):
        """无候选时返回空结果。"""
        selector = AttentionSelector()
        snapshot = WorkingMemorySnapshot()
        result = selector.select("query", snapshot)
        assert result.is_empty
        assert result.total_candidates == 0

    def test_select_returns_all_when_few_candidates(self):
        """候选少于 max_items 时全部返回。"""
        selector = AttentionSelector(max_items=6)
        snapshot = WorkingMemorySnapshot(
            items=[
                MemoryItem(role="user", content="hello"),
                MemoryItem(role="assistant", content="hi there"),
            ],
        )
        result = selector.select("hello", snapshot)
        assert len(result.selected) == 2
        assert result.pruned == 0

    def test_select_respects_max_items(self):
        """超过 max_items 时只返回 max_items 条。"""
        items = [MemoryItem(role="user", content=f"msg{i}") for i in range(10)]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(max_items=3)
        result = selector.select("msg", snapshot)
        assert len(result.selected) == 3
        assert result.pruned == 7

    def test_select_respects_token_budget(self):
        """超过 token 预算时跳过。"""
        items = [
            MemoryItem(role="user", content="你好世界" * 100),  # 很长
            MemoryItem(role="user", content="短消息"),
        ]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(token_budget=10, max_items=6)
        result = selector.select("你好", snapshot)
        # 第一条太长（超过预算），第二条短可以选
        assert len(result.selected) <= 1

    def test_select_scores_by_relevance(self):
        """按相关性排序。"""
        items = [
            MemoryItem(role="user", content="完全不相关的内容"),
            MemoryItem(role="user", content="查询订单状态"),
            MemoryItem(role="user", content="你好世界"),
        ]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(max_items=2)
        result = selector.select("查询订单", snapshot)
        # "查询订单状态" 应该排第一（相关性最高）
        assert result.selected[0].content == "查询订单状态"

    def test_select_applies_recency_decay(self):
        """近期消息权重更高。"""
        items = [
            MemoryItem(role="user", content="查询"),  # 旧
            MemoryItem(role="user", content="查询"),  # 新
        ]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(max_items=1)
        result = selector.select("查询", snapshot)
        # 两条相关性相同，但新的（idx=1）recency 更高
        assert result.selected[0].content == "查询"
        # 选取的应该是 idx=1（新的一条）

    def test_select_preserves_temporal_order(self):
        """选取后按原始时序排列。"""
        items = [
            MemoryItem(role="user", content="第一条"),
            MemoryItem(role="user", content="第二条"),
            MemoryItem(role="user", content="第三条"),
        ]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(max_items=2)
        result = selector.select("", snapshot)
        # 选取后应按原始顺序
        contents = [it.content for it in result.selected]
        # 原始顺序是 [第一条, 第二条, 第三条]，选取 2 条后应保持顺序
        assert contents == sorted(contents, key=lambda c: ["第一条", "第二条", "第三条"].index(c))

    def test_select_long_term_uses_existing_score(self):
        """长期记忆条目复用已有 score。"""
        items = [
            MemoryItem(role="system", content="历史记忆", source="long_term", score=0.95),
            MemoryItem(role="user", content="会话消息", source="session"),
        ]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(max_items=2)
        result = selector.select("无关查询", snapshot)
        # 长期记忆有 score=0.95，即使查询不相关也应被选中
        assert any(it.source == "long_term" for it in result.selected)

    def test_select_empty_query(self):
        """空查询时仍可选取（靠 recency）。"""
        items = [MemoryItem(role="user", content=f"msg{i}") for i in range(3)]
        snapshot = WorkingMemorySnapshot(items=items)
        selector = AttentionSelector(max_items=2)
        result = selector.select("", snapshot)
        assert len(result.selected) == 2

    def test_attention_result_as_messages(self):
        """AttentionResult.as_messages() 返回 OpenAI 格式。"""
        result = AttentionResult(
            selected=[
                MemoryItem(role="user", content="hi"),
                MemoryItem(role="assistant", content="hello"),
            ],
        )
        msgs = result.as_messages()
        assert msgs == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

    def test_attention_result_is_empty(self):
        """空结果 is_empty=True。"""
        assert AttentionResult().is_empty
        assert not AttentionResult(selected=[MemoryItem(role="user", content="x")]).is_empty


# ============================================================================
# ConsciousLLMHandler 测试
# ============================================================================


class TestConsciousLLMHandler:
    """Conscious LLM 处理器测试。"""

    @pytest.fixture
    def mock_event(self):
        """构造 mock NeuroEvent。"""
        event = MagicMock()
        event.payload = {
            "text": "你好",
            "session_id": "sess1",
            "user_id": "u1",
        }
        return event

    @pytest.fixture
    def mock_llm_port(self):
        """构造 mock LLMPort。"""
        port = MagicMock(spec=LLMPort)
        port.chat = AsyncMock(return_value="LLM 回复")
        return port

    @pytest.fixture
    def mock_working_memory(self):
        """构造 mock WorkingMemory。"""
        wm = MagicMock(spec=WorkingMemory)
        wm.recall.return_value = WorkingMemorySnapshot()  # 空记忆
        wm.remember = MagicMock()
        return wm

    async def test_handle_returns_response_on_success(
        self, mock_event, mock_llm_port, mock_working_memory
    ):
        """LLM 调用成功时返回回复。"""
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
        )
        result = await handler.handle(mock_event)

        assert result["success"] is True
        assert result["response"] == "LLM 回复"
        assert result["error"] is None

    async def test_handle_returns_error_on_empty_query(self, mock_llm_port, mock_working_memory):
        """空查询时返回错误。"""
        event = MagicMock()
        event.payload = {"text": ""}
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
        )
        result = await handler.handle(event)

        assert result["success"] is False
        assert result["error"] == "empty_query"
        mock_llm_port.chat.assert_not_called()

    async def test_handle_returns_error_when_llm_unavailable(self, mock_event, mock_working_memory):
        """LLM 不可用时返回错误。"""
        mock_port = MagicMock(spec=LLMPort)
        mock_port.chat = AsyncMock(return_value=None)
        handler = ConsciousLLMHandler(
            llm_port=mock_port,
            working_memory=mock_working_memory,
        )
        result = await handler.handle(mock_event)

        assert result["success"] is False
        assert result["error"] == "llm_unavailable"

    async def test_handle_calls_llm_with_messages(
        self, mock_event, mock_llm_port, mock_working_memory
    ):
        """handle 调用 LLM 时传入正确的消息结构。"""
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
        )
        await handler.handle(mock_event)

        mock_llm_port.chat.assert_called_once()
        call_args = mock_llm_port.chat.call_args
        messages = call_args[0][0]  # 第一个位置参数
        assert isinstance(messages, list)
        assert messages[0]["role"] == "system"  # system prompt
        assert messages[-1]["role"] == "user"  # 用户查询
        assert messages[-1]["content"] == "你好"

    async def test_handle_remembers_after_success(
        self, mock_event, mock_llm_port, mock_working_memory
    ):
        """成功后写入工作记忆。"""
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
        )
        await handler.handle(mock_event)

        # remember 被调用两次：user query + assistant response
        assert mock_working_memory.remember.call_count == 2

    async def test_handle_does_not_remember_on_failure(self, mock_event, mock_working_memory):
        """LLM 失败时不写入记忆。"""
        mock_port = MagicMock(spec=LLMPort)
        mock_port.chat = AsyncMock(return_value=None)
        handler = ConsciousLLMHandler(
            llm_port=mock_port,
            working_memory=mock_working_memory,
        )
        await handler.handle(mock_event)

        mock_working_memory.remember.assert_not_called()

    async def test_handle_injects_memory_context(self, mock_event, mock_llm_port):
        """有工作记忆时注入上下文。"""
        mock_wm = MagicMock(spec=WorkingMemory)
        mock_wm.recall.return_value = WorkingMemorySnapshot(
            items=[
                MemoryItem(role="user", content="之前的查询"),
                MemoryItem(role="assistant", content="之前的回复"),
            ],
        )
        mock_wm.remember = MagicMock()

        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_wm,
        )
        await handler.handle(mock_event)

        call_args = mock_llm_port.chat.call_args
        messages = call_args[0][0]
        # 应该有 system prompt + 上下文段落 + user query
        assert len(messages) >= 3
        # 第二条应该是上下文
        assert "相关上下文" in messages[1]["content"] or "上下文" in messages[1]["content"]

    async def test_handle_injects_extra_context(
        self, mock_event, mock_llm_port, mock_working_memory
    ):
        """有附加上下文时注入。"""
        mock_event.payload = {
            "text": "你好",
            "context": {"intent": "greeting", "mode": "pro"},
        }
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
        )
        await handler.handle(mock_event)

        call_args = mock_llm_port.chat.call_args
        messages = call_args[0][0]
        # 应该包含附加上下文段落
        context_msgs = [m for m in messages if "附加上下文" in m.get("content", "")]
        assert len(context_msgs) >= 1

    async def test_handle_uses_custom_system_prompt(
        self, mock_event, mock_llm_port, mock_working_memory
    ):
        """使用自定义系统提示词。"""
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
            system_prompt="自定义提示词",
        )
        await handler.handle(mock_event)

        call_args = mock_llm_port.chat.call_args
        messages = call_args[0][0]
        assert messages[0]["content"] == "自定义提示词"

    async def test_handle_uses_payload_system_prompt_override(
        self, mock_event, mock_llm_port, mock_working_memory
    ):
        """payload 中的 system_prompt 覆盖默认。"""
        mock_event.payload = {
            "text": "你好",
            "system_prompt": "payload覆盖提示词",
        }
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
            system_prompt="默认提示词",
        )
        await handler.handle(mock_event)

        call_args = mock_llm_port.chat.call_args
        messages = call_args[0][0]
        assert messages[0]["content"] == "payload覆盖提示词"

    async def test_handle_query_from_query_field(self, mock_llm_port, mock_working_memory):
        """payload 用 query 字段而非 text 时也能工作。"""
        event = MagicMock()
        event.payload = {"query": "从query字段来"}
        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_working_memory,
        )
        result = await handler.handle(event)

        assert result["success"] is True
        call_args = mock_llm_port.chat.call_args
        messages = call_args[0][0]
        assert messages[-1]["content"] == "从query字段来"

    async def test_handle_remember_swallows_exceptions(self, mock_event, mock_llm_port):
        """remember 异常时不影响主流程。"""
        mock_wm = MagicMock(spec=WorkingMemory)
        mock_wm.recall.return_value = WorkingMemorySnapshot()
        mock_wm.remember.side_effect = RuntimeError("db down")

        handler = ConsciousLLMHandler(
            llm_port=mock_llm_port,
            working_memory=mock_wm,
        )
        # 不应抛异常
        result = await handler.handle(mock_event)
        assert result["success"] is True
