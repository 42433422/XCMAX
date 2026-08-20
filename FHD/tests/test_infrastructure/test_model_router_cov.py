# mypy: disable-error-code="misc"
"""Tests for app.infrastructure.llm.model_router — 覆盖率补齐。

聚焦现有 test_model_router.py 未覆盖的路径：
- 模块级辅助函数（_coerce_bool / _coerce_int）
- ModelRouter 私有静态方法（_validate_tier / _coerce_keywords / _is_cjk / _resolve_repo_root）
- _read_json_config / _load_config 的 JSON 路径与异常路径
- RoutingRequest.__post_init__ 边界
- ModelRouter.is_simple_intent / _match_large_keyword
- route() 阈值边界（等于阈值不触发 large）+ 自定义配置路由

所有用例独立运行，不依赖外部服务；通过 monkeypatch 隔离环境变量，tmp_path 隔离 JSON 配置。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.infrastructure.llm.model_router import (
    _DEFAULT_LARGE_HISTORY_TURNS,
    _DEFAULT_LARGE_INTENT_KEYWORDS,
    _DEFAULT_LARGE_MESSAGE_LENGTH,
    _DEFAULT_LARGE_MODEL,
    _DEFAULT_LARGE_TOOL_COUNT,
    _DEFAULT_SMALL_MODEL,
    ModelRouter,
    RoutingDecision,
    RoutingRequest,
    _coerce_bool,
    _coerce_int,
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


# ---------------- _coerce_bool ----------------


class TestCoerceBool:
    """_coerce_bool 辅助函数测试。"""

    def test_none_returns_default(self) -> None:
        assert _coerce_bool(None, False) is False
        assert _coerce_bool(None, True) is True

    @pytest.mark.parametrize(
        "raw",
        ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON", "  true  "],
    )
    def test_truthy_values(self, raw: str) -> None:
        assert _coerce_bool(raw, False) is True

    @pytest.mark.parametrize(
        "raw",
        ["0", "false", "False", "no", "off", "", "  ", "anything-else", "2"],
    )
    def test_falsy_values(self, raw: str) -> None:
        assert _coerce_bool(raw, True) is False


# ---------------- _coerce_int ----------------


class TestCoerceInt:
    """_coerce_int 辅助函数测试。"""

    def test_valid_int(self) -> None:
        assert _coerce_int(5, 0) == 5
        assert _coerce_int("10", 0) == 10

    def test_string_with_whitespace_parsed(self) -> None:
        # int("  10  ") == 10 in Python
        assert _coerce_int("  10  ", 0) == 10

    def test_below_minimum_clamped(self) -> None:
        assert _coerce_int(-5, 10, minimum=0) == 0
        assert _coerce_int(-1, 10, minimum=2) == 2

    def test_at_minimum_returned(self) -> None:
        assert _coerce_int(0, 5, minimum=0) == 0
        assert _coerce_int(1, 5, minimum=1) == 1

    def test_invalid_returns_default(self) -> None:
        assert _coerce_int("not-a-number", 7) == 7
        assert _coerce_int(None, 7) == 7

    def test_invalid_returns_default_ignores_minimum(self) -> None:
        # invalid → default (not clamped to minimum)
        assert _coerce_int("bad", 5, minimum=10) == 5

    def test_float_truncated(self) -> None:
        assert _coerce_int(3.9, 0) == 3
        assert _coerce_int(0.1, 5, minimum=0) == 0


# ---------------- RoutingRequest 边界 ----------------


class TestRoutingRequestPostInit:
    """RoutingRequest.__post_init__ 防御性规范化测试。"""

    def test_message_non_string_coerced_to_string(self) -> None:
        req = RoutingRequest(message=12345)  # type: ignore[arg-type]
        assert req.message == "12345"

    def test_message_zero_coerced_to_empty_string(self) -> None:
        # 0 is falsy → `(0 or "")` → "" → str("") = ""
        req = RoutingRequest(message=0)  # type: ignore[arg-type]
        assert req.message == ""

    def test_intent_whitespace_only_becomes_none(self) -> None:
        req = RoutingRequest(message="hi", intent="   ")
        assert req.intent is None

    def test_intent_stripped(self) -> None:
        req = RoutingRequest(message="hi", intent="  workflow  ")
        assert req.intent == "workflow"

    def test_intent_empty_string_becomes_none(self) -> None:
        req = RoutingRequest(message="hi", intent="")
        assert req.intent is None

    def test_profile_whitespace_only_becomes_none(self) -> None:
        req = RoutingRequest(message="hi", profile="   ")
        assert req.profile is None

    def test_profile_lowercased(self) -> None:
        req = RoutingRequest(message="hi", profile="REASONING")
        assert req.profile == "reasoning"

    def test_profile_stripped_and_lowercased(self) -> None:
        req = RoutingRequest(message="hi", profile="  FAST  ")
        assert req.profile == "fast"

    def test_profile_empty_string_becomes_none(self) -> None:
        req = RoutingRequest(message="hi", profile="")
        assert req.profile is None

    def test_tool_count_float_truncated(self) -> None:
        req = RoutingRequest(message="hi", tool_count=3.9)  # type: ignore[arg-type]
        assert req.tool_count == 3

    def test_tool_count_float_string_falls_back_to_zero(self) -> None:
        # int("3.9") raises ValueError → fallback 0
        req = RoutingRequest(message="hi", tool_count="3.9")  # type: ignore[arg-type]
        assert req.tool_count == 0

    def test_tool_count_negative_preserved(self) -> None:
        # __post_init__ does not clamp negative; route() handles via > comparison
        req = RoutingRequest(message="hi", tool_count=-5)
        assert req.tool_count == -5

    def test_history_len_float_truncated(self) -> None:
        req = RoutingRequest(message="hi", conversation_history_len=11.7)  # type: ignore[arg-type]
        assert req.conversation_history_len == 11

    def test_history_len_bool_converted(self) -> None:
        # bool is subclass of int; int(True) = 1
        req = RoutingRequest(message="hi", conversation_history_len=True)  # type: ignore[arg-type]
        assert req.conversation_history_len == 1

    def test_history_len_invalid_string_falls_back(self) -> None:
        req = RoutingRequest(message="hi", conversation_history_len="bad")  # type: ignore[arg-type]
        assert req.conversation_history_len == 0


# ---------------- RoutingDecision ----------------


class TestRoutingDecision:
    """RoutingDecision 数据类测试。"""

    def test_fields_assigned(self) -> None:
        d = RoutingDecision(model_tier="small", model_name="m", reason="r")
        assert d.model_tier == "small"
        assert d.model_name == "m"
        assert d.reason == "r"

    def test_to_dict_returns_all_fields(self) -> None:
        d = RoutingDecision(model_tier="large", model_name="gpt", reason="why")
        out = d.to_dict()
        assert set(out.keys()) == {"model_tier", "model_name", "reason"}
        assert out["model_tier"] == "large"
        assert out["model_name"] == "gpt"
        assert out["reason"] == "why"


# ---------------- ModelRouter 静态方法 ----------------


class TestModelRouterStaticHelpers:
    """ModelRouter 私有静态方法测试。"""

    def test_validate_tier_valid(self) -> None:
        assert ModelRouter._validate_tier("small", "large") == "small"
        assert ModelRouter._validate_tier("large", "small") == "large"

    def test_validate_tier_case_insensitive(self) -> None:
        assert ModelRouter._validate_tier("SMALL", "large") == "small"
        assert ModelRouter._validate_tier("Large", "small") == "large"

    def test_validate_tier_stripped(self) -> None:
        assert ModelRouter._validate_tier("  small  ", "large") == "small"

    def test_validate_tier_invalid_returns_default(self) -> None:
        assert ModelRouter._validate_tier("medium", "small") == "small"
        assert ModelRouter._validate_tier("", "large") == "large"
        assert ModelRouter._validate_tier(None, "large") == "large"
        assert ModelRouter._validate_tier(123, "small") == "small"

    def test_coerce_keywords_non_list_returns_default(self) -> None:
        default = ("a", "b")
        assert ModelRouter._coerce_keywords(None, default) == default
        assert ModelRouter._coerce_keywords("not-a-list", default) == default
        assert ModelRouter._coerce_keywords({"a": 1}, default) == default

    def test_coerce_keywords_empty_list_returns_default(self) -> None:
        default = ("a", "b")
        assert ModelRouter._coerce_keywords([], default) == default

    def test_coerce_keywords_strips_and_filters_empty(self) -> None:
        result = ModelRouter._coerce_keywords(["  a  ", "", "  ", "b"], ("default",))
        assert result == ("a", "b")

    def test_coerce_keywords_all_empty_returns_default(self) -> None:
        default = ("default",)
        assert ModelRouter._coerce_keywords(["", "  "], default) == default

    def test_coerce_keywords_non_string_items_coerced(self) -> None:
        result = ModelRouter._coerce_keywords([1, 2, "  ", 3], ("default",))
        assert result == ("1", "2", "3")

    def test_is_cjk_ascii_returns_false(self) -> None:
        assert ModelRouter._is_cjk("a") is False
        assert ModelRouter._is_cjk(" ") is False
        assert ModelRouter._is_cjk("1") is False

    def test_is_cjk_main_range(self) -> None:
        # 0x4E00 = '一', 0x4F60 = '你', 0x9FFF = last char of main range
        assert ModelRouter._is_cjk(chr(0x4E00)) is True
        assert ModelRouter._is_cjk(chr(0x4F60)) is True
        assert ModelRouter._is_cjk(chr(0x9FFF)) is True

    def test_is_cjk_ext_a_range(self) -> None:
        assert ModelRouter._is_cjk(chr(0x3400)) is True
        assert ModelRouter._is_cjk(chr(0x4DBF)) is True

    def test_is_cjk_compat_range(self) -> None:
        assert ModelRouter._is_cjk(chr(0xF900)) is True
        assert ModelRouter._is_cjk(chr(0xFAFF)) is True

    def test_is_cjk_ext_b_range(self) -> None:
        assert ModelRouter._is_cjk(chr(0x20000)) is True
        assert ModelRouter._is_cjk(chr(0x2A6DF)) is True

    def test_is_cjk_just_outside_ranges(self) -> None:
        # 0x4DC0 is just above ext A end (0x4DBF), below main start (0x4E00)
        assert ModelRouter._is_cjk(chr(0x4DC0)) is False
        # 0xFB00 is just above compat end (0xFAFF)
        assert ModelRouter._is_cjk(chr(0xFB00)) is False
        # 0x2A6E0 is just above ext B end (0x2A6DF)
        assert ModelRouter._is_cjk(chr(0x2A6E0)) is False

    def test_resolve_repo_root_returns_path_or_none(self) -> None:
        # Static method — should return Path (project root) or None.
        result = ModelRouter._resolve_repo_root()
        assert result is None or isinstance(result, Path)

    def test_is_simple_intent_none_and_empty(self) -> None:
        assert ModelRouter.is_simple_intent(None) is False
        assert ModelRouter.is_simple_intent("") is False
        assert ModelRouter.is_simple_intent("   ") is False

    def test_is_simple_intent_in_whitelist(self) -> None:
        assert ModelRouter.is_simple_intent("customers") is True
        assert ModelRouter.is_simple_intent("product_query") is True
        assert ModelRouter.is_simple_intent("greeting") is True

    def test_is_simple_intent_case_insensitive(self) -> None:
        assert ModelRouter.is_simple_intent("Customers") is True
        assert ModelRouter.is_simple_intent("PRODUCT_QUERY") is True

    def test_is_simple_intent_stripped(self) -> None:
        assert ModelRouter.is_simple_intent("  customers  ") is True

    def test_is_simple_intent_not_in_whitelist(self) -> None:
        assert ModelRouter.is_simple_intent("analysis") is False
        assert ModelRouter.is_simple_intent("workflow") is False
        assert ModelRouter.is_simple_intent("unknown_intent") is False


# ---------------- ModelRouter.estimate_tokens 边界 ----------------


class TestEstimateTokensEdgeCases:
    """estimate_tokens 边界场景。"""

    def test_single_ascii_returns_zero(self) -> None:
        # 1 / 4 = 0.25 → round → 0
        router = ModelRouter()
        assert router.estimate_tokens("a") == 0

    def test_four_ascii_returns_one(self) -> None:
        router = ModelRouter()
        assert router.estimate_tokens("abcd") == 1

    def test_single_chinese_returns_one(self) -> None:
        # 1 / 1.5 = 0.667 → round → 1
        router = ModelRouter()
        assert router.estimate_tokens("你") == 1

    def test_two_chinese_returns_one(self) -> None:
        # 2 / 1.5 = 1.333 → round → 1
        router = ModelRouter()
        assert router.estimate_tokens("你好") == 1

    def test_three_chinese_returns_two(self) -> None:
        # 3 / 1.5 = 2.0 → round → 2
        router = ModelRouter()
        assert router.estimate_tokens("你好世") == 2

    def test_estimate_tokens_non_string_coerced(self) -> None:
        router = ModelRouter()
        # 12345 → 5 ASCII digits → 5/4 = 1.25 → round → 1
        assert router.estimate_tokens(12345) == 1  # type: ignore[arg-type]

    def test_estimate_tokens_zero_returns_zero(self) -> None:
        router = ModelRouter()
        # not 0 → True → early return 0
        assert router.estimate_tokens(0) == 0  # type: ignore[arg-type]


# ---------------- _match_large_keyword ----------------


class TestMatchLargeKeyword:
    """_match_large_keyword 内部方法测试。"""

    def test_intent_contains_keyword_returns_kw(self) -> None:
        router = ModelRouter()
        result = router._match_large_keyword("workflow_planner", "")
        assert result == "workflow"

    def test_intent_case_insensitive(self) -> None:
        router = ModelRouter()
        result = router._match_large_keyword("WORKFLOW_x", "")
        assert result == "workflow"

    def test_message_contains_chinese_keyword(self) -> None:
        router = ModelRouter()
        result = router._match_large_keyword(None, "请帮我分析数据")
        assert result == "分析"

    def test_no_match_returns_none(self) -> None:
        router = ModelRouter()
        result = router._match_large_keyword("greeting", "你好")
        assert result is None

    def test_both_none_returns_none(self) -> None:
        router = ModelRouter()
        result = router._match_large_keyword(None, "")
        assert result is None

    def test_intent_match_takes_precedence_over_message(self) -> None:
        # Both could match; intent is checked first
        router = ModelRouter()
        # intent "workflow_x" matches "workflow"
        # message "请帮我分析" matches "分析"
        # Expect intent match → returns "workflow"
        result = router._match_large_keyword("workflow_x", "请帮我分析")
        assert result == "workflow"

    def test_intent_none_message_match(self) -> None:
        router = ModelRouter()
        result = router._match_large_keyword(None, "multi_step procedure")
        assert result == "multi_step"

    def test_intent_empty_string_falls_back_to_message(self) -> None:
        router = ModelRouter()
        # Empty intent string is falsy → fall back to message
        result = router._match_large_keyword("", "请帮我做月度报表")
        assert result == "报表"


# ---------------- _read_json_config / _load_config ----------------


class TestLoadConfig:
    """_load_config / _read_json_config 测试。"""

    def test_load_config_with_nonexistent_path_uses_defaults(self) -> None:
        router = ModelRouter(config_path="/nonexistent/path/to/config.json")
        cfg = router.config
        assert cfg.default_tier == "small"
        assert cfg.small_model == _DEFAULT_SMALL_MODEL
        assert cfg.large_model == _DEFAULT_LARGE_MODEL
        assert cfg.large_intent_keywords == _DEFAULT_LARGE_INTENT_KEYWORDS
        assert cfg.large_message_length == _DEFAULT_LARGE_MESSAGE_LENGTH
        assert cfg.large_tool_count == _DEFAULT_LARGE_TOOL_COUNT
        assert cfg.large_history_turns == _DEFAULT_LARGE_HISTORY_TURNS

    def test_read_json_config_nonexistent_returns_none(self) -> None:
        router = ModelRouter(config_path="/nonexistent/path/to/config.json")
        assert router._read_json_config() is None

    def test_read_json_config_valid_returns_dict(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"default_tier": "large"}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        data = router._read_json_config()
        assert isinstance(data, dict)
        assert data["default_tier"] == "large"

    def test_load_config_with_invalid_json_uses_defaults(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json ", encoding="utf-8")
        router = ModelRouter(config_path=str(bad))
        cfg = router.config
        # JSON load failed → defaults retained
        assert cfg.small_model == _DEFAULT_SMALL_MODEL
        assert cfg.large_model == _DEFAULT_LARGE_MODEL
        assert cfg.default_tier == "small"

    def test_load_config_with_valid_json_overrides_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "default_tier": "large",
                    "small_model": "json-small",
                    "large_model": "json-large",
                    "rules": {
                        "large_intent_keywords": ["custom_kw"],
                        "large_message_length": 500,
                        "large_tool_count": 5,
                        "large_history_turns": 20,
                    },
                }
            ),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        cfg = router.config
        assert cfg.default_tier == "large"
        assert cfg.small_model == "json-small"
        assert cfg.large_model == "json-large"
        assert cfg.large_intent_keywords == ("custom_kw",)
        assert cfg.large_message_length == 500
        assert cfg.large_tool_count == 5
        assert cfg.large_history_turns == 20

    def test_load_config_invalid_tier_falls_back(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"default_tier": "medium"}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        # "medium" not in {small, large} → default fallback "small"
        assert router.config.default_tier == "small"

    def test_load_config_non_string_model_ignored(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"small_model": 123, "large_model": None}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        # Non-string values fall back to defaults
        assert router.config.small_model == _DEFAULT_SMALL_MODEL
        assert router.config.large_model == _DEFAULT_LARGE_MODEL

    def test_load_config_empty_string_model_ignored(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"small_model": "", "large_model": ""}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        # Empty strings fall back to defaults
        assert router.config.small_model == _DEFAULT_SMALL_MODEL
        assert router.config.large_model == _DEFAULT_LARGE_MODEL

    def test_load_config_rules_not_dict_ignored(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"rules": "not-a-dict"}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        cfg = router.config
        # Non-dict rules → all rule fields retain defaults
        assert cfg.large_intent_keywords == _DEFAULT_LARGE_INTENT_KEYWORDS
        assert cfg.large_message_length == _DEFAULT_LARGE_MESSAGE_LENGTH

    def test_load_config_invalid_rule_values_use_defaults(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "rules": {
                        "large_intent_keywords": "not-a-list",
                        "large_message_length": "not-a-number",
                        "large_tool_count": None,
                        "large_history_turns": "bad",
                    }
                }
            ),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        cfg = router.config
        # All invalid → all defaults
        assert cfg.large_intent_keywords == _DEFAULT_LARGE_INTENT_KEYWORDS
        assert cfg.large_message_length == _DEFAULT_LARGE_MESSAGE_LENGTH
        assert cfg.large_tool_count == _DEFAULT_LARGE_TOOL_COUNT
        assert cfg.large_history_turns == _DEFAULT_LARGE_HISTORY_TURNS

    def test_load_config_rule_below_minimum_clamped(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "rules": {
                        "large_message_length": -100,
                        "large_tool_count": 0,
                        "large_history_turns": -5,
                    }
                }
            ),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        cfg = router.config
        # Below minimum=1 → clamped to 1
        assert cfg.large_message_length == 1
        assert cfg.large_tool_count == 1
        assert cfg.large_history_turns == 1

    def test_env_overrides_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_MODEL_SMALL", "env-small")
        monkeypatch.setenv("FHD_MODEL_LARGE", "env-large")
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"small_model": "json-small", "large_model": "json-large"}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        cfg = router.config
        assert cfg.small_model == "env-small"
        assert cfg.large_model == "env-large"

    def test_env_whitespace_only_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FHD_MODEL_SMALL", "   ")
        monkeypatch.setenv("FHD_MODEL_LARGE", "   ")
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"small_model": "json-small", "large_model": "json-large"}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        # Whitespace-only env → fall back to JSON config
        assert router.config.small_model == "json-small"
        assert router.config.large_model == "json-large"


# ---------------- ModelRouter.route 边界 ----------------


class TestRouteBoundaryConditions:
    """route() 阈值边界条件测试。"""

    def test_message_length_equal_threshold_routes_small(self) -> None:
        # len == threshold → NOT > threshold → small
        router = ModelRouter()
        msg = "a" * _DEFAULT_LARGE_MESSAGE_LENGTH
        decision = router.route(RoutingRequest(message=msg, intent="greeting"))
        assert decision.model_tier == "small"

    def test_tool_count_equal_threshold_routes_small(self) -> None:
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(message="hi", intent="greeting", tool_count=_DEFAULT_LARGE_TOOL_COUNT)
        )
        assert decision.model_tier == "small"

    def test_history_len_equal_threshold_routes_small(self) -> None:
        router = ModelRouter()
        decision = router.route(
            RoutingRequest(
                message="hi",
                intent="greeting",
                conversation_history_len=_DEFAULT_LARGE_HISTORY_TURNS,
            )
        )
        assert decision.model_tier == "small"

    def test_disabled_with_default_large_returns_large_model_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FHD_MODEL_ROUTING_ENABLED", "0")
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"default_tier": "large"}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        assert router.enabled is False
        decision = router.route(
            RoutingRequest(message="hi", intent="greeting", profile="reasoning")
        )
        # Default tier is "large" → large_model used, even though routing disabled
        assert decision.model_tier == "large"
        assert decision.model_name == _DEFAULT_LARGE_MODEL
        assert "routing disabled" in decision.reason

    def test_disabled_with_default_small_returns_small_model_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FHD_MODEL_ROUTING_ENABLED", "0")
        router = ModelRouter()
        assert router.enabled is False
        decision = router.route(
            RoutingRequest(message="hi", intent="greeting", profile="reasoning")
        )
        assert decision.model_tier == "small"
        assert decision.model_name == _DEFAULT_SMALL_MODEL
        assert "routing disabled" in decision.reason

    def test_profile_invalid_falls_through_to_rules(self) -> None:
        # profile="balanced" → not "reasoning" / "fast" → falls through
        router = ModelRouter()
        decision = router.route(RoutingRequest(message="hi", intent="greeting", profile="balanced"))
        assert decision.model_tier == "small"

    def test_profile_none_falls_through_to_rules(self) -> None:
        router = ModelRouter()
        decision = router.route(RoutingRequest(message="hi", intent="greeting", profile=None))
        assert decision.model_tier == "small"

    def test_message_keyword_priority_over_length(self) -> None:
        # Long message AND keyword match — keyword reason returned (checked first)
        router = ModelRouter()
        long_msg = "a" * 3000 + " 分析"
        decision = router.route(RoutingRequest(message=long_msg, intent="greeting"))
        assert decision.model_tier == "large"
        assert "large keyword" in decision.reason

    def test_intent_match_priority_over_length(self) -> None:
        router = ModelRouter()
        long_msg = "a" * 3000
        decision = router.route(RoutingRequest(message=long_msg, intent="workflow_x"))
        assert decision.model_tier == "large"
        assert "large keyword" in decision.reason

    def test_route_with_custom_keywords_from_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"rules": {"large_intent_keywords": ["budget_analysis"]}}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        # Custom keyword matches via intent
        decision = router.route(RoutingRequest(message="hi", intent="budget_analysis_q1"))
        assert decision.model_tier == "large"
        assert "budget_analysis" in decision.reason

    def test_route_with_custom_thresholds_from_config(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "routing.json"
        cfg_file.write_text(
            json.dumps({"rules": {"large_message_length": 50}}),
            encoding="utf-8",
        )
        router = ModelRouter(config_path=str(cfg_file))
        # 100 chars > custom threshold 50 → large
        decision = router.route(RoutingRequest(message="a" * 100, intent="greeting"))
        assert decision.model_tier == "large"
        assert "message length" in decision.reason


# ---------------- 单例 ----------------


class TestSingletonLifecycle:
    """get_model_router / reset_model_router 单例生命周期。"""

    def test_reset_clears_singleton(self) -> None:
        r1 = get_model_router()
        reset_model_router()
        r2 = get_model_router()
        assert r1 is not r2

    def test_get_returns_router_instance(self) -> None:
        router = get_model_router()
        assert isinstance(router, ModelRouter)

    def test_reset_idempotent(self) -> None:
        # Calling reset multiple times should not error
        reset_model_router()
        reset_model_router()
        reset_model_router()
        assert get_model_router() is not None


# ---------------- 默认值常量 ----------------


class TestDefaultConstants:
    """模块默认常量完整性检查（防止误改）。"""

    def test_default_model_constants(self) -> None:
        assert _DEFAULT_SMALL_MODEL == "deepseek-chat"
        assert _DEFAULT_LARGE_MODEL == "deepseek-reasoner"
        assert _DEFAULT_LARGE_MESSAGE_LENGTH == 2000
        assert _DEFAULT_LARGE_TOOL_COUNT == 3
        assert _DEFAULT_LARGE_HISTORY_TURNS == 10

    def test_default_keywords_tuple_contents(self) -> None:
        # Ensure the default keyword tuple contains expected entries
        assert "分析" in _DEFAULT_LARGE_INTENT_KEYWORDS
        assert "workflow" in _DEFAULT_LARGE_INTENT_KEYWORDS
        assert "multi_step" in _DEFAULT_LARGE_INTENT_KEYWORDS
        assert isinstance(_DEFAULT_LARGE_INTENT_KEYWORDS, tuple)
