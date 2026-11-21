"""Query plans retain filtering, grouping and error contracts without Python execution."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.infrastructure.excel.text_to_pandas import _safe_exec_pandas, _validate_generated_code


@pytest.mark.parametrize(
    "code",
    [
        "obj._secret",
        "for col in df.columns:\n    pass",
        'result = {"key": "value"}',
        "result = len(df)",
    ],
)
def test_legacy_python_is_not_an_execution_fallback(code):
    assert _validate_generated_code(code)
    with pytest.raises(ValueError):
        _safe_exec_pandas(code, pd.DataFrame({"a": [1]}))


@pytest.mark.parametrize(
    "plan",
    [{}, {"limit": 5}, {"query_expression": "c0 > 1"}, {"columns": ["a"]}],
)
def test_valid_plans_pass_schema_validation(plan):
    assert _validate_generated_code(json.dumps(plan)) is None


def test_returns_filtered_dataframe():
    result = _safe_exec_pandas('{"query_expression": "c0 > 1"}', pd.DataFrame({"a": [1, 2, 3]}))
    assert result["a"].tolist() == [2, 3]


def test_returns_all_rows_for_empty_plan():
    frame = pd.DataFrame({"a": [1, 2, 3]})
    pd.testing.assert_frame_equal(_safe_exec_pandas("{}", frame), frame)


def test_aggregation_returns_expected_groups():
    frame = pd.DataFrame({"group": ["a", "a", "b"], "val": [1, 2, 3]})
    plan = {"group_by": ["group"], "metrics": [{"column": "val", "op": "sum"}]}
    result = _safe_exec_pandas(json.dumps(plan), frame)
    assert result.to_dict(orient="records") == [
        {"group": "a", "val_sum": 3},
        {"group": "b", "val_sum": 3},
    ]


def test_aliases_cover_labels_that_are_not_python_identifiers():
    frame = pd.DataFrame({"购货金额（元）": [1, 2, 3]})
    result = _safe_exec_pandas(
        '{"query_expression": "c0 >= 2", "sort_by": ["购货金额（元）"], "ascending": false, "limit": 1}',
        frame,
    )
    assert result.to_dict(orient="records") == [{"购货金额（元）": 3}]


@pytest.mark.parametrize(
    "plan",
    [
        {"query_expression": "missing > 1"},
        {"columns": ["missing"]},
        {"sort_by": ["missing"]},
        {"conversions": [{"column": "missing", "kind": "date"}]},
        {"group_by": ["a"]},
        {"unsupported_reason": "requires arbitrary Python"},
    ],
)
def test_unsupported_operations_fail_without_returning_false_success(plan):
    with pytest.raises(ValueError):
        _safe_exec_pandas(json.dumps(plan), pd.DataFrame({"a": [1]}))


def test_schema_integer_floats_are_normalized_before_pandas_and_datetime():
    plan = {
        "limit": 1.0,
        "conversions": [{"column": "日期", "kind": "date", "default_year": 2026.0}],
    }
    result = _safe_exec_pandas(json.dumps(plan), pd.DataFrame({"日期": ["2月", "3月"]}))
    assert result["日期"].tolist() == [pd.Timestamp("2026-02-01")]
