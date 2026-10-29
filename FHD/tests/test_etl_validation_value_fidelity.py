"""A07: legitimate false values are data, not missing values."""
from decimal import Decimal

import pytest

from app.application.etl.service_support import apply_validation_rules


@pytest.mark.parametrize("value", [0, False, Decimal("0"), 0.0, "0", "False", "中文"])
def test_false_values_preserve_their_text_length(value):
    size = len(str(value))
    assert apply_validation_rules(
        {"value": value},
        [
            {"field": "value", "op": "min_length", "value": size},
            {"field": "value", "op": "max_length", "value": size},
        ],
    ) == []
    assert len(apply_validation_rules(
        {"value": value}, [{"field": "value", "op": "max_length", "value": size - 1}]
    )) == 1


@pytest.mark.parametrize("data", [{}, {"value": None}, {"value": ""}])
def test_missing_and_empty_values_keep_empty_length(data):
    assert apply_validation_rules(data, [{"field": "value", "op": "max_length", "value": 0}]) == []
    assert len(apply_validation_rules(data, [{"field": "value", "op": "min_length", "value": 1}])) == 1
