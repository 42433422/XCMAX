"""Targeted coverage tests for app.application.tools.workflow.

Focus: the error/except branches and edge cases not yet exercised by the
existing test_tools_workflow_cov / test_workflow_tools_ext* suites. Each test
asserts on real return values / side effects and is fully offline (DB, LLM,
filesystem helpers all mocked or driven via tmp_path).

Uncovered targets (line numbers from the missing-line report):
  87        run_natural_language_pandas ValueError branch
  166-167   handle_excel_analysis read: customer_hint extraction error swallowed
  492-493   invalidate_workflow_tool_registry employee cache error swallowed
  569-570   execute_workflow_tool native planner dispatch error swallowed
  586-588   execute_workflow_tool legacy employee planner returns raw / error
  678-679   excel_join_compare except RECOVERABLE_ERRORS
  736-737   excel_prophet except RECOVERABLE_ERRORS
  763-764   excel_schema_understand except RECOVERABLE_ERRORS
  898-900   _handle_import sheet_name from excel_analysis_selected_sheet
  908-910   _handle_import sheet_name from preview_data
  950       unit_name from excel_analysis customer_hint
  964-977   unit_name from linked grid preview inline hits
  986-987   unit_name from _extract_customer_hint_from_excel error swallowed
  996-1004  header detection from excel_analysis ctx (+ error branch)
  1029-1030 last_data parse TypeError/ValueError branch
  1045      last_data row slice
  1067/1069 customers/orders dispatch
  1220/1223 _excel_cell_as_clean_str isna error / float-nan branches
  1242-1248 _excel_cell_as_float isna error / nan-after-float branches
  1294/1296 _looks_like_contract_or_footer_line numbered-clause branches
  1314-1316 _import_products detected_unit from single unit column
  1327/1343 spec from model_col fallback / qty int-cast failure
  1610-1611 _import_orders per-row exception increments failed
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# run_natural_language_pandas — ValueError branch (line 87)
# ---------------------------------------------------------------------------


class TestRunNLValueErrorBranch:
    def test_translate_raises_value_error_sets_error_msg(self):
        from app.application.tools.workflow import run_natural_language_pandas

        df = pd.DataFrame({"a": [1, 2, 3]})
        mock_converter = MagicMock()
        mock_converter.translate.side_effect = ValueError("bad NL query")
        with patch.dict(
            "sys.modules",
            {
                "app.legacy.excel_text_to_pandas": MagicMock(
                    ExcelTextToPandas=MagicMock(return_value=mock_converter)
                )
            },
        ):
            result = run_natural_language_pandas(df, "explode")
        # ValueError is caught at line 86-87 → error key present, df unchanged.
        assert result["error"] == "bad NL query"
        assert result["row_count"] == 3
        assert result["generated_code"] == ""


# ---------------------------------------------------------------------------
# handle_excel_analysis read: customer_hint extraction error swallowed (166-167)
# ---------------------------------------------------------------------------


class TestHandleExcelAnalysisCustomerHint:
    def test_customer_hint_success_attached(self, tmp_path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        with patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            return_value="客户甲公司",
        ):
            result = handle_excel_analysis(
                {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        assert result["customer_hint"] == "客户甲公司"

    def test_customer_hint_extraction_error_swallowed(self, tmp_path):
        from app.application.tools.workflow import handle_excel_analysis

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        # OSError is in RECOVERABLE_ERRORS → suppressed at line 166-167.
        with patch(
            "app.application.template_grid_core._extract_customer_hint_from_excel",
            side_effect=OSError("hint read boom"),
        ):
            result = handle_excel_analysis(
                {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
            )
        assert result["success"] is True
        # Hint extraction failed → no customer_hint key, but read still succeeds.
        assert "customer_hint" not in result


# ---------------------------------------------------------------------------
# invalidate_workflow_tool_registry — employee cache error swallowed (492-493)
# ---------------------------------------------------------------------------


class TestInvalidateRegistry:
    def test_bumps_version_and_clears_cache(self):
        import app.application.tools.workflow as wf

        before = wf._WORKFLOW_REG_VER
        wf._workflow_tool_registry_cache = [{"x": 1}]
        with patch(
            "app.mod_sdk.employee_tool_registry.invalidate_employee_tool_cache",
            return_value=None,
            create=True,
        ):
            wf.invalidate_workflow_tool_registry()
        assert before + 1 == wf._WORKFLOW_REG_VER
        assert wf._workflow_tool_registry_cache is None

    def test_employee_cache_invalidate_error_swallowed(self):
        import app.application.tools.workflow as wf

        before = wf._WORKFLOW_REG_VER
        # ImportError is in RECOVERABLE_ERRORS → suppressed at 492-493.
        with patch(
            "app.mod_sdk.employee_tool_registry.invalidate_employee_tool_cache",
            side_effect=ImportError("no cache module"),
            create=True,
        ):
            wf.invalidate_workflow_tool_registry()
        # Version still bumped despite the error.
        assert before + 1 == wf._WORKFLOW_REG_VER
        assert wf._workflow_tool_registry_cache is None


# ---------------------------------------------------------------------------
# execute_workflow_tool — native planner dispatch error swallowed (569-570)
# ---------------------------------------------------------------------------


class TestExecuteNativePlannerErrorSwallowed:
    def test_native_planner_error_falls_through(self):
        from app.application.tools.workflow import execute_workflow_tool

        with (
            patch(
                "app.mod_sdk.employee_tool_registry.is_employee_tool",
                return_value=False,
                create=True,
            ),
            # RuntimeError ∈ RECOVERABLE_ERRORS → caught at 569-570, continues on.
            patch(
                "app.mod_sdk.planner_native_tools.try_execute_native_planner_tool",
                side_effect=RuntimeError("native boom"),
                create=True,
            ),
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                return_value=None,
                create=True,
            ),
        ):
            result = execute_workflow_tool("excel_chart_recommend", {})
        parsed = json.loads(result)
        assert "suggestions" in parsed


# ---------------------------------------------------------------------------
# execute_workflow_tool — legacy employee planner returns raw / errors (586-588)
# ---------------------------------------------------------------------------


class TestExecuteLegacyEmployeePlanner:
    def test_legacy_planner_returns_raw_short_circuits(self):
        from app.application.tools.workflow import execute_workflow_tool

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
                return_value='{"legacy": "ok"}',
                create=True,
            ),
        ):
            result = execute_workflow_tool("some_legacy_tool", {})
        # Raw returned directly (line 586) — not the unknown_tool fallthrough.
        assert result == '{"legacy": "ok"}'

    def test_legacy_planner_error_swallowed(self):
        from app.application.tools.workflow import execute_workflow_tool

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
            # OSError ∈ RECOVERABLE_ERRORS → caught at 587-588, continues to fallthrough.
            patch(
                "app.application.employee_pack_runner.try_execute_employee_planner_tool",
                side_effect=OSError("planner boom"),
                create=True,
            ),
        ):
            result = execute_workflow_tool("totally_unknown_tool", {})
        parsed = json.loads(result)
        assert parsed["error"] == "unknown_tool"
        assert parsed["tool"] == "totally_unknown_tool"


# ---------------------------------------------------------------------------
# excel_join_compare — except RECOVERABLE_ERRORS (678-679)
# ---------------------------------------------------------------------------


class TestJoinCompareException:
    def test_read_excel_raises_recoverable_returns_error(self, tmp_path):
        from app.application.tools.workflow import execute_workflow_tool

        p1 = tmp_path / "a.xlsx"
        p2 = tmp_path / "b.xlsx"
        pd.DataFrame({"id": [1]}).to_excel(p1, index=False)
        pd.DataFrame({"id": [1]}).to_excel(p2, index=False)
        # pd.read_excel raises ValueError ∈ RECOVERABLE_ERRORS → caught at 678-679.
        with patch(
            "app.application.tools.workflow.pd.read_excel",
            side_effect=ValueError("corrupt workbook"),
        ):
            result = execute_workflow_tool(
                "excel_join_compare",
                {"action": "join", "file_paths": [str(p1), str(p2)], "join_keys": ["id"]},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "corrupt workbook" in parsed["error"]


# ---------------------------------------------------------------------------
# excel_prophet — except RECOVERABLE_ERRORS (736-737)
# ---------------------------------------------------------------------------


class TestProphetException:
    def test_read_failure_returns_forecast_error(self, tmp_path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"y": [1, 2, 3]}).to_excel(p, index=False)
        # OSError ∈ RECOVERABLE_ERRORS → caught at 736-737.
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=OSError("disk gone"),
        ):
            result = execute_workflow_tool(
                "excel_prophet",
                {"file_path": str(p), "value_column": "y"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["action"] == "forecast"
        assert parsed["future_forecast"] == []
        assert "disk gone" in parsed["error"]


# ---------------------------------------------------------------------------
# excel_schema_understand — except RECOVERABLE_ERRORS (763-764)
# ---------------------------------------------------------------------------


class TestSchemaUnderstandException:
    def test_read_failure_returns_error_message(self, tmp_path):
        from app.application.tools.workflow import execute_workflow_tool

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1]}).to_excel(p, index=False)
        # ValueError ∈ RECOVERABLE_ERRORS → caught at 763-764.
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=ValueError("schema read fail"),
        ):
            result = execute_workflow_tool(
                "excel_schema_understand",
                {"file_path": str(p)},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "schema read fail" in parsed["error"]
        assert "读取 Excel 文件失败" in parsed["message"]


# ---------------------------------------------------------------------------
# _handle_import_excel_to_database — sheet_name resolution branches (898-910)
# ---------------------------------------------------------------------------


class TestHandleImportSheetResolution:
    def test_sheet_from_selected_sheet_context(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        with pd.ExcelWriter(p) as writer:
            pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(
                writer, sheet_name="Sheet1", index=False
            )
            pd.DataFrame({"产品名称": ["B"], "数量": [2]}).to_excel(
                writer, sheet_name="Target", index=False
            )
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    # Triggers lines 896-900.
                    "context": {"excel_analysis_selected_sheet": {"sheet_name": "Target"}},
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        # "Target" sheet has product "B" — confirm correct sheet was read.
        assert parsed["sample_data"][0]["name"] == "B"

    def test_sheet_from_preview_data_context(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        with pd.ExcelWriter(p) as writer:
            pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(
                writer, sheet_name="Sheet1", index=False
            )
            pd.DataFrame({"产品名称": ["Z"], "数量": [9]}).to_excel(
                writer, sheet_name="FromPreview", index=False
            )
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    # excel_analysis ctx with preview_data.sheet_name → lines 905-910.
                    "excel_analysis": {"preview_data": {"sheet_name": "FromPreview"}},
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["sample_data"][0]["name"] == "Z"


# ---------------------------------------------------------------------------
# _handle_import_excel_to_database — unit_name resolution (950, 964-977, 986-987)
# ---------------------------------------------------------------------------


class TestHandleImportUnitNameResolution:
    def test_unit_from_excel_analysis_customer_hint(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(p, index=False)
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    # excel_analysis.customer_hint → line 950.
                    "excel_analysis": {"customer_hint": "提示客户公司"},
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["detected_unit"] == "提示客户公司"

    def test_unit_from_linked_grid_inline_hits(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(p, index=False)
        with (
            patch("app.application.tools.workflow.configured_db_write_token", return_value=""),
            # Lines 956-975: linked grid preview text → inline customer hits.
            patch(
                "app.application.template_grid_core._extract_inline_customer_hits_from_cell",
                return_value=["内联客户名"],
            ),
        ):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    "context": {
                        "excel_linked_grid_preview": {"preview_text": "客户：某某公司"},
                        "excel_linked_grid_previews": [
                            {"preview_text": "another"},
                            "not-a-dict",
                        ],
                    },
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["detected_unit"] == "内联客户名"

    def test_unit_from_excel_hint_extractor(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(p, index=False)
        with (
            patch("app.application.tools.workflow.configured_db_write_token", return_value=""),
            # Lines 979-985: fallback to _extract_customer_hint_from_excel.
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="表内提取客户",
            ),
        ):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "products", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["detected_unit"] == "表内提取客户"

    def test_unit_extractor_error_swallowed(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(p, index=False)
        with (
            patch("app.application.tools.workflow.configured_db_write_token", return_value=""),
            # OSError ∈ RECOVERABLE_ERRORS → lines 986-987 swallow.
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                side_effect=OSError("hint extract boom"),
            ),
        ):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "products", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        # No unit resolved, but the call still produces a preview.
        assert parsed["success"] is True
        assert parsed["detected_unit"] in (None, "")


# ---------------------------------------------------------------------------
# _handle_import — header detection from excel_analysis ctx (996-1004)
# ---------------------------------------------------------------------------


class TestHandleImportHeaderDetection:
    def test_header_detected_from_excel_analysis_ctx(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        # Row 0 is junk title; real header on Excel row 2.
        pd.DataFrame([["报价单标题", "占位"], ["产品名称", "数量"], ["A", 1], ["B", 2]]).to_excel(
            p, index=False, header=False
        )
        with (
            patch("app.application.tools.workflow.configured_db_write_token", return_value=""),
            # Force header detection to row 2 via the session_context helper (lines 996-1002).
            patch(
                "app.domain.context.session_context.detected_excel_header_row_1based",
                return_value=2,
            ),
        ):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    "excel_analysis": {"some": "ctx"},
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        # read_options reflects the detected header row.
        assert parsed["read_options"]["header_row"] == 2

    def test_header_detection_error_swallowed(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [1]}).to_excel(p, index=False)
        with (
            patch("app.application.tools.workflow.configured_db_write_token", return_value=""),
            # ValueError ∈ RECOVERABLE_ERRORS → lines 1003-1004 set header_1b=None.
            patch(
                "app.domain.context.session_context.detected_excel_header_row_1based",
                side_effect=ValueError("detect boom"),
            ),
        ):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    "excel_analysis": {"some": "ctx"},
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["read_options"]["header_row"] is None


# ---------------------------------------------------------------------------
# _handle_import — last_data_row parse / slice (1029-1030, 1045)
# ---------------------------------------------------------------------------


class TestHandleImportLastDataRow:
    def test_last_data_row_invalid_string_ignored(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A", "B", "C"], "数量": [1, 2, 3]}).to_excel(p, index=False)
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    # "abc" → int() raises ValueError → last_data_i=None (lines 1029-1030).
                    "last_data_row_1based": "abc",
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        # No truncation applied → all 3 product rows present.
        assert parsed["row_count"] == 3
        assert parsed["read_options"]["last_data_row_applied"] is None

    def test_last_data_row_truncates_rows(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        # Header on Excel row 1; data rows 2..5 (4 product rows).
        pd.DataFrame({"产品名称": ["A", "B", "C", "D"], "数量": [1, 2, 3, 4]}).to_excel(
            p, index=False
        )
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {
                    "file_path": str(p),
                    "import_type": "products",
                    "preview_only": True,
                    # last_data_row=3 with header at row 1 → keep 3-1=2 rows (line 1045).
                    "last_data_row_1based": 3,
                },
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is True
        names = [r["name"] for r in parsed["sample_data"]]
        assert names == ["A", "B"]
        assert parsed["read_options"]["last_data_row_applied"] == 3


# ---------------------------------------------------------------------------
# _handle_import — customers/orders dispatch (1067, 1069)
# ---------------------------------------------------------------------------


class TestHandleImportTypeDispatch:
    def test_customers_dispatch(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"客户名称": ["甲公司"], "电话": ["13800000000"]}).to_excel(p, index=False)
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "customers", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        # Dispatched to _import_customers_preview_or_execute (line 1067).
        assert parsed["import_type"] == "customers"
        assert parsed["preview"] is True

    def test_orders_dispatch(self, tmp_path):
        from app.application.tools.workflow import _handle_import_excel_to_database

        p = tmp_path / "data.xlsx"
        pd.DataFrame({"产品名称": ["A"], "数量": [3], "购买单位": ["ACME"]}).to_excel(
            p, index=False
        )
        with patch("app.application.tools.workflow.configured_db_write_token", return_value=""):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "orders", "preview_only": True},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        # Dispatched to _import_orders_preview_or_execute (line 1069).
        assert parsed["import_type"] == "orders"
        assert parsed["preview"] is True


# ---------------------------------------------------------------------------
# _excel_cell_as_clean_str — error / float-nan branches (1220, 1223)
# ---------------------------------------------------------------------------


class TestExcelCellAsCleanStrEdge:
    def test_isna_ambiguous_array_falls_through_to_str(self):
        import numpy as np

        from app.application.tools.workflow import _excel_cell_as_clean_str

        # `if pd.isna(val):` over a multi-element array raises ValueError ("ambiguous
        # truth value") ∈ RECOVERABLE_ERRORS → caught at line 1220, then str() at 1231.
        out = _excel_cell_as_clean_str(np.array([1, 2]))
        assert out == "[1 2]"

    def test_float_literal_nan_returns_empty(self):
        from app.application.tools.workflow import _excel_cell_as_clean_str

        # float NaN: the explicit val != val guard (1222-1223) returns "".
        assert _excel_cell_as_clean_str(float("nan")) == ""


# ---------------------------------------------------------------------------
# _excel_cell_as_float — isna error / nan-after-float branches (1242-1248)
# ---------------------------------------------------------------------------


class TestExcelCellAsFloatEdge:
    def test_isna_ambiguous_array_then_float_fails_returns_default(self):
        import numpy as np

        from app.application.tools.workflow import _excel_cell_as_float

        # `if pd.isna(val):` over a 2-element array raises ValueError ("ambiguous")
        # ∈ RECOVERABLE_ERRORS → caught at 1242-1243; then float(array) raises
        # TypeError → caught at 1250-1251 → default returned.
        assert _excel_cell_as_float(np.array([1, 2]), default=4.0) == 4.0

    def test_numpy_scalar_converts(self):
        import numpy as np

        from app.application.tools.workflow import _excel_cell_as_float

        # numpy float64 scalar: pd.isna → False, float() succeeds.
        assert _excel_cell_as_float(np.float64(9.0)) == pytest.approx(9.0)

    def test_nan_after_float_returns_default(self):
        from app.application.tools.workflow import _excel_cell_as_float

        # float("nan") string path: float() → nan, v != v True → default (1247-1248).
        assert _excel_cell_as_float("nan", default=3.0) == 3.0


# ---------------------------------------------------------------------------
# _looks_like_contract_or_footer_line — numbered clause regex (1294, 1296)
# ---------------------------------------------------------------------------


class TestLooksLikeContractNumbered:
    def test_numbered_clause_with_clause_substring(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        # "1、" prefix, rest contains a clause substring (含税) → line 1293-1294 True.
        assert _looks_like_contract_or_footer_line("1、本报价均为含税价格说明")

    def test_numbered_clause_with_regex_keyword(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        # "2、" prefix, rest matches the keyword regex (验收) → line 1295-1296 True.
        assert _looks_like_contract_or_footer_line("2、货到后请于三日内完成验收手续")

    def test_numbered_clause_plain_not_footer(self):
        from app.application.tools.workflow import _looks_like_contract_or_footer_line

        # Numbered but rest is a plain product description → not a footer.
        assert not _looks_like_contract_or_footer_line("1、不锈钢螺丝规格齐全现货")


# ---------------------------------------------------------------------------
# _import_products_preview_or_execute — detected_unit / spec / qty (1314-1344)
# ---------------------------------------------------------------------------


class TestImportProductsBranches:
    def test_detected_unit_from_single_unit_column(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        # unit_name empty + single unique value in 单位 column → detected_unit set (1313-1316).
        df = pd.DataFrame({"产品名称": ["A", "B"], "单位": ["甲公司", "甲公司"], "数量": [1, 2]})
        result = json.loads(
            _import_products_preview_or_execute(df, list(df.columns), "", False, len(df))
        )
        assert result["preview"] is True
        assert result["detected_unit"] == "甲公司"

    def test_detected_unit_not_set_when_multiple_units(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        # Two distinct unit values → no single detected unit.
        df = pd.DataFrame({"产品名称": ["A", "B"], "单位": ["甲", "乙"], "数量": [1, 2]})
        result = json.loads(
            _import_products_preview_or_execute(df, list(df.columns), "", False, len(df))
        )
        # detected_unit stays falsy; the actual unit per record falls back to default.
        assert not result["detected_unit"]

    def test_spec_falls_back_to_model_column(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        # No 规格 column, but 型号 present → spec_val taken from model_col (line 1327).
        df = pd.DataFrame({"产品名称": ["螺丝"], "型号": ["M8x20"], "数量": [10]})
        result = json.loads(
            _import_products_preview_or_execute(df, list(df.columns), "客户", False, len(df))
        )
        sample = result["sample_data"][0]
        assert sample["specification"] == "M8x20"

    def test_qty_non_numeric_defaults_zero(self):
        from app.application.tools.workflow import _import_products_preview_or_execute

        # Quantity that cannot be int-cast → qty defaults (lines 1339-1344 path).
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["X"], "数量": ["abc"]})
        result = json.loads(
            _import_products_preview_or_execute(df, list(df.columns), "客户", False, len(df))
        )
        sample = result["sample_data"][0]
        assert sample["quantity"] == 0


# ---------------------------------------------------------------------------
# _import_orders_preview_or_execute — per-row exception (1610-1611)
# ---------------------------------------------------------------------------


class TestImportOrdersPerRowException:
    def test_per_row_exception_counts_as_failed(self):
        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A", "B"], "数量": [1, 2], "购买单位": ["ACME", "ACME"]})
        mock_svc = MagicMock()
        # First row raises OSError ∈ RECOVERABLE_ERRORS (caught at 1610-1611 → failed += 1),
        # second row succeeds.
        mock_svc.create_shipment.side_effect = [
            OSError("ship boom"),
            {"success": True},
        ]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc, create=True):
            result = json.loads(
                _import_orders_preview_or_execute(df, list(df.columns), "ACME", True, len(df))
            )
        assert result["success"] is True
        assert result["imported"] == 1
        assert result["failed"] == 1

    def test_outer_service_error_swallowed(self):
        from app.application.tools.workflow import _import_orders_preview_or_execute

        df = pd.DataFrame({"产品名称": ["A"], "数量": [1], "购买单位": ["ACME"]})
        # get_shipment_app_service itself raising → outer except (1623-1626).
        with patch(
            "app.bootstrap.get_shipment_app_service",
            side_effect=RuntimeError("no shipment svc"),
            create=True,
        ):
            result = json.loads(
                _import_orders_preview_or_execute(df, list(df.columns), "ACME", True, len(df))
            )
        assert result["success"] is False
        assert "订单导入失败" in result["error"]
