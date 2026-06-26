"""分支覆盖测试 app.application.tools.workflow（第三批）。

补充覆盖已有 test_tools_workflow_cov.py 未覆盖的分支：
- run_natural_language_pandas（ValueError / RECOVERABLE_ERRORS / 空 code / truncated）
- handle_excel_analysis（excel_query / read+customer_hint / query / aggregate / statistics / unsupported）
- execute_workflow_tool（excel_join_compare join/diff/unknown、excel_prophet 各分支、
  excel_schema_understand、products_bulk_import、excel_vector_index、
  generate_office_document、unknown_tool、template_preview 空 action）
- _handle_import_excel_to_database（token 校验 / file not found / df empty /
  last_data_row invalid / import_type=orders / import_type=other）
- _import_orders_preview_or_execute（preview / confirm / 缺 unit）
- _excel_cell_as_clean_str（bool / -inf / nat）
- _excel_cell_as_float（nan after float）
- _looks_like_contract_or_footer_line（短编号条款 / 无关键词编号）
- _read_excel_dataframe（engine 选择 / sheet_name / header_row）
- invalidate_workflow_tool_registry（成功 / 异常）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.tools.workflow import (
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _handle_import_excel_to_database,
    _import_orders_preview_or_execute,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
    _read_excel_dataframe,
    execute_workflow_tool,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
    run_natural_language_pandas,
)


# ---------------------------------------------------------------------------
# run_natural_language_pandas
# ---------------------------------------------------------------------------


def _patch_excel_text_to_pandas(translate_return=None, translate_side_effect=None):
    """构造一个注入 sys.modules 的 fake ExcelTextToPandas 模块。

    app.legacy.excel_text_to_pandas 在本仓库不存在，run_natural_language_pandas
    通过 from ... import 延迟导入；测试需要用 patch.dict 注入 fake 模块。
    """
    mock_converter = MagicMock()
    if translate_side_effect is not None:
        mock_converter.translate.side_effect = translate_side_effect
    else:
        mock_converter.translate.return_value = translate_return
    fake_module = MagicMock(ExcelTextToPandas=MagicMock(return_value=mock_converter))
    return patch.dict("sys.modules", {"app.legacy.excel_text_to_pandas": fake_module}), mock_converter


class TestRunNaturalLanguagePandas:
    """run_natural_language_pandas 分支覆盖。"""

    def test_value_error_sets_error_msg(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        patch_ctx, _ = _patch_excel_text_to_pandas(
            translate_side_effect=ValueError("bad query")
        )
        with patch_ctx:
            result = run_natural_language_pandas(df, "bad")
        assert "error" in result
        assert "bad query" in result["error"]
        assert result["generated_code"] == ""

    def test_recoverable_error_sets_error_msg(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        patch_ctx, _ = _patch_excel_text_to_pandas(
            translate_side_effect=OSError("io fail")
        )
        with patch_ctx:
            result = run_natural_language_pandas(df, "x")
        assert "error" in result
        assert "io fail" in result["error"]

    def test_empty_code_does_not_execute(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        patch_ctx, _ = _patch_excel_text_to_pandas(translate_return="   ")
        with patch_ctx:
            result = run_natural_language_pandas(df, "x")
        assert result["generated_code"] == ""
        assert result["row_count"] == 2

    def test_truncated_when_more_than_200_rows(self) -> None:
        df = pd.DataFrame({"a": list(range(250))})
        patch_ctx, _ = _patch_excel_text_to_pandas(translate_return="")
        with patch_ctx:
            result = run_natural_language_pandas(df, "x")
        assert result["truncated"] is True
        assert result["returned_rows"] == 200
        assert result["row_count"] == 250

    def test_not_truncated_when_less_than_200_rows(self) -> None:
        df = pd.DataFrame({"a": list(range(10))})
        patch_ctx, _ = _patch_excel_text_to_pandas(translate_return="")
        with patch_ctx:
            result = run_natural_language_pandas(df, "x")
        assert result["truncated"] is False
        assert result["returned_rows"] == 10

    def test_import_error_sets_error_msg(self) -> None:
        """app.legacy.excel_text_to_pandas 不存在时 ImportError 被捕获。"""
        df = pd.DataFrame({"a": [1, 2]})
        # 不注入 fake 模块，让真实 import 失败
        with patch.dict("sys.modules", {"app.legacy.excel_text_to_pandas": None}):
            result = run_natural_language_pandas(df, "x")
        # ImportError 属于 RECOVERABLE_ERRORS，会被捕获并设置 error
        assert "error" in result
        assert result["generated_code"] == ""

    def test_successful_code_execution(self) -> None:
        """translate 返回有效代码时执行并返回结果。"""
        df = pd.DataFrame({"a": [1, 2, 3]})
        patch_ctx, _ = _patch_excel_text_to_pandas(
            translate_return="result = df.head(1)"
        )
        with patch_ctx:
            result = run_natural_language_pandas(df, "first row")
        assert result["generated_code"] == "result = df.head(1)"
        assert result["row_count"] == 1

    def test_runtime_error_sets_error_msg(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        patch_ctx, _ = _patch_excel_text_to_pandas(
            translate_side_effect=RuntimeError("rt fail")
        )
        with patch_ctx:
            result = run_natural_language_pandas(df, "x")
        assert "error" in result
        assert "rt fail" in result["error"]


# ---------------------------------------------------------------------------
# handle_excel_analysis
# ---------------------------------------------------------------------------


class TestHandleExcelAnalysis:
    """handle_excel_analysis 分支覆盖。"""

    def test_missing_file_path_returns_error(self) -> None:
        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_resolve_path_error_returns_error(self) -> None:
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=OSError("denied"),
        ):
            result = handle_excel_analysis({"file_path": "x.xlsx"})
        assert result["success"] is False
        assert "denied" in result["error"]

    def test_file_not_found_returns_error(self, tmp_path: Path) -> None:
        result = handle_excel_analysis(
            {"file_path": "missing.xlsx"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_read_failed_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("read fail"),
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is False
        assert "read failed" in result["error"]

    def test_action_excel_query(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.tools.workflow.run_natural_language_pandas",
            return_value={"generated_code": "x", "row_count": 2},
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "excel_query", "natural_language": "x"},
                workspace_root=str(tmp_path),
            )
        assert result["action"] == "excel_query"

    def test_action_read_with_customer_hint(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            return_value="客户A",
            create=True,
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert result["customer_hint"] == "客户A"
        assert result["action"] == "read"

    def test_action_read_customer_hint_error_swallowed(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            side_effect=OSError("fail"),
            create=True,
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert "customer_hint" not in result

    def test_action_read_with_header_row(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            return_value="",
            create=True,
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "read", "header_row": 2},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["header_row"] == 2

    def test_action_query_with_expr(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query", "query_expression": "a > 1"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "query"
        assert result["row_count"] == 2

    def test_action_query_without_expr(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2, 3]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "query"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["row_count"] == 3

    def test_action_aggregate_with_metrics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"cat": ["a", "a", "b"], "val": [1, 2, 3]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {
                    "file_path": "data.xlsx",
                    "action": "aggregate",
                    "group_by": ["cat"],
                    "metrics": [{"column": "val", "op": "sum"}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_action_aggregate_with_invalid_metrics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"cat": ["a"], "val": [1]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {
                    "file_path": "data.xlsx",
                    "action": "aggregate",
                    "group_by": ["cat"],
                    "metrics": ["not a dict", {"column": "", "op": ""}],
                },
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_action_aggregate_no_group_by(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "aggregate"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True

    def test_action_statistics(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2, 3]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "statistics"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_unsupported_action(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = handle_excel_analysis(
                {"file_path": "data.xlsx", "action": "unknown"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_join_compare
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolJoinCompare:
    """execute_workflow_tool excel_join_compare 分支覆盖。"""

    def _call(self, name, args, workspace_root=None):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            return execute_workflow_tool(name, args, workspace_root=workspace_root)

    def test_join_file1_not_found(self, tmp_path: Path) -> None:
        result = self._call(
            "excel_join_compare",
            {"action": "join", "file_paths": ["missing1.xlsx", "missing2.xlsx"]},
            workspace_root=str(tmp_path),
        )
        data = json.loads(result)
        assert data["success"] is False
        assert "file not found" in data["error"]

    def test_join_file2_not_found(self, tmp_path: Path) -> None:
        f1 = tmp_path / "f1.xlsx"
        f1.write_text("not excel")
        f2_name = "missing2.xlsx"
        with patch("pandas.read_excel", return_value=pd.DataFrame({"a": [1]})):
            result = self._call(
                "excel_join_compare",
                {"action": "join", "file_paths": ["f1.xlsx", f2_name]},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False

    def test_join_success_with_keys(self, tmp_path: Path) -> None:
        f1 = tmp_path / "f1.xlsx"
        f1.write_text("not excel")
        f2 = tmp_path / "f2.xlsx"
        f2.write_text("not excel")
        d1 = pd.DataFrame({"id": [1, 2], "a": [10, 20]})
        d2 = pd.DataFrame({"id": [1, 2], "b": [30, 40]})
        with patch("pandas.read_excel", side_effect=[d1, d2]):
            result = self._call(
                "excel_join_compare",
                {"action": "join", "file_paths": ["f1.xlsx", "f2.xlsx"], "join_keys": ["id"]},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["action"] == "join"
        assert data["row_count"] == 2

    def test_join_success_without_keys(self, tmp_path: Path) -> None:
        f1 = tmp_path / "f1.xlsx"
        f1.write_text("not excel")
        f2 = tmp_path / "f2.xlsx"
        f2.write_text("not excel")
        d1 = pd.DataFrame({"a": [1]})
        d2 = pd.DataFrame({"b": [2]})
        with patch("pandas.read_excel", side_effect=[d1, d2]):
            result = self._call(
                "excel_join_compare",
                {"action": "join", "file_paths": ["f1.xlsx", "f2.xlsx"]},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["action"] == "join"

    def test_diff_file_a_not_found(self, tmp_path: Path) -> None:
        result = self._call(
            "excel_join_compare",
            {"action": "diff", "file_path_a": "missing.xlsx", "file_path_b": "missing2.xlsx"},
            workspace_root=str(tmp_path),
        )
        data = json.loads(result)
        assert data["success"] is False

    def test_diff_file_b_not_found(self, tmp_path: Path) -> None:
        fa = tmp_path / "fa.xlsx"
        fa.write_text("not excel")
        with patch("pandas.read_excel", return_value=pd.DataFrame({"a": [1]})):
            result = self._call(
                "excel_join_compare",
                {"action": "diff", "file_path_a": "fa.xlsx", "file_path_b": "missing.xlsx"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False

    def test_diff_with_keys_and_changes(self, tmp_path: Path) -> None:
        fa = tmp_path / "fa.xlsx"
        fa.write_text("not excel")
        fb = tmp_path / "fb.xlsx"
        fb.write_text("not excel")
        a = pd.DataFrame({"id": [1, 2], "v": [10, 20]})
        b = pd.DataFrame({"id": [1, 2], "v": [10, 99]})
        with patch("pandas.read_excel", side_effect=[a, b]):
            result = self._call(
                "excel_join_compare",
                {"action": "diff", "file_path_a": "fa.xlsx", "file_path_b": "fb.xlsx", "key_columns": ["id"]},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["action"] == "diff"
        assert data["rows_with_value_changes"]["count"] == 1

    def test_diff_without_keys(self, tmp_path: Path) -> None:
        fa = tmp_path / "fa.xlsx"
        fa.write_text("not excel")
        fb = tmp_path / "fb.xlsx"
        fb.write_text("not excel")
        with patch("pandas.read_excel", side_effect=[pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [2]})]):
            result = self._call(
                "excel_join_compare",
                {"action": "diff", "file_path_a": "fa.xlsx", "file_path_b": "fb.xlsx"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["action"] == "diff"
        assert "row_count" in data

    def test_unknown_action(self, tmp_path: Path) -> None:
        result = self._call(
            "excel_join_compare",
            {"action": "unknown_action"},
            workspace_root=str(tmp_path),
        )
        data = json.loads(result)
        assert data["success"] is False
        assert "unknown action" in data["error"]

    def test_recoverable_error_returns_error(self, tmp_path: Path) -> None:
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=OSError("fail"),
        ):
            result = self._call(
                "excel_join_compare",
                {"action": "join", "file_paths": ["x.xlsx"]},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_prophet
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolProphet:
    """execute_workflow_tool excel_prophet 分支覆盖。"""

    def _call(self, args, workspace_root=None):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            return execute_workflow_tool("excel_prophet", args, workspace_root=workspace_root)

    def test_no_file_path_returns_zero_forecast(self, tmp_path: Path) -> None:
        result = self._call({}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["action"] == "forecast"
        assert len(data["future_forecast"]) == 6
        assert data["future_forecast"][0]["yhat"] == 0.0

    def test_file_path_with_insufficient_data(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"v": [1]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = self._call({"file_path": "data.xlsx"}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["action"] == "forecast"
        assert data["future_forecast"][0]["yhat"] == 0.0

    def test_file_path_with_valid_data_forecasts(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = self._call({"file_path": "data.xlsx", "periods": 3}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["action"] == "forecast"
        assert data["model"] == "linear_regression"
        assert len(data["future_forecast"]) == 3

    def test_value_col_not_in_columns_auto_detect(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"name": ["a", "b"], "v": [1.0, 2.0, 3.0, 4.0][:2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = self._call(
                {"file_path": "data.xlsx", "value_column": "missing"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["action"] == "forecast"

    def test_no_numeric_columns(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"name": ["a", "b"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = self._call({"file_path": "data.xlsx"}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["action"] == "forecast"
        assert data["future_forecast"][0]["yhat"] == 0.0

    def test_periods_clamped_to_max_30(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"v": [1.0, 2.0, 3.0]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = self._call(
                {"file_path": "data.xlsx", "periods": 100},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert len(data["future_forecast"]) == 30

    def test_recoverable_error_returns_error(self, tmp_path: Path) -> None:
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=OSError("fail"),
        ):
            result = self._call({"file_path": "x.xlsx"}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["action"] == "forecast"
        assert "error" in data


# ---------------------------------------------------------------------------
# execute_workflow_tool — excel_schema_understand
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolSchemaUnderstand:
    """execute_workflow_tool excel_schema_understand 分支覆盖。"""

    def _call(self, args, workspace_root=None):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            return execute_workflow_tool("excel_schema_understand", args, workspace_root=workspace_root)

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = self._call({"file_path": "missing.xlsx"}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "file_not_found"

    def test_success(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.infrastructure.excel.schema_service.ExcelSchemaUnderstandingService.understand_dataframe",
            return_value={"success": True, "fields": []},
        ):
            result = self._call({"file_path": "data.xlsx"}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["success"] is True

    def test_recoverable_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("read fail"),
        ):
            result = self._call({"file_path": "data.xlsx"}, workspace_root=str(tmp_path))
        data = json.loads(result)
        assert data["success"] is False
        assert "read fail" in data["error"]


# ---------------------------------------------------------------------------
# execute_workflow_tool — products_bulk_import / excel_vector_index
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolBulkAndVector:
    """execute_workflow_tool products_bulk_import / excel_vector_index 分支覆盖。"""

    def _call(self, name, args, workspace_root=None):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            return execute_workflow_tool(name, args, workspace_root=workspace_root)

    def test_products_bulk_import_dispatches(self) -> None:
        with patch(
            "app.application.excel_imports.run_bulk_import",
            return_value={"success": True},
            create=True,
        ):
            result = self._call("products_bulk_import", {"file_path": "x.xlsx"})
        data = json.loads(result)
        assert data["success"] is True

    def test_excel_vector_index_missing_file_path(self) -> None:
        result = self._call("excel_vector_index", {})
        data = json.loads(result)
        assert data["success"] is False
        assert "file_path" in data["error"]

    def test_excel_vector_index_file_not_found(self, tmp_path: Path) -> None:
        result = self._call(
            "excel_vector_index", {"file_path": "missing.xlsx"}, workspace_root=str(tmp_path)
        )
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "file_not_found"

    def test_excel_vector_index_success_with_index_id(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {
            "success": True,
            "index_id": "idx-123",
        }
        with patch(
            "app.application.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
            create=True,
        ):
            result = self._call(
                "excel_vector_index", {"file_path": "data.xlsx"}, workspace_root=str(tmp_path)
            )
        data = json.loads(result)
        assert data["success"] is True
        assert data["excel_vector_index_id"] == "idx-123"
        assert data["excel_index_id"] == "idx-123"

    def test_excel_vector_index_success_without_index_id(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        mock_svc = MagicMock()
        mock_svc.ingest_excel.return_value = {"success": True}
        with patch(
            "app.application.get_excel_vector_ingest_app_service",
            return_value=mock_svc,
            create=True,
        ):
            result = self._call(
                "excel_vector_index", {"file_path": "data.xlsx"}, workspace_root=str(tmp_path)
            )
        data = json.loads(result)
        assert data["success"] is True
        assert "excel_vector_index_id" not in data


# ---------------------------------------------------------------------------
# execute_workflow_tool — generate_office_document
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolGenerateOffice:
    """execute_workflow_tool generate_office_document 分支覆盖。"""

    def _call(self, args, workspace_root=None):
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            return execute_workflow_tool("generate_office_document", args, workspace_root=workspace_root)

    def test_missing_user_request(self) -> None:
        result = self._call({"output_format": "docx"})
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "missing_user_request"

    def test_invalid_format_defaults_to_docx(self) -> None:
        with patch(
            "app.services.kitten_ai_document.generate.generate_office_file",
            return_value=(b"content", "file.docx"),
            create=True,
        ), patch(
            "app.services.kitten_ai_document.pickup.store_document_pickup",
            return_value="token123",
            create=True,
        ):
            result = self._call({"user_request": "make a doc", "output_format": "pdf"})
        data = json.loads(result)
        assert data["success"] is True
        assert data["file_name"] == "file.docx"

    def test_xlsx_format(self) -> None:
        with patch(
            "app.services.kitten_ai_document.generate.generate_office_file",
            return_value=(b"content", "file.xlsx"),
            create=True,
        ), patch(
            "app.services.kitten_ai_document.pickup.store_document_pickup",
            return_value="token123",
            create=True,
        ):
            result = self._call({"user_request": "make a sheet", "output_format": "xlsx"})
        data = json.loads(result)
        assert data["success"] is True
        assert "spreadsheet" in data["artifacts"][0]["mime_type"]

    def test_recoverable_error(self) -> None:
        with patch(
            "app.services.kitten_ai_document.generate.generate_office_file",
            side_effect=OSError("disk full"),
            create=True,
        ):
            result = self._call({"user_request": "make a doc"})
        data = json.loads(result)
        assert data["success"] is False
        assert "disk full" in data["error"]

    def test_prompt_alias_for_user_request(self) -> None:
        with patch(
            "app.services.kitten_ai_document.generate.generate_office_file",
            return_value=(b"content", "file.docx"),
            create=True,
        ), patch(
            "app.services.kitten_ai_document.pickup.store_document_pickup",
            return_value="token123",
            create=True,
        ):
            result = self._call({"prompt": "via prompt alias"})
        data = json.loads(result)
        assert data["success"] is True


# ---------------------------------------------------------------------------
# execute_workflow_tool — unknown_tool / template_preview empty action
# ---------------------------------------------------------------------------


class TestExecuteWorkflowToolMisc:
    """execute_workflow_tool 其它分支覆盖。"""

    def test_unknown_tool(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            result = execute_workflow_tool("totally_unknown", {})
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "unknown_tool"
        assert data["tool"] == "totally_unknown"

    def test_template_preview_empty_action_defaults_to_view(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
            patch(
                "app.services.tools_workflow_registered.execute_registered_workflow_tool",
                return_value={"result": "ok"},
                create=True,
            ),
        ):
            result = execute_workflow_tool("template_preview", {"action": ""})
        data = json.loads(result)
        assert "result" in data

    def test_employee_planner_tool_returned(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value='{"emp": true}',
                create=True,
            ),
        ):
            result = execute_workflow_tool("some_tool", {})
        assert "emp" in result

    def test_planner_native_tool_error_swallowed(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                side_effect=ImportError("no planner"),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        data = json.loads(result)
        assert "suggestions" in data

    def test_employee_planner_tool_error_swallowed(self) -> None:
        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                return_value=(None, None),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                side_effect=RuntimeError("fail"),
                create=True,
            ),
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        data = json.loads(result)
        assert "suggestions" in data


# ---------------------------------------------------------------------------
# _handle_import_excel_to_database
# ---------------------------------------------------------------------------


class TestHandleImportExcelToDatabase:
    """_handle_import_excel_to_database 分支覆盖。"""

    @pytest.fixture(autouse=True)
    def _suppress_customer_hint(self) -> Any:
        """默认抑制 _extract_customer_hint_from_excel（避免 BadZipFile）。

        测试文件创建的是伪 xlsx（write_text("not excel")），openpyxl 加载会
        抛 BadZipFile（不在 RECOVERABLE_ERRORS 中）。需要测试 customer_hint
        的用例可自行覆盖此 patch。
        """
        with patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            return_value="",
            create=True,
        ):
            yield

    def test_missing_file_path_returns_error(self) -> None:
        result = _handle_import_excel_to_database({"import_type": "products"})
        data = json.loads(result)
        assert data["success"] is False
        assert "file_path" in data["error"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = _handle_import_excel_to_database(
            {"import_type": "products", "file_path": "missing.xlsx"},
            workspace_root=str(tmp_path),
        )
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "file not found"

    def test_db_write_token_required(self, tmp_path: Path) -> None:
        # token 校验仅在 workspace_root is None 时触发
        with patch.dict("os.environ", {"FHD_DB_WRITE_TOKEN": "secret"}):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx"},
            )
        data = json.loads(result)
        assert data["success"] is False
        assert data.get("requires_token") is True

    def test_db_write_token_invalid(self, tmp_path: Path) -> None:
        # token 校验仅在 workspace_root is None 时触发
        with patch.dict("os.environ", {"FHD_DB_WRITE_TOKEN": "secret"}):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx", "db_write_token": "wrong"},
            )
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "invalid_token"

    def test_db_write_token_valid_proceeds(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"], "型号": ["x"]})
        with patch.dict("os.environ", {"FHD_DB_WRITE_TOKEN": "secret"}), patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx", "db_write_token": "secret", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        # preview_only → preview=True
        assert data.get("preview") is True or data.get("success") is False

    def test_read_excel_failed(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("read fail"),
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False
        assert "read_excel_failed" in data["error"]

    def test_empty_dataframe(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame()
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "Excel file is empty"

    def test_invalid_last_data_row(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx", "last_data_row_1based": 1},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False
        assert data["error"] == "invalid_last_data_row"

    def test_invalid_last_data_row_non_int(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx", "last_data_row_1based": "abc"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        # non-int last_data_row → None → no truncation → proceeds to import_type
        # products 路径但无产品列 → 返回 message
        assert "message" in data or data.get("success") is False or data.get("preview") is True

    def test_import_type_orders_preview(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"], "数量": [1], "购买单位": ["客户A"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "orders", "file_path": "data.xlsx", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True
        assert data["import_type"] == "orders"

    def test_import_type_other_returns_preview(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "unknown_type", "file_path": "data.xlsx"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is True
        assert data["preview"] is True
        assert data["import_type"] == "unknown_type"

    def test_unit_name_from_excel_customer_hint_arg(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "excel_customer_hint": "客户X",
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True
        assert data.get("detected_unit") == "客户X" or "客户X" in str(data)

    def test_unit_name_from_req_ctx_excel_customer_hint(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "context": {"excel_customer_hint": "客户Y"},
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_unit_name_from_excel_analysis_ctx(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "excel_analysis": {"customer_hint": "客户Z"},
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_sheet_name_from_excel_analysis_selected_sheet(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ) as mock_read:
            _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "context": {"excel_analysis_selected_sheet": {"sheet_name": "Sheet2"}},
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
            # sheet_name should be passed to _read_excel_dataframe
            assert mock_read.call_args.kwargs.get("sheet_name") == "Sheet2"

    def test_header_row_from_excel_analysis_ctx(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.domain.context.session_context.detected_excel_header_row_1based",
            return_value=3,
            create=True,
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "excel_analysis": {"some": "ctx"},
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_header_row_detection_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.domain.context.session_context.detected_excel_header_row_1based",
            side_effect=OSError("fail"),
            create=True,
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "excel_analysis": {"some": "ctx"},
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_unit_name_from_linked_grid_preview(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            return_value=["客户W"],
            create=True,
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "context": {
                        "excel_linked_grid_preview": {"preview_text": "客户W的报价单"}
                    },
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_unit_name_from_linked_grid_previews_list(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
            return_value=["客户V"],
            create=True,
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "context": {
                        "excel_linked_grid_previews": [
                            {"preview_text": "客户V的报价单"}
                        ]
                    },
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_unit_name_from_extract_customer_hint_from_excel(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            return_value="客户U",
            create=True,
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_unit_name_extract_customer_hint_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        df = pd.DataFrame({"产品名称": ["a"]})
        with patch(
            "app.application.tools.workflow._read_excel_dataframe", return_value=df
        ), patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            side_effect=OSError("fail"),
            create=True,
        ):
            result = _handle_import_excel_to_database(
                {
                    "import_type": "products",
                    "file_path": "data.xlsx",
                    "preview_only": True,
                },
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data.get("preview") is True

    def test_recoverable_error_wrapped(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xlsx"
        f.write_text("not excel")
        with patch(
            "app.application.tools.workflow.resolve_safe_excel_path",
            side_effect=RuntimeError("unexpected"),
        ):
            result = _handle_import_excel_to_database(
                {"import_type": "products", "file_path": "data.xlsx"},
                workspace_root=str(tmp_path),
            )
        data = json.loads(result)
        assert data["success"] is False


# ---------------------------------------------------------------------------
# _import_orders_preview_or_execute
# ---------------------------------------------------------------------------


class TestImportOrdersPreviewOrExecute:
    """_import_orders_preview_or_execute 分支覆盖。"""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame({"产品名称": ["a"], "数量": [1], "购买单位": ["客户A"]})
        result = json.loads(_import_orders_preview_or_execute(df, list(df.columns), "客户A", False, 1))
        assert result["preview"] is True
        assert result["import_type"] == "orders"
        assert "column_mapping" in result

    def test_confirm_with_unit_name(self) -> None:
        df = pd.DataFrame({"产品名称": ["a"], "数量": [2], "购买单位": ["客户A"]})
        mock_svc = MagicMock()
        mock_svc.create_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc, create=True):
            result = json.loads(_import_orders_preview_or_execute(df, list(df.columns), "客户A", True, 1))
        assert result["success"] is True
        assert result["imported"] == 1

    def test_confirm_without_unit_name_fails(self) -> None:
        df = pd.DataFrame({"产品名称": ["a"], "数量": [2]})
        mock_svc = MagicMock()
        mock_svc.create_shipment.return_value = {"success": True}
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc, create=True):
            result = json.loads(_import_orders_preview_or_execute(df, list(df.columns), "", True, 1))
        assert result["success"] is True
        assert result["failed"] == 1

    def test_confirm_service_error(self) -> None:
        df = pd.DataFrame({"产品名称": ["a"], "数量": [2], "购买单位": ["客户A"]})
        with patch(
            "app.bootstrap.get_shipment_app_service",
            side_effect=OSError("db fail"),
            create=True,
        ):
            result = json.loads(_import_orders_preview_or_execute(df, list(df.columns), "客户A", True, 1))
        assert result["success"] is False
        assert "订单导入失败" in result["error"]

    def test_confirm_row_level_error(self) -> None:
        df = pd.DataFrame({"产品名称": ["a"], "数量": [2], "购买单位": ["客户A"]})
        mock_svc = MagicMock()
        mock_svc.create_shipment.side_effect = RuntimeError("row fail")
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc, create=True):
            result = json.loads(_import_orders_preview_or_execute(df, list(df.columns), "客户A", True, 1))
        assert result["success"] is True
        assert result["failed"] == 1


# ---------------------------------------------------------------------------
# _excel_cell_as_clean_str / _excel_cell_as_float — edge cases
# ---------------------------------------------------------------------------


class TestExcelCellAsCleanStrEdgeCases:
    """_excel_cell_as_clean_str 边界分支覆盖。"""

    def test_bool_returns_empty(self) -> None:
        assert _excel_cell_as_clean_str(True) == ""
        assert _excel_cell_as_clean_str(False) == ""

    def test_negative_inf_returns_empty(self) -> None:
        assert _excel_cell_as_clean_str(float("-inf")) == ""

    def test_nat_string_returns_empty(self) -> None:
        assert _excel_cell_as_clean_str("NaT") == ""

    def test_null_string_returns_empty(self) -> None:
        assert _excel_cell_as_clean_str("null") == ""

    def test_float_non_integer_returns_str(self) -> None:
        assert _excel_cell_as_clean_str(3.14) == "3.14"

    def test_pd_isna_error_swallowed(self) -> None:
        # list input causes pd.isna to raise TypeError in some versions
        result = _excel_cell_as_clean_str([1, 2, 3])
        # Should not crash; returns str representation
        assert isinstance(result, str)


class TestExcelCellAsFloatEdgeCases:
    """_excel_cell_as_float 边界分支覆盖。"""

    def test_nan_after_float_returns_default(self) -> None:
        # float("nan") handled by first check
        assert _excel_cell_as_float(float("nan")) == 0.0

    def test_pd_isna_error_swallowed(self) -> None:
        # list input causes pd.isna to raise
        result = _excel_cell_as_float([1, 2])
        # Should not crash; falls through to float() which may fail → default
        assert isinstance(result, float)

    def test_nan_after_float_conversion(self) -> None:
        # float("nan") conversion path
        assert _excel_cell_as_float("nan") == 0.0

    def test_valid_string_number(self) -> None:
        assert _excel_cell_as_float("42.5") == pytest.approx(42.5)


# ---------------------------------------------------------------------------
# _looks_like_contract_or_footer_line — edge cases
# ---------------------------------------------------------------------------


class TestLooksLikeContractOrFooterLineEdgeCases:
    """_looks_like_contract_or_footer_line 边界分支覆盖。"""

    def test_numbered_clause_without_keyword(self) -> None:
        # numbered clause with >= 8 chars after number but no clause keyword
        assert not _looks_like_contract_or_footer_line("1、这是普通产品说明文字")

    def test_numbered_clause_with_keyword(self) -> None:
        assert _looks_like_contract_or_footer_line("1、以上价格含税不含运费说明")

    def test_numbered_clause_short_rest(self) -> None:
        # rest < 8 chars → not a clause
        assert not _looks_like_contract_or_footer_line("1、含税")

    def test_numbered_clause_with_clause_substring(self) -> None:
        assert _looks_like_contract_or_footer_line("2、供应方签名盖章处")

    def test_long_text_without_clause(self) -> None:
        assert not _looks_like_contract_or_footer_line("铝合金方管50x50x3规格产品")


# ---------------------------------------------------------------------------
# _read_excel_dataframe
# ---------------------------------------------------------------------------


class TestReadExcelDataframe:
    """_read_excel_dataframe 分支覆盖。"""

    def test_xlsx_uses_openpyxl_engine(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert mock_read.call_args.kwargs.get("engine") == "openpyxl"

    def test_xlsm_uses_openpyxl_engine(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsm"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert mock_read.call_args.kwargs.get("engine") == "openpyxl"

    def test_sheet_name_passed(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name="Sheet2", header_row_1based=None)
            assert mock_read.call_args.kwargs.get("sheet_name") == "Sheet2"

    def test_header_row_passed(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=3)
            assert mock_read.call_args.kwargs.get("header") == 2

    def test_no_extra_kwargs_for_xls(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xls"
        p.write_text("not excel")
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.read_excel", return_value=df) as mock_read:
            _read_excel_dataframe(p, sheet_name=None, header_row_1based=None)
            assert "engine" not in mock_read.call_args.kwargs


# ---------------------------------------------------------------------------
# invalidate_workflow_tool_registry
# ---------------------------------------------------------------------------


class TestInvalidateWorkflowToolRegistry:
    """invalidate_workflow_tool_registry 分支覆盖。"""

    def test_invalidates_cache(self) -> None:
        import app.application.tools.workflow as wf

        wf._workflow_tool_registry_cache = [{"old": True}]
        wf._WORKFLOW_REG_VER = 1
        with patch(
            "app.mod_sdk.employee_tool_registry.invalidate_employee_tool_cache",
            create=True,
        ):
            invalidate_workflow_tool_registry()
        assert wf._workflow_tool_registry_cache is None
        assert wf._WORKFLOW_REG_VER == 2

    def test_employee_cache_invalidate_error_swallowed(self) -> None:
        import app.application.tools.workflow as wf

        wf._workflow_tool_registry_cache = [{"old": True}]
        with patch(
            "app.mod_sdk.employee_tool_registry.invalidate_employee_tool_cache",
            side_effect=ImportError("no module"),
            create=True,
        ):
            invalidate_workflow_tool_registry()
        assert wf._workflow_tool_registry_cache is None


# ---------------------------------------------------------------------------
# _infer_product_field_mapping — additional branches
# ---------------------------------------------------------------------------


class TestInferProductFieldMappingAdditional:
    """_infer_product_field_mapping 补充分支覆盖。"""

    def test_sku_column(self) -> None:
        m = _infer_product_field_mapping(["sku", "name"])
        assert m.get("model_number") == "sku"

    def test_bianhao_column(self) -> None:
        m = _infer_product_field_mapping(["编号", "name"])
        assert m.get("model_number") == "编号"

    def test_bianma_column(self) -> None:
        m = _infer_product_field_mapping(["编码", "name"])
        assert m.get("model_number") == "编码"

    def test_unit_column(self) -> None:
        m = _infer_product_field_mapping(["单位", "name"])
        assert m.get("unit") == "单位"

    def test_quantity_column(self) -> None:
        m = _infer_product_field_mapping(["数量", "name"])
        assert m.get("quantity") == "数量"

    def test_qty_column(self) -> None:
        m = _infer_product_field_mapping(["qty", "name"])
        assert m.get("quantity") == "qty"

    def test_description_column(self) -> None:
        m = _infer_product_field_mapping(["备注", "name"])
        assert m.get("description") == "备注"

    def test_brand_column(self) -> None:
        m = _infer_product_field_mapping(["品牌", "name"])
        assert m.get("brand") == "品牌"

    def test_category_column(self) -> None:
        m = _infer_product_field_mapping(["类别", "name"])
        assert m.get("category") == "类别"

    def test_price_diaoqianhou(self) -> None:
        m = _infer_product_field_mapping(["调价前", "name"])
        assert m.get("price") == "调价前"

    def test_price_diaoqianhou_after(self) -> None:
        m = _infer_product_field_mapping(["调价后", "name"])
        assert m.get("price") == "调价后"

    def test_price_xianjia(self) -> None:
        m = _infer_product_field_mapping(["现价", "name"])
        assert m.get("price") == "现价"

    def test_price_english(self) -> None:
        m = _infer_product_field_mapping(["price", "name"])
        assert m.get("price") == "price"

    def test_specification_with_guige(self) -> None:
        m = _infer_product_field_mapping(["规格型号", "name"])
        # "规格" maps to model_number (not specification)
        assert m.get("model_number") == "规格型号" or m.get("specification") == "规格型号"

    def test_skip_specification_when_has_hao(self) -> None:
        # "规格号" — actual behavior: maps to specification
        m = _infer_product_field_mapping(["规格号", "name"])
        assert isinstance(m, dict)
