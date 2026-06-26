"""测试 :mod:`app.infrastructure.llm.token_estimator` 的单元测试。

覆盖场景（遵循 ``.trae/rules/test-coverage-90-prompt.md`` 铁律 3）：

- happy path：纯中文 / 纯英文 / 混合文本
- 空值 / None：``None``、空字符串、纯空白、纯标点、纯数字
- 边界值：单字符、单单词、超长文本
- estimate_messages_tokens：None / 空 / 单条 / 多条 / 非 dict / 缺 content / 非 str content
"""

from __future__ import annotations

import pytest

from app.infrastructure.llm.token_estimator import (
    estimate_messages_tokens,
    estimate_tokens,
)


class TestEstimateTokens:
    """``estimate_tokens`` 单元测试套件。"""

    def test_estimate_tokens_none_returns_zero(self) -> None:
        """None 输入返回 0。"""
        assert estimate_tokens(None) == 0

    def test_estimate_tokens_empty_string_returns_zero(self) -> None:
        """空字符串返回 0。"""
        assert estimate_tokens("") == 0

    def test_estimate_tokens_whitespace_only_returns_zero(self) -> None:
        """纯空白字符（不计入 token）返回 0。"""
        assert estimate_tokens("   \n\t  ") == 0

    def test_estimate_tokens_punctuation_only_returns_zero(self) -> None:
        """纯标点符号（不计入 token）返回 0。"""
        assert estimate_tokens("！？。，！？") == 0

    def test_estimate_tokens_digits_only_returns_zero(self) -> None:
        """纯数字（不计入 token）返回 0。"""
        assert estimate_tokens("1234567890") == 0

    def test_estimate_tokens_pure_chinese_returns_estimated(self) -> None:
        """纯中文按 1 字 ≈ 1.5 token 估算。

        "你好世界" = 4 个中文字 → 4 * 1.5 = 6.0 → int(6.0) = 6
        """
        assert estimate_tokens("你好世界") == 6

    def test_estimate_tokens_single_chinese_char_returns_estimated(self) -> None:
        """单个中文字符边界值。

        "你" = 1 个中文字 → 1 * 1.5 = 1.5 → int(1.5) = 1
        """
        assert estimate_tokens("你") == 1

    def test_estimate_tokens_pure_english_returns_estimated(self) -> None:
        """纯英文按 1 词 ≈ 1.3 token 估算。

        "hello world" = 2 个英文词 → 2 * 1.3 = 2.6 → int(2.6) = 2
        """
        assert estimate_tokens("hello world") == 2

    def test_estimate_tokens_single_english_word_returns_estimated(self) -> None:
        """单个英文单词边界值。

        "hello" = 1 个英文词 → 1 * 1.3 = 1.3 → int(1.3) = 1
        """
        assert estimate_tokens("hello") == 1

    def test_estimate_tokens_mixed_returns_estimated(self) -> None:
        """中英混合文本累加估算。

        "你好 world" = 2 中文字 + 1 英文词 → 2*1.5 + 1*1.3 = 3.0 + 1.3 = 4.3 → int(4.3) = 4
        """
        assert estimate_tokens("你好 world") == 4

    def test_estimate_tokens_mixed_with_punctuation_returns_estimated(self) -> None:
        """中英混合带标点（标点不计入）。

        "你好，world！" = 2 中文字 + 1 英文词 → 2*1.5 + 1*1.3 = 4.3 → 4
        """
        assert estimate_tokens("你好，world！") == 4

    def test_estimate_tokens_long_text_returns_estimated(self) -> None:
        """超长文本正常估算（无性能问题、无溢出）。"""
        # 1000 个中文字 + 1000 个英文词
        text = "你" * 1000 + " word" * 1000
        result = estimate_tokens(text)
        # 1000 * 1.5 + 1000 * 1.3 = 1500 + 1300 = 2800
        assert result == 2800

    def test_estimate_tokens_case_insensitive_english(self) -> None:
        """英文大小写不影响词数计数（findall 匹配大小写）。"""
        assert estimate_tokens("Hello WORLD") == estimate_tokens("hello world")

    def test_estimate_tokens_returns_int_type(self) -> None:
        """返回值类型为 int（不是 float）。"""
        result = estimate_tokens("test")
        assert isinstance(result, int)
        assert not isinstance(result, float)  # bool 是 int 子类，但这里不是 bool


class TestEstimateMessagesTokens:
    """``estimate_messages_tokens`` 单元测试套件。"""

    def test_estimate_messages_tokens_none_returns_zero(self) -> None:
        """None 输入返回 0。"""
        assert estimate_messages_tokens(None) == 0

    def test_estimate_messages_tokens_empty_list_returns_zero(self) -> None:
        """空列表返回 0。"""
        assert estimate_messages_tokens([]) == 0

    def test_estimate_messages_tokens_single_message_returns_content_tokens(self) -> None:
        """单条消息返回 content 的 token 数。

        "你好世界" content → 6 token
        """
        messages = [{"role": "user", "content": "你好世界"}]
        assert estimate_messages_tokens(messages) == 6

    def test_estimate_messages_tokens_multiple_messages_returns_sum(self) -> None:
        """多条消息返回 content token 数之和。"""
        messages = [
            {"role": "system", "content": "你好"},  # 2 * 1.5 = 3
            {"role": "user", "content": "hello"},  # 1 * 1.3 = 1.3 → 1
            {"role": "assistant", "content": "世界"},  # 2 * 1.5 = 3
        ]
        # 3 + 1 + 3 = 7
        assert estimate_messages_tokens(messages) == 7

    def test_estimate_messages_tokens_skips_non_dict_entries(self) -> None:
        """非 dict 条目被跳过（不抛异常）。"""
        messages = [
            {"role": "user", "content": "你好"},  # 3
            "not a dict",  # 跳过
            None,  # 跳过
            42,  # 跳过
            {"role": "assistant", "content": "世界"},  # 3
        ]
        assert estimate_messages_tokens(messages) == 6

    def test_estimate_messages_tokens_skips_missing_content(self) -> None:
        """缺 content 字段的消息被跳过。"""
        messages = [
            {"role": "user", "content": "你好"},  # 3
            {"role": "system"},  # 无 content，跳过
            {"content": "世界"},  # 有 content，3
        ]
        assert estimate_messages_tokens(messages) == 6

    def test_estimate_messages_tokens_none_content_skipped(self) -> None:
        """content 为 None 的消息被跳过。"""
        messages = [
            {"role": "user", "content": "你好"},  # 3
            {"role": "system", "content": None},  # 跳过
        ]
        assert estimate_messages_tokens(messages) == 3

    def test_estimate_messages_tokens_non_string_content_converts_to_string(self) -> None:
        """非 str content（如多模态 list）转为 str 后估算。"""
        # content 是 list，str(list) 会包含英文字母
        messages = [{"role": "user", "content": ["hello", "world"]}]
        # str(["hello", "world"]) = "['hello', 'world']"
        # 英文词：hello, world = 2 词 → 2 * 1.3 = 2.6 → 2
        result = estimate_messages_tokens(messages)
        assert result > 0
        assert isinstance(result, int)

    def test_estimate_messages_tokens_empty_content_returns_zero(self) -> None:
        """所有消息 content 为空时返回 0。"""
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": ""},
        ]
        assert estimate_messages_tokens(messages) == 0

    def test_estimate_messages_tokens_returns_int_type(self) -> None:
        """返回值类型为 int。"""
        result = estimate_messages_tokens([{"role": "user", "content": "hi"}])
        assert isinstance(result, int)

    def test_estimate_messages_tokens_preserves_input_list(self) -> None:
        """估算过程不修改输入列表（无副作用）。"""
        messages = [{"role": "user", "content": "你好世界"}]
        original = [dict(m) for m in messages]
        estimate_messages_tokens(messages)
        assert messages == original
