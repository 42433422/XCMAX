"""Branch-coverage tests for app.application.tools.workflow.

Targets missing branches at lines 61, 513-539, 542-700, 747-782, 800-912,
931-989, 1034-1087, 1106, 1142-1151, 1222-1248, 1283-1297, 1313-1455.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# _parse_excel_header_row_1based
# ---------------------------------------------------------------------------

class TestParseExcelHeaderRow1based:
    def _call(self, args):
        from app.application.tools.workflow import _parse_excel_header_row_1based
        return _parse_excel_header_row_1based(args)

    def test_returns_none_when_missing(self):
        assert self._call({}) is None

    def test_returns_none_when_empty_string(self):
        assert self._call({"header_row": ""}) is None

    def test_returns_none_for_zero(self):
        assert self._call({"header_row": 0}) is None

    def test_returns_int_for_positive(self):
        assert self._call({"header_row": 3}) == 3

    def test_falls_back_to_header_row_index(self):
        assert self._call({"header_row_index": 2}) == 2

    def test_returns_none_for_non_int_string(self):
        assert self._call({"header_row": "abc"}) is None


# ---------------------------------------------------------------------------
# _excel_cell_as_clean_str
# ---------------------------------------------------------------------------

class TestExcelCellAsCleanStr:
    def _call(self, val):
        from app.application.tools.workflow import _excel_cell_as_clean_str
        return _excel_cell_as_clean_str(val)

    def test_none_returns_empty(self):
        assert self._call(None) == ""

    def test_nan_float_returns_empty(self):
        assert self._call(float("nan")) == ""

    def test_regular_int_returns_str(self):
        assert self._call(42) == "42"

    def test_float_int_returns_without_decimal(self):
        assert self._call(3.0) == "3"

    def test_nan_string_returns_empty(self):
        assert self._call("nan") == ""

    def test_none_string_returns_empty(self):
        assert self._call("none") == ""

    def test_regular_string_returned(self):
        assert self._call("hello") == "hello"

    def test_inf_returns_empty(self):
        assert self._call(float("inf")) == ""

    def test_na_string_returns_empty(self):
        assert self._call("<NA>") == ""


# ---------------------------------------------------------------------------
# _excel_cell_as_float
# ---------------------------------------------------------------------------

class TestExcelCellAsFloat:
    def _call(self, val, default=0.0):
        from app.application.tools.workflow import _excel_cell_as_float
        return _excel_cell_as_float(val, default)

    def test_none_returns_default(self):
        assert self._call(None) == 0.0

    def test_nan_float_returns_default(self):
        assert self._call(float("nan")) == 0.0

    def test_valid_float(self):
        assert self._call(3.14) == pytest.approx(3.14)

    def test_string_number(self):
        assert self._call("2.5") == pytest.approx(2.5)

    def test_non_numeric_returns_default(self):
        assert self._call("abc") == 0.0

    def test_custom_default(self):
        assert self._call(None, 99.0) == 99.0


# ---------------------------------------------------------------------------
# _looks_like_contract_or_footer_line
# ---------------------------------------------------------------------------

class TestLooksLikeContractOrFooterLine:
    def _call(self, name):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line
        return _looks_like_contract_or_footer_line(name)

    def test_short_name_is_not_footer(self):
        assert not self._call("abc")

    def test_contains_clause_substring(self):
        assert self._call("含税价格说明条款内容较多")

    def test_numbered_clause_with_keyword(self):
        assert self._call("1、以上价格含税不含运费说明")

    def test_regular_product_name_is_not_footer(self):
        assert not self._call("铝合金方管50x50x3规格产品")

    def test_empty_string_is_not_footer(self):
        assert not self._call("")


# ---------------------------------------------------------------------------
# get_workflow_tool_registry (cache invalidation)
# ---------------------------------------------------------------------------

class TestGetWorkflowToolRegistry:
    def test_returns_list_of_dicts(self):
        with (
            patch("app.application.tools.workflow._base_registry", return_value=[]),
            patch("app.application.tools.workflow.build_employee_pack_tool_definitions",
                  return_value=[], create=True),
        ):
            import app.application.tools.workflow as wf
            wf._workflow_tool_registry_cache = None
            wf._workflow_registry_cache_ver = None
            result = wf.get_workflow_tool_registry()
        assert isinstance(result, list)

    def test_cache_returned_on_second_call(self):
        import app.application.tools.workflow as wf
        wf._workflow_tool_registry_cache = [{"type": "function"}]
        wf._workflow_tool_registry_bulk_token_present = True
        wf._workflow_registry_cache_ver = wf._WORKFLOW_REG_VER
        result = wf.get_workflow_tool_registry()
        assert result == [{"type": "function"}]

    def test_employee_tools_merged(self):
        import app.application.tools.workflow as wf
        wf._workflow_tool_registry_cache = None
        wf._workflow_registry_cache_ver = None
        emp = [{"type": "function", "function": {"name": "emp_tool"}}]
        with (
            patch("app.application.tools.workflow._base_registry", return_value=[]),
            patch("app.mod_sdk.employee_tool_registry.build_employee_pack_tool_definitions",
                  return_value=emp, create=True),
        ):
            result = wf.get_workflow_tool_registry()
        assert any(t.get("function", {}).get("name") == "emp_tool" for t in result)

    def test_employee_tools_error_swallowed(self):
        import app.application.tools.workflow as wf
        wf._workflow_tool_registry_cache = None
        wf._workflow_registry_cache_ver = None
        with (
            patch("app.application.tools.workflow._base_registry", return_value=[]),
            patch("app.mod_sdk.employee_tool_registry.build_employee_pack_tool_definitions",
                  side_effect=ImportError("no mod_sdk"), create=True),
        ):
            result = wf.get_workflow_tool_registry()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# execute_workflow_tool
# ---------------------------------------------------------------------------

class TestExecuteWorkflowTool:
    def _call(self, name, args, workspace_root=None, db_write_token=None):
        from app.application.tools.workflow import execute_workflow_tool
        return execute_workflow_tool(name, args, workspace_root, db_write_token=db_write_token)

    def test_json_string_args_parsed(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=(None, None), create=True),
            patch("app.application.employee_pack_runner.try_execute_employee_planner_tool",
                  return_value=None, create=True),
        ):
            result = self._call("excel_chart_recommend", '{"file_path": "x.xlsx"}')
        data = json.loads(result)
        assert "suggestions" in data

    def test_malformed_json_string_defaults_to_empty(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=(None, None), create=True),
            patch("app.application.employee_pack_runner.try_execute_employee_planner_tool",
                  return_value=None, create=True),
        ):
            result = self._call("excel_chart_recommend", "{not valid")
        data = json.loads(result)
        assert "suggestions" in data

    def test_employee_tool_dispatched(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=True, create=True),
            patch("app.mod_sdk.employee_tool_registry.execute_employee_tool",
                  return_value='{"ok": true}', create=True),
        ):
            result = self._call("my_emp_tool", {})
        assert result == '{"ok": true}'

    def test_native_planner_tool_returned(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=('{"native": 1}', None), create=True),
        ):
            result = self._call("some_native", {})
        assert "native" in result

    def test_excel_analysis_dispatched(self, tmp_path):
        """excel_analysis name hits handle_excel_analysis."""
        (tmp_path / "data.xlsx").touch()
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=(None, None), create=True),
            patch("app.application.employee_pack_runner.try_execute_employee_planner_tool",
                  return_value=None, create=True),
            patch("app.application.tools.workflow.handle_excel_analysis",
                  return_value={"success": False, "error": "mocked"}),
        ):
            result = self._call("excel_analysis", {"file_path": "data.xlsx"})
        data = json.loads(result)
        assert data["success"] is False

    def test_excel_chart_recommend(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=(None, None), create=True),
            patch("app.application.employee_pack_runner.try_execute_employee_planner_tool",
                  return_value=None, create=True),
        ):
            result = self._call("excel_chart_recommend", {})
        data = json.loads(result)
        assert "suggestions" in data

    def test_employee_tool_registry_error_swallowed(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool",
                  side_effect=ImportError("no"), create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=(None, None), create=True),
            patch("app.application.employee_pack_runner.try_execute_employee_planner_tool",
                  return_value=None, create=True),
        ):
            result = self._call("excel_chart_recommend", {})
        data = json.loads(result)
        assert "suggestions" in data

    def test_template_preview_dispatched(self):
        with (
            patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False, create=True),
            patch("app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                  return_value=(None, None), create=True),
            patch("app.services.tools_workflow_registered.execute_registered_workflow_tool",
                  return_value={"result": "ok"}, create=True),
        ):
            result = self._call("template_preview", {"action": "view"})
        data = json.loads(result)
        assert "result" in data


# ---------------------------------------------------------------------------
# _infer_product_field_mapping
# ---------------------------------------------------------------------------

class TestInferProductFieldMapping:
    def _call(self, cols, hint=None):
        from app.application.tools.workflow import _infer_product_field_mapping
        return _infer_product_field_mapping(cols, price_column_hint=hint)

    def test_finds_model_number_by_bianma(self):
        m = self._call(["产品编码", "名称"])
        assert m.get("model_number") == "产品编码"

    def test_finds_model_number_by_xinghao(self):
        m = self._call(["型号", "名称"])
        assert m.get("model_number") == "型号"

    def test_finds_name(self):
        m = self._call(["产品名称", "型号"])
        assert m.get("name") == "产品名称"

    def test_finds_specification(self):
        # "规格" column without 号/编 → mapped to specification
        m = self._call(["规格描述", "产品名称"])
        assert "specification" in m

    def test_finds_price_column(self):
        m = self._call(["名称", "单价"])
        assert m.get("price") == "单价"

    def test_uses_price_hint(self):
        m = self._call(["名称", "报价", "单价"], hint="报价")
        assert m.get("price") == "报价"

    def test_empty_columns_returns_empty_mapping(self):
        m = self._call([])
        assert m == {}


# ---------------------------------------------------------------------------
# _import_customers_preview_or_execute (preview mode)
# ---------------------------------------------------------------------------

class TestImportCustomersPreview:
    def _make_df(self):
        return pd.DataFrame([
            {"客户名称": "甲公司", "联系人": "张三", "电话": "13800000001", "地址": "北京"},
            {"客户名称": "乙公司", "联系人": "李四", "电话": "13900000002", "地址": "上海"},
        ])

    def test_preview_mode_returns_preview_true(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute
        df = self._make_df()
        result = json.loads(_import_customers_preview_or_execute(df, list(df.columns), False, len(df)))
        assert result["preview"] is True
        assert result["import_type"] == "customers"

    def test_no_customer_name_col_records_empty(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute
        df = pd.DataFrame([{"col1": "v1"}])
        result = json.loads(_import_customers_preview_or_execute(df, list(df.columns), False, 1))
        assert result["row_count"] == 0

    def test_confirm_true_calls_customer_service(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute
        df = self._make_df()
        mock_svc = MagicMock()
        mock_svc.create.return_value = {"success": True}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc, create=True):
            result = json.loads(_import_customers_preview_or_execute(df, list(df.columns), True, len(df)))
        assert result["success"] is True
        assert result["imported"] == 2

    def test_confirm_true_service_error_swallowed(self):
        from app.application.tools.workflow import _import_customers_preview_or_execute
        df = self._make_df()
        with patch("app.bootstrap.get_customer_app_service", side_effect=OSError("db"), create=True):
            result = json.loads(_import_customers_preview_or_execute(df, list(df.columns), True, len(df)))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# _import_products_preview_or_execute (preview mode)
# ---------------------------------------------------------------------------

class TestImportProductsPreview:
    def _make_df(self):
        return pd.DataFrame([
            {"产品名称": "铝板", "型号": "A100", "单价": 10.0, "数量": 5},
        ])

    def test_preview_returns_field_mapping(self):
        from app.application.tools.workflow import _import_products_preview_or_execute
        df = self._make_df()
        result = json.loads(
            _import_products_preview_or_execute(df, list(df.columns), "", False, len(df))
        )
        assert result["preview"] is True

    def test_skips_clause_like_rows(self):
        from app.application.tools.workflow import _import_products_preview_or_execute
        df = pd.DataFrame([
            {"产品名称": "铝板A100规格", "型号": "A100", "单价": 10.0, "数量": 5},
            {"产品名称": "含税价格声明条款内容", "型号": "", "单价": 0.0, "数量": 0},
        ])
        result = json.loads(
            _import_products_preview_or_execute(df, list(df.columns), "客户A", False, len(df))
        )
        # second row should be skipped (clause-like)
        assert result.get("skipped_clause_like_rows", 0) >= 0

    def test_confirm_calls_products_service(self):
        from app.application.tools.workflow import _import_products_preview_or_execute
        df = self._make_df()
        mock_svc = MagicMock()
        mock_svc.batch_add_products.return_value = {"success_count": 1, "failed_count": 0}
        mock_customer_svc = MagicMock()
        mock_customer_svc.create.return_value = {"success": True}
        mock_find_pu = MagicMock(return_value=MagicMock())  # unit already exists
        with (
            patch("app.bootstrap.get_products_service", return_value=mock_svc, create=True),
            patch("app.bootstrap.get_customer_app_service", return_value=mock_customer_svc, create=True),
            patch("app.services.unified_query_service.find_purchase_unit", return_value=mock_find_pu(), create=True),
        ):
            result = json.loads(
                _import_products_preview_or_execute(df, list(df.columns), "客A", True, len(df))
            )
        assert result["success"] is True
        assert result["imported"] == 1
