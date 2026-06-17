"""Tests for app.infrastructure.excel.text_to_pandas."""
from __future__ import annotations

import pytest
import pandas as pd

from app.infrastructure.excel.text_to_pandas import (
    _validate_generated_code,
    _safe_exec_pandas,
    SAFE_BUILTINS,
    MAX_CODE_LENGTH,
)


class TestValidateGeneratedCode:
    def test_empty_code_returns_error(self):
        assert _validate_generated_code("") == "empty code"

    def test_whitespace_only_returns_error(self):
        assert _validate_generated_code("   ") == "empty code"

    def test_none_code_returns_error(self):
        assert _validate_generated_code(None) == "empty code"

    def test_code_exceeds_max_length(self):
        long_code = "x = 1\n" * (MAX_CODE_LENGTH // 5)
        result = _validate_generated_code(long_code)
        assert result is not None
        assert "exceeds maximum length" in result

    def test_syntax_error_returns_error(self):
        result = _validate_generated_code("def (")
        assert result is not None
        assert "syntax error" in result

    def test_private_attribute_access_forbidden(self):
        result = _validate_generated_code("x._secret")
        assert result is not None
        assert "private attribute" in result

    def test_import_statement_forbidden(self):
        result = _validate_generated_code("import os")
        assert result is not None
        assert "import" in result.lower()

    def test_from_import_forbidden(self):
        result = _validate_generated_code("from os import path")
        assert result is not None
        assert "import" in result.lower()

    def test_valid_simple_code_passes(self):
        code = "result = df.head()"
        assert _validate_generated_code(code) is None

    def test_valid_assignment_passes(self):
        code = "x = 1\nresult = df"
        assert _validate_generated_code(code) is None

    def test_valid_if_else_passes(self):
        code = "if True:\n    result = df\nelse:\n    result = df.head()"
        assert _validate_generated_code(code) is None

    def test_valid_for_loop_passes(self):
        code = "for i in range(10):\n    pass\nresult = df"
        assert _validate_generated_code(code) is None

    def test_valid_list_comprehension_passes(self):
        code = "result = [x for x in range(5)]"
        assert _validate_generated_code(code) is None


class TestSafeExecPandas:
    def test_validation_failure_raises_value_error(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        with pytest.raises(ValueError, match="code validation failed"):
            _safe_exec_pandas("import os", df)

    def test_simple_filter_returns_dataframe(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        result = _safe_exec_pandas("result = df[df['a'] > 2]", df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3

    def test_result_series_converted_to_dataframe(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = _safe_exec_pandas("result = df['a']", df)
        assert isinstance(result, pd.DataFrame)

    def test_no_result_returns_empty_dataframe(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = _safe_exec_pandas("x = 1", df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_original_df_not_mutated(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        original = df.copy()
        _safe_exec_pandas("df['b'] = 4", df)
        pd.testing.assert_frame_equal(df, original)

    def test_safe_builtins_available(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = _safe_exec_pandas("result = len(df)", df)
        # len returns int, not DataFrame, so we get empty df
        assert isinstance(result, pd.DataFrame)

    def test_result_dataframe_with_columns(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        result = _safe_exec_pandas("result = df[['a']]", df)
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["a"]
