"""Regression cases for audit items 1-5; real modules, no external services."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.application.etl.transforms import apply_mapping, apply_transform
from app.domain.approval.safe_dsl import (
    SafeEvaluationError,
    evaluate_condition,
    should_trigger_condition,
)


@pytest.mark.parametrize(
    "value,expected",
    [(0, "0"), (False, "False"), (True, "True"), (None, ""), ("", ""),
     (0.0, "0.0"), (Decimal("0.00"), "0.00"), ("0", "0"), ("中文", "中文")],
)
def test_text_transforms_preserve_falsy_values(value, expected):
    row = {"prefix": "SKU", "value": value}
    assert apply_transform(value, {"op": "split"}, row) == expected
    rule = {"op": "concat", "fields": ["prefix", "value"], "separator": "/"}
    assert apply_transform(None, rule, row) == f"SKU/{expected}"
    assert row == {"prefix": "SKU", "value": value}


def test_concat_missing_fields_remain_empty():
    rule = {"op": "concat", "fields": ["missing", "zero", "none"], "separator": "/"}
    assert apply_transform(None, rule, {"zero": 0, "none": None}) == "/0/"


@pytest.mark.parametrize("index,expected", [(0, "0"), (1, "False"), (-1, "False"), (2, "")])
def test_split_indices_are_compatible(index, expected):
    assert apply_transform("0,False", {"op": "split", "index": index}, {}) == expected


def test_mapping_chain_preserves_zero_and_false():
    source = {"raw_zero": 0, "flag": False}
    mappings = [
        {"source": "raw_zero", "target": "code", "transforms": [{"op": "split"}]},
        {"target": "label", "transforms": [
            {"op": "concat", "fields": ["code", "flag"], "separator": "/"}
        ]},
    ]
    assert apply_mapping(source, mappings) == {"code": "0", "label": "0/False"}
    assert source == {"raw_zero": 0, "flag": False}


@pytest.mark.parametrize(
    "expression,expected",
    [("True or 1 / 0", True), ("False and 1 / 0", False),
     ("False or True or 1 / 0", True), ("True and False and 1 / 0", False),
     ("True OR 1 / 0", True), ("False AND 1 / 0", False),
     ("False AND amount > 1", False), ("True OR amount > 1", True)],
)
def test_boolean_short_circuit(expression, expected):
    assert evaluate_condition(expression, {}) is expected


@pytest.mark.parametrize("expression", ["True and 1 / 0", "False or 1 / 0"])
def test_required_boolean_operand_still_executes(expression):
    with pytest.raises(SafeEvaluationError):
        evaluate_condition(expression, {})


@pytest.mark.parametrize("expression", [
    'True or __import__("os")', "False and amount.__class__", "True OR [1, 2]",
    "False AND (amount := 1)", "True or untrusted_name", "False and open('file')",
])
def test_short_circuit_does_not_bypass_ast_validation(expression):
    with pytest.raises(SafeEvaluationError):
        evaluate_condition(expression, {"amount": 0})


@pytest.mark.parametrize("expression,context", [
    ("amount > 50000", {"amount": 60000}),
    ("quantity > 100 AND unit_price > 10.0", {"quantity": 101, "unit_price": 11}),
    ("priority = 'high' OR amount > 10000", {"priority": "high", "amount": 0}),
    ("(amount > 5000 AND department = 'sales')", {"amount": 5001, "department": "sales"}),
    ("amount > 50000 AND priority = 'high'", {"amount": 60000, "priority": "high"}),
    ("NOT (amount < 0) AND amount >= +0", {"amount": 0}),
    ("amount > -1", {"amount": 0}), ("amount = -1.5", {"amount": -1.5}),
    ("amount - -1 = +1", {"amount": 0}),
])
def test_documented_syntax_and_signed_numbers(expression, context):
    assert evaluate_condition(expression, context) is True


@pytest.mark.parametrize("value", ["AND", "OR = NOT", "a >= b", "A AND B = C", "quote' AND x"])
def test_operator_normalization_preserves_quoted_strings(value):
    assert evaluate_condition(f"department = {value!r}", {"department": value}) is True


@pytest.mark.parametrize("expression", ["amount =", "(amount > 1", "amount === 1", "amount > 'bad"])
def test_invalid_syntax_is_a_domain_error_and_fails_closed(expression):
    with pytest.raises(SafeEvaluationError):
        evaluate_condition(expression, {"amount": 0})
    node = SimpleNamespace(id="audit-syntax", condition_expression=expression)
    assert should_trigger_condition(node, {"amount": 0}) is False
