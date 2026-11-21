"""The legacy executor names now accept only validated, read-only query plans."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.infrastructure.excel.text_to_pandas import (
    MAX_CODE_LENGTH,
    _safe_exec_pandas,
    _validate_generated_code,
)


@pytest.mark.parametrize("value", ["", "   ", None])
def test_empty_plan_is_rejected(value):
    assert _validate_generated_code(value) == "empty query plan"


def test_plan_length_is_bounded():
    assert "maximum length" in _validate_generated_code("x" * (MAX_CODE_LENGTH + 1))


@pytest.mark.parametrize(
    "code",
    [
        "def (",
        "x._secret",
        "import os",
        "from os import path",
        "result = df.head()",
        "x = 1\nresult = df",
        "if True:\n    result = df\nelse:\n    result = df.head()",
        "for i in range(10):\n    pass\nresult = df",
        "result = [x for x in range(5)]",
    ],
)
def test_all_python_constructs_are_rejected(code):
    assert "JSON, not Python" in _validate_generated_code(code)
    with pytest.raises(ValueError, match="JSON, not Python"):
        _safe_exec_pandas(code, pd.DataFrame({"a": [1]}))


@pytest.mark.parametrize(
    "plan",
    [
        {"code": "result = df"},
        {"limit": -1},
        {"limit": True},
        {"limit": 5001},
        {"columns": "a"},
        {"columns": ["a", "a"]},
        {"metrics": [{"column": "a", "op": "to_csv"}]},
        {"conversions": [{"column": "a", "kind": "eval"}]},
        {"query_expression": None},
        [],
        1,
    ],
)
def test_complete_plan_schema_is_checked_at_execution(plan):
    code = json.dumps(plan)
    assert _validate_generated_code(code)
    with pytest.raises(ValueError, match="invalid query plan"):
        _safe_exec_pandas(code, pd.DataFrame({"a": [1]}))


def test_simple_filter_returns_dataframe():
    result = _safe_exec_pandas(
        '{"query_expression": "c0 > 2"}', pd.DataFrame({"a": [1, 2, 3, 4, 5]})
    )
    assert result.to_dict(orient="records") == [{"a": 3}, {"a": 4}, {"a": 5}]


def test_projection_preserves_dataframe_contract():
    result = _safe_exec_pandas('{"columns": ["a"]}', pd.DataFrame({"a": [1], "b": [2]}))
    assert isinstance(result, pd.DataFrame)
    assert result.to_dict(orient="records") == [{"a": 1}]


def test_zero_limit_returns_empty_frame_with_source_columns():
    result = _safe_exec_pandas('{"limit": 0}', pd.DataFrame({"a": [1]}))
    assert result.empty and list(result.columns) == ["a"]


def test_explicit_conversion_does_not_mutate_original_frame():
    frame = pd.DataFrame({"金额": ["￥1,000元", "25"]})
    original = frame.copy()
    result = _safe_exec_pandas('{"conversions": [{"column": "金额", "kind": "number"}]}', frame)
    assert result["金额"].tolist() == [1000, 25]
    pd.testing.assert_frame_equal(frame, original)


def test_safe_count_replaces_python_builtin_execution():
    result = _safe_exec_pandas(
        '{"metrics": [{"column": "a", "op": "count"}]}', pd.DataFrame({"a": [1, 2, 3]})
    )
    assert result.to_dict(orient="records") == [{"a_count": 3}]
