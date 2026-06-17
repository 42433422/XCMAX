"""app/domain/approval/safe_dsl 单测：AST 安全求值器。

纯逻辑、无外部边界（铁律4）。覆盖空值/合法表达式/各运算符/越权变量/
非白名单节点/除零/便捷函数与 should_trigger_condition 的 fail-closed（铁律3）。
"""

from __future__ import annotations

import pytest

from app.domain.approval.safe_dsl import (
    SafeEvaluationError,
    SafeExpressionEvaluator,
    evaluate_condition,
    should_trigger_condition,
)


class TestEmptyAndNonString:
    def test_none_passes(self):
        assert SafeExpressionEvaluator({}).evaluate(None) is True  # type: ignore[arg-type]

    def test_empty_string_passes(self):
        assert SafeExpressionEvaluator({}).evaluate("") is True

    def test_whitespace_passes(self):
        assert SafeExpressionEvaluator({}).evaluate("   ") is True

    def test_non_string_passes(self):
        assert SafeExpressionEvaluator({}).evaluate(123) is True  # type: ignore[arg-type]


class TestComparisons:
    def test_gt_true(self):
        assert evaluate_condition("amount > 50000", {"amount": 60000}) is True

    def test_gt_false(self):
        assert evaluate_condition("amount > 50000", {"amount": 100}) is False

    def test_string_equality(self):
        assert evaluate_condition("department == 'sales'", {"department": "sales"}) is True
        assert evaluate_condition("department == 'sales'", {"department": "ops"}) is False

    def test_chained_comparison(self):
        assert evaluate_condition("1 < amount < 100", {"amount": 50}) is True
        assert evaluate_condition("1 < amount < 100", {"amount": 500}) is False

    def test_lte_gte_neq(self):
        assert evaluate_condition("amount <= 10", {"amount": 10}) is True
        assert evaluate_condition("amount >= 10", {"amount": 10}) is True
        assert evaluate_condition("amount != 10", {"amount": 11}) is True


class TestBooleanAndUnary:
    def test_and(self):
        ctx = {"amount": 6000, "department": "sales"}
        assert evaluate_condition("amount > 5000 and department == 'sales'", ctx) is True

    def test_or(self):
        assert (
            evaluate_condition(
                "priority == 'high' or amount > 10000", {"priority": "high", "amount": 0}
            )
            is True
        )

    def test_not(self):
        assert evaluate_condition("not (amount > 100)", {"amount": 5}) is True


class TestArithmetic:
    def test_add(self):
        assert evaluate_condition("amount + 10 > 50", {"amount": 45}) is True

    def test_sub_mult_div_mod_pow(self):
        assert evaluate_condition("amount - 5 == 5", {"amount": 10}) is True
        assert evaluate_condition("amount * 2 == 20", {"amount": 10}) is True
        assert evaluate_condition("amount / 2 == 5", {"amount": 10}) is True
        assert evaluate_condition("amount % 3 == 1", {"amount": 10}) is True
        assert evaluate_condition("amount ** 2 == 100", {"amount": 10}) is True


class TestLiterals:
    def test_true_false_null_names(self):
        assert SafeExpressionEvaluator({}).evaluate("true") is True
        assert SafeExpressionEvaluator({}).evaluate("false") is False
        assert SafeExpressionEvaluator({}).evaluate("null") is False


class TestContextVariables:
    def test_context_var_outside_allowlist(self):
        assert evaluate_condition("custom_field > 1", {"custom_field": 5}) is True


class TestUnsafeRejected:
    def test_disallowed_variable(self):
        with pytest.raises(SafeEvaluationError):
            evaluate_condition("os > 1", {})

    def test_disallowed_node_function_call(self):
        with pytest.raises(SafeEvaluationError):
            evaluate_condition("len(amount) > 1", {"amount": 5})

    def test_division_by_zero(self):
        with pytest.raises(SafeEvaluationError):
            evaluate_condition("amount / 0 > 1", {"amount": 5})


class TestShouldTriggerCondition:
    def test_node_without_condition_attr(self):
        class Node:
            id = "n1"

        assert should_trigger_condition(Node(), {}) is True

    def test_node_with_empty_condition(self):
        class Node:
            id = "n2"
            condition_expression = ""

        assert should_trigger_condition(Node(), {}) is True

    def test_node_with_truthy_condition(self):
        class Node:
            id = "n3"
            condition_expression = "amount > 100"

        assert should_trigger_condition(Node(), {"amount": 200}) is True
        assert should_trigger_condition(Node(), {"amount": 1}) is False

    def test_fail_closed_on_unsafe(self):
        class Node:
            id = "n4"
            condition_expression = "os > 1"

        assert should_trigger_condition(Node(), {}) is False
