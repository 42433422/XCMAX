# mypy: disable-error-code="misc"
"""Tests for app.infrastructure.llm.model_router — ModelRouter 路由判定与 token 估算。

覆盖路由规则的 7 条优先级路径 + 配置加载 + 向后兼容（enabled=False 时回退默认 tier）。
所有用例独立运行，不依赖外部服务，不依赖特定环境变量（通过 monkeypatch 隔离）。
"""

from __future__ import annotations

import pytest

from app.infrastructure.llm.model_router import (
    ModelRouter,
    RoutingDecision,
    RoutingRequest,
    get_model_router,
    reset_model_router,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例独立的环境变量上下文。

    - 默认开启路由（``FHD_MODEL_ROUTING_ENABLED=1``），多数用例需要 enabled=True
    - 清空 FHD_MODEL_SMALL / FHD_MODEL_LARGE，让用例显式设置或退回 config 文件默认
    - 重置单例，避免上一个用例的实例泄漏
    """
    monkeypatch.setenv("FHD_MODEL_ROUTING_ENABLED", "1")
    monkeypatch.delenv("FHD_MODEL_SMALL", raising=False)
    monkeypatch.delenv("FHD_MODEL_LARGE", raising=False)
    reset_model_router()
    yield
    reset_model_router()


class TestModelRouterRouting:
    """路由规则优先级测试。"""

    def test_simple_intent_routes_to_small(self) -> None:
        """简单 CRUD 意图 + 短消息 + 无工具 → small。"""
        router = ModelRouter()
        decision = router.route(RoutingRequest(message="查询产品列表", intent="product_query"))
        assert decision.model_tier == "small"
        assert decision.model_name == "deepseek-chat"
        assert "default" in decision.reason or "cost" in decision.reason

    def test_complex_intent_routes_to_large(self) -> None:
        """复杂意图（命中 large_intent_keywords）→ large。"""
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(
                message="请帮我分析本月销售数据",
                intent="analysis",
            )
        )
        assert decision.model_tier == "large"
        assert decision.model_name == "deepseek-reasoner"
        assert "large keyword" in decision.reason

    def test_long_message_routes_to_large(self) -> None:
        """消息长度 > 2000 字符 → large。"""
        router = ModelRouter()
        long_message = "a" * 2001  # 2001 > 2000 阈值
        decision = router.route(RoutingRequest(message=long_message, intent="product_query"))
        assert decision.model_tier == "large"
        assert "message length" in decision.reason
        assert "2001" in decision.reason

    def test_many_tools_routes_to_large(self) -> None:
        """工具数 > 3 → large。"""
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(
                message="执行多步操作",
                intent="product_query",
                tool_count=4,
            )
        )
        assert decision.model_tier == "large"
        assert "tool_count" in decision.reason

    def test_long_history_routes_to_large(self) -> None:
        """对话历史 > 10 轮 → large。"""
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(
                message="继续",
                intent="chat",
                conversation_history_len=11,
            )
        )
        assert decision.model_tier == "large"
        assert "history_len" in decision.reason
        assert "11" in decision.reason

    def test_profile_reasoning_forces_large(self) -> None:
        """profile=reasoning 强制 large（即使消息很短、意图简单）。"""
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(
                message="hi",
                intent="greeting",
                profile="reasoning",
            )
        )
        assert decision.model_tier == "large"
        assert decision.model_name == "deepseek-reasoner"
        assert "reasoning" in decision.reason

    def test_profile_fast_forces_small(self) -> None:
        """profile=fast 强制 small（即使消息很长、工具很多）。"""
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(
                message="x" * 5000,
                intent="analysis",
                tool_count=10,
                profile="fast",
            )
        )
        assert decision.model_tier == "small"
        assert decision.model_name == "deepseek-chat"
        assert "fast" in decision.reason

    def test_default_routes_to_small(self) -> None:
        """无任何触发条件 → 默认 small（成本优先）。"""
        router = ModelRouter()
        decision = router.route(RoutingRequest(message="你好", intent="greeting"))
        assert decision.model_tier == "small"
        assert "default" in decision.reason or "cost" in decision.reason


class TestModelRouterTokenEstimation:
    """token 估算测试。"""

    def test_estimate_tokens_empty_returns_zero(self) -> None:
        """空文本 → 0 token。"""
        router = ModelRouter()
        assert router.estimate_tokens("") == 0
        assert router.estimate_tokens(None) == 0  # type: ignore[arg-type]

    def test_estimate_tokens_pure_chinese(self) -> None:
        """纯中文：1.5 字/token。"""
        router = ModelRouter()
        # 6 个中文字符 → 6 / 1.5 = 4 token
        assert router.estimate_tokens("你好世界测试") == 4

    def test_estimate_tokens_pure_english(self) -> None:
        """纯英文：4 字符/token。"""
        router = ModelRouter()
        # 12 个 ASCII 字符 → 12 / 4 = 3 token
        assert router.estimate_tokens("hello world!") == 3

    def test_estimate_tokens_mixed(self) -> None:
        """中英混合：CJK 按 1.5 字/token，非 CJK 按 4 字符/token。"""
        router = ModelRouter()
        # 4 个中文 + 8 个 ASCII = 4/1.5 + 8/4 ≈ 2.67 + 2 = 4.67 → round → 5
        text = "你好世界" + "abcdefgh"
        result = router.estimate_tokens(text)
        assert result == 5


class TestModelRouterConfig:
    """配置加载与向后兼容测试。"""

    def test_disabled_returns_default_tier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FHD_MODEL_ROUTING_ENABLED 未开启时返回默认 tier decision，不抛错。"""
        monkeypatch.setenv("FHD_MODEL_ROUTING_ENABLED", "0")
        reset_model_router()
        router = ModelRouter()
        assert router.enabled is False

        decision = router.route(
            RoutingRequest(
                message="分析数据",
                intent="analysis",
                profile="reasoning",
            )
        )
        # 未启用时即使所有规则都命中 large，也返回默认 small
        assert decision.model_tier == "small"
        assert "routing disabled" in decision.reason

    def test_env_overrides_config_for_model_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FHD_MODEL_SMALL / FHD_MODEL_LARGE 环境变量覆盖配置文件。"""
        monkeypatch.setenv("FHD_MODEL_SMALL", "qwen-7b")
        monkeypatch.setenv("FHD_MODEL_LARGE", "qwen-72b")
        reset_model_router()
        router = ModelRouter()

        small = router.route(RoutingRequest(message="hi", intent="greeting"))
        assert small.model_tier == "small"
        assert small.model_name == "qwen-7b"

        large = router.route(RoutingRequest(message="hi", intent="greeting", profile="reasoning"))
        assert large.model_tier == "large"
        assert large.model_name == "qwen-72b"

    def test_routing_request_normalizes_invalid_types(self) -> None:
        """RoutingRequest 防御性规范化：非法 tool_count / history_len 不炸。"""
        req = RoutingRequest(
            message=None,  # type: ignore[arg-type]
            intent="  ",
            tool_count="not-a-number",  # type: ignore[arg-type]
            conversation_history_len=None,  # type: ignore[arg-type]
            profile="REASONING",
        )
        assert req.message == ""
        assert req.intent is None
        assert req.tool_count == 0
        assert req.conversation_history_len == 0
        assert req.profile == "reasoning"

    def test_routing_decision_to_dict_roundtrip(self) -> None:
        """RoutingDecision.to_dict() 返回完整字段。"""
        d = RoutingDecision(model_tier="large", model_name="gpt-4o", reason="test reason")
        out = d.to_dict()
        assert out == {
            "model_tier": "large",
            "model_name": "gpt-4o",
            "reason": "test reason",
        }

    def test_singleton_get_model_router_returns_same_instance(self) -> None:
        """get_model_router 单例：连续调用返回同一实例。"""
        reset_model_router()
        r1 = get_model_router()
        r2 = get_model_router()
        assert r1 is r2

    def test_message_keyword_triggers_large(self) -> None:
        """消息文本命中 large_intent_keywords（即使 intent 为 None）→ large。"""
        router = ModelRouter()
        decision = router.route(RoutingRequest(message="请帮我做一份月度报表", intent=None))
        assert decision.model_tier == "large"
        assert "large keyword" in decision.reason
