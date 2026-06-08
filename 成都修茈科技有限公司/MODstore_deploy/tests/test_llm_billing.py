from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from modstore_server.llm_billing import (
    UsageMeter,
    WalletHold,
    calculate_charge,
    estimate_tokens_from_message_content,
    estimate_tokens_from_text,
    model_price,
    money,
    money_str,
    usage_from_response,
)


class TestMoney:
    def test_zero(self):
        assert money(0) == Decimal("0.00")

    def test_integer(self):
        assert money(100) == Decimal("100.00")

    def test_float(self):
        assert money(1.5) == Decimal("1.50")

    def test_string(self):
        assert money("3.456") == Decimal("3.46")

    def test_none(self):
        assert money(None) == Decimal("0.00")

    def test_rounding(self):
        assert money("1.005") == Decimal("1.01")


class TestMoneyStr:
    def test_format(self):
        assert money_str(1.5) == "1.50"

    def test_zero(self):
        assert money_str(0) == "0.00"


class TestEstimateTokensFromText:
    def test_empty(self):
        assert estimate_tokens_from_text("") >= 1

    def test_short(self):
        result = estimate_tokens_from_text("hi")
        assert result >= 1

    def test_long(self):
        result = estimate_tokens_from_text("a" * 100)
        assert result >= 25

    def test_none(self):
        result = estimate_tokens_from_text(None)
        assert result >= 1


class TestEstimateTokensFromMessageContent:
    def test_string_content(self):
        result = estimate_tokens_from_message_content("hello world")
        assert result >= 1

    def test_list_content_with_text(self):
        content = [{"type": "text", "text": "hello"}]
        result = estimate_tokens_from_message_content(content)
        assert result >= 1

    def test_list_content_with_image(self):
        content = [{"type": "image_url", "image_url": {"url": "http://example.com/img.png"}}]
        result = estimate_tokens_from_message_content(content)
        assert result >= 1

    def test_non_dict_list_items(self):
        content = ["not a dict", 42]
        result = estimate_tokens_from_message_content(content)
        assert result >= 1

    def test_other_type(self):
        result = estimate_tokens_from_message_content(42)
        assert result >= 1


class TestUsageFromResponse:
    def test_with_openai_usage(self):
        raw = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        usage = usage_from_response(raw, [], "")
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 20
        assert usage.total_tokens == 30
        assert usage.estimated is False

    def test_with_anthropic_usage(self):
        raw = {"input_tokens": 15, "output_tokens": 25}
        usage = usage_from_response(raw, [], "")
        assert usage.prompt_tokens == 15
        assert usage.completion_tokens == 25
        assert usage.estimated is False

    def test_with_no_usage_estimates(self):
        messages = [{"content": "hello world test message"}]
        usage = usage_from_response(None, messages, "response text here")
        assert usage.estimated is True
        assert usage.prompt_tokens >= 1
        assert usage.completion_tokens >= 1

    def test_total_computed_when_missing(self):
        raw = {"prompt_tokens": 10, "completion_tokens": 20}
        usage = usage_from_response(raw, [], "")
        assert usage.total_tokens == 30


class TestModelPrice:
    def test_default_when_no_row(self):
        session = MagicMock()
        session.query().filter().first.return_value = None
        in_p, out_p, min_c = model_price(session, "openai", "gpt-4")
        assert in_p == Decimal("0.006")
        assert out_p == Decimal("0.018")
        assert min_c == Decimal("0.02")


class TestCalculateCharge:
    def test_basic_calculation(self):
        session = MagicMock()
        session.query().filter().first.return_value = None
        usage = UsageMeter(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        charge = calculate_charge(session, "openai", "gpt-4", usage)
        assert isinstance(charge, Decimal)
        assert charge > 0

    def test_minimum_charge(self):
        session = MagicMock()
        session.query().filter().first.return_value = None
        usage = UsageMeter(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        charge = calculate_charge(session, "openai", "gpt-4", usage)
        assert charge >= Decimal("0.02")


class TestUsageMeter:
    def test_defaults(self):
        m = UsageMeter(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert m.estimated is False

    def test_estimated_flag(self):
        m = UsageMeter(prompt_tokens=10, completion_tokens=20, total_tokens=30, estimated=True)
        assert m.estimated is True


class TestWalletHold:
    def test_creation(self):
        h = WalletHold(hold_no="H001", amount=Decimal("1.50"), enabled=True)
        assert h.hold_no == "H001"
        assert h.amount == Decimal("1.50")
        assert h.enabled is True
