"""Tests for app.infrastructure.excel.text_to_pandas."""
from __future__ import annotations

import pytest
import pandas as pd

from app.infrastructure.excel.text_to_pandas import (
    MAX_CODE_LENGTH,
    _safe_exec_pandas,
    _validate_generated_code,
)


class TestValidateGeneratedCode:
    """Tests for _validate_generated_code."""

    def test_empty_code(self) -> None:
        assert _validate_generated_code("") == "empty code"

    def test_whitespace_only_code(self) -> None:
        assert _validate_generated_code("   \n  ") == "empty code"

    def test_none_code(self) -> None:
        assert _validate_generated_code(None) == "empty code"

    def test_code_exceeds_max_length(self) -> None:
        long_code = "x = 1\n" * (MAX_CODE_LENGTH // 5 + 1)
        result = _validate_generated_code(long_code)
        assert "exceeds maximum length" in result

    def test_syntax_error(self) -> None:
        result = _validate_generated_code("def (")
        assert "syntax error" in result

    def test_access_to_private_attribute(self) -> None:
        result = _validate_generated_code("obj._secret")
        assert "private attribute" in result

    def test_import_statement_forbidden(self) -> None:
        result = _validate_generated_code("import os")
        assert "import" in result and "forbidden" in result

    def test_from_import_forbidden(self) -> None:
        result = _validate_generated_code("from os import path")
        assert "import" in result and "forbidden" in result

    def test_valid_simple_code(self) -> None:
        code = "result = df.head()"
        assert _validate_generated_code(code) is None

    def test_valid_code_with_if(self) -> None:
        code = "if len(df) > 0:\n    result = df"
        assert _validate_generated_code(code) is None

    def test_valid_code_with_for_loop(self) -> None:
        code = "for col in df.columns:\n    pass"
        assert _validate_generated_code(code) is None

    def test_valid_code_with_list_comp(self) -> None:
        code = "result = [x for x in range(10)]"
        assert _validate_generated_code(code) is None

    def test_valid_code_with_dict(self) -> None:
        code = 'result = {"key": "value"}'
        assert _validate_generated_code(code) is None


class TestSafeExecPandas:
    """Tests for _safe_exec_pandas."""

    def test_invalid_code_raises_value_error(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        with pytest.raises(ValueError, match="code validation failed"):
            _safe_exec_pandas("import os", df)

    def test_returns_dataframe_result(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        code = "result = df[df['a'] > 1]"
        result = _safe_exec_pandas(code, df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2

    def test_returns_series_as_dataframe(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        code = "result = df['a']"
        result = _safe_exec_pandas(code, df)
        assert isinstance(result, pd.DataFrame)

    def test_returns_empty_df_when_no_result(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        code = "x = 5"
        result = _safe_exec_pandas(code, df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_does_not_mutate_original_df(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        code = "df['b'] = 4"
        _safe_exec_pandas(code, df)
        assert "b" not in df.columns

    def test_can_use_safe_builtins(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        code = "result = len(df)"
        # len returns int, not DataFrame, so result should be empty df
        result = _safe_exec_pandas(code, df)
        assert isinstance(result, pd.DataFrame)

    def test_aggregation_returns_dataframe(self) -> None:
        df = pd.DataFrame({"group": ["a", "a", "b"], "val": [1, 2, 3]})
        code = "result = df.groupby('group').sum()"
        result = _safe_exec_pandas(code, df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
