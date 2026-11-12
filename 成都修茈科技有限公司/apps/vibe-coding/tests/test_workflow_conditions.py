"""Unit tests for the safe condition evaluator."""

from __future__ import annotations

import pytest

from vibe_coding.workflow_conditions import ConditionError, evaluate_condition


class TestLiterals:
    def test_true_literal(self) -> None:
        assert evaluate_condition("True", {}) is True

    def test_false_literal(self) -> None:
        assert evaluate_condition("False", {}) is False

    def test_none_literal_falsy(self) -> None:
        assert evaluate_condition("None", {}) is False

    def test_int_truthy(self) -> None:
        assert evaluate_condition("1", {}) is True

    def test_zero_falsy(self) -> None:
        assert evaluate_condition("0", {}) is False

    def test_string_truthy(self) -> None:
        assert evaluate_condition('"hello"', {}) is True

    def test_empty_string_falsy(self) -> None:
        assert evaluate_condition('""', {}) is False


class TestNames:
    def test_truthy_name(self) -> None:
        assert evaluate_condition("foo", {"foo": "bar"}) is True

    def test_falsy_name(self) -> None:
        assert evaluate_condition("foo", {"foo": ""}) is False

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ConditionError, match="unknown name"):
            evaluate_condition("missing", {})


class TestComparisons:
    def test_equality(self) -> None:
        assert evaluate_condition('status == "ok"', {"status": "ok"}) is True
        assert evaluate_condition('status == "ok"', {"status": "fail"}) is False

    def test_inequality(self) -> None:
        assert evaluate_condition("count != 0", {"count": 5}) is True

    def test_greater_than(self) -> None:
        assert evaluate_condition("score > 80", {"score": 90}) is True
        assert evaluate_condition("score > 80", {"score": 70}) is False

    def test_chained_comparison(self) -> None:
        assert evaluate_condition("0 < x < 10", {"x": 5}) is True
        assert evaluate_condition("0 < x < 10", {"x": 15}) is False


class TestBooleanOps:
    def test_and(self) -> None:
        assert evaluate_condition("a and b", {"a": True, "b": True}) is True
        assert evaluate_condition("a and b", {"a": True, "b": False}) is False

    def test_or(self) -> None:
        assert evaluate_condition("a or b", {"a": False, "b": True}) is True

    def test_not(self) -> None:
        assert evaluate_condition("not a", {"a": False}) is True


class TestMembership:
    def test_in_dict(self) -> None:
        assert evaluate_condition('"k" in d', {"d": {"k": 1}}) is True

    def test_in_list(self) -> None:
        assert evaluate_condition('"x" in items', {"items": ["x", "y"]}) is True

    def test_in_string(self) -> None:
        assert evaluate_condition('"foo" in s', {"s": "barfoobaz"}) is True


class TestAccess:
    def test_attribute_access_on_dict_truthy(self) -> None:
        # evaluate_condition coerces the resolved value to bool.
        assert evaluate_condition("user.name", {"user": {"name": "Alice"}}) is True

    def test_subscript_on_dict_truthy(self) -> None:
        assert evaluate_condition('user["name"]', {"user": {"name": "Bob"}}) is True

    def test_attribute_access_falsy_when_missing(self) -> None:
        # Missing keys silently return None → falsy.
        assert evaluate_condition("user.missing", {"user": {}}) is False

    def test_nested_access(self) -> None:
        ctx = {"data": {"result": {"value": 42}}}
        assert evaluate_condition("data.result.value > 40", ctx) is True

    def test_nested_access_with_string_compare(self) -> None:
        ctx = {"step": {"label": "spam"}}
        assert evaluate_condition('step.label == "spam"', ctx) is True
        assert evaluate_condition('step.label == "ham"', ctx) is False


class TestEmpty:
    def test_empty_string_returns_true(self) -> None:
        # Backwards compatibility: empty condition = follow always.
        assert evaluate_condition("", {}) is True

    def test_whitespace_returns_true(self) -> None:
        assert evaluate_condition("   ", {}) is True


class TestUnsupported:
    def test_function_call_rejected(self) -> None:
        with pytest.raises(ConditionError):
            evaluate_condition("len(x)", {"x": [1, 2]})

    def test_walrus_rejected(self) -> None:
        with pytest.raises(ConditionError):
            evaluate_condition("(y := 1) > 0", {})

    def test_lambda_rejected(self) -> None:
        with pytest.raises(ConditionError):
            evaluate_condition("(lambda: 1)()", {})

    def test_attr_on_non_dict_rejected(self) -> None:
        with pytest.raises(ConditionError):
            evaluate_condition("x.attr", {"x": object()})


class TestSyntaxErrors:
    def test_invalid_syntax(self) -> None:
        with pytest.raises(ConditionError, match="syntax"):
            evaluate_condition("not a +", {})


class TestRealisticUsage:
    def test_skill_output_dispatch(self) -> None:
        ctx = {"classify": {"label": "spam", "confidence": 0.95}}
        assert evaluate_condition('classify.label == "spam"', ctx) is True
        assert evaluate_condition("classify.confidence > 0.9", ctx) is True

    def test_failure_branching(self) -> None:
        ctx = {"step1": {"status": "ok"}, "step2": {"status": "error"}}
        assert evaluate_condition('step1.status == "ok"', ctx) is True
        assert evaluate_condition('step2.status == "ok"', ctx) is False
