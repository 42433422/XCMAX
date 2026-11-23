"""COVERAGE_RAMP Phase 6 round 13: backend low-coverage modules.

Targets:
- ``app/application/ai_chat_app_service.py`` (81.0% line coverage, 230 uncovered lines)
- ``app/application/workflow/planner.py`` (77.0% line coverage, 151 uncovered lines)
- ``app/application/tools/workflow.py`` (82.1% line coverage, 121 uncovered lines)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (DB / external
API / LLM / file IO). The handler functions themselves are exercised through
real calls.

Coverage scenarios per 铁律3:
- Happy path (valid input)
- Empty / None input
- Boundary values (empty list, empty dict, empty string)
- Exception paths (RECOVERABLE_ERRORS: RuntimeError, ValueError, httpx errors)
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd
import pytest

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.tools.workflow import (
    _excel_cell_as_clean_str,
    _excel_cell_as_float,
    _handle_import_excel_to_database,
    _import_customers_preview_or_execute,
    _import_orders_preview_or_execute,
    _import_products_preview_or_execute,
    _infer_product_field_mapping,
    _looks_like_contract_or_footer_line,
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    handle_excel_analysis,
    invalidate_workflow_tool_registry,
    run_natural_language_pandas,
)
from app.application.workflow.planning_graph_policy import filter_registry_for_profile
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, validate_plan_graph
from app.services.tools_execution.registry import get_workflow_tool_registry as get_tool_registry
from tests.fixtures.planner_model import goal_review_response

# ===========================================================================
# 1. app/application/ai_chat_app_service.py
# ===========================================================================


# ===========================================================================
# 2. app/application/workflow/planner.py
# ===========================================================================


class TestGetToolRegistryPlanner:
    """Cover get_tool_registry from planner."""

    def test_returns_dict_with_tools(self) -> None:
        reg = get_tool_registry()
        assert isinstance(reg, dict)
        assert "products" in reg
        assert "customers" in reg
        assert "shipment_orders" in reg
        assert "shipment_records" in reg

    def test_tool_has_required_fields(self) -> None:
        reg = get_tool_registry()
        for tool_id, spec in reg.items():
            assert "description" in spec, f"{tool_id} missing description"
            assert "availability" in spec, f"{tool_id} missing availability"
            assert "actions" in spec, f"{tool_id} missing actions"
            assert isinstance(spec["actions"], dict)


class TestFilterToolRegistryForProfile:
    """Cover filter_registry_for_profile."""

    def test_non_dict_actions_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": "not a dict",
            },
        }
        result = filter_registry_for_profile(reg, "normal")
        assert "tool_a" not in result

    def test_non_dict_action_meta_skipped(self) -> None:
        reg = {
            "tool_a": {
                "availability": "shared",
                "actions": {"query": "not a dict"},
            },
        }
        result = filter_registry_for_profile(reg, "normal")
        assert "tool_a" not in result


# ===========================================================================
# 3. app/application/tools/workflow.py
# ===========================================================================


class TestParseExcelHeaderRow1based:
    """Cover _parse_excel_header_row_1based."""

    def test_with_header_row(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 3}) == 3

    def test_with_header_row_index(self) -> None:
        assert _parse_excel_header_row_1based({"header_row_index": 2}) == 2

    def test_header_row_takes_precedence(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 3, "header_row_index": 2}) == 3

    def test_none_value(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": None}) is None

    def test_empty_string(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": ""}) is None

    def test_invalid_string(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": "abc"}) is None

    def test_zero_returns_none(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": 0}) is None

    def test_negative_returns_none(self) -> None:
        assert _parse_excel_header_row_1based({"header_row": -1}) is None

    def test_missing_key(self) -> None:
        assert _parse_excel_header_row_1based({}) is None


class TestExcelCellAsCleanStr:
    """Cover _excel_cell_as_clean_str."""

    def test_none(self) -> None:
        assert _excel_cell_as_clean_str(None) == ""

    def test_bool(self) -> None:
        assert _excel_cell_as_clean_str(True) == ""

    def test_nan_float(self) -> None:
        assert _excel_cell_as_clean_str(float("nan")) == ""

    def test_integer(self) -> None:
        assert _excel_cell_as_clean_str(42) == "42"

    def test_float_integer_value(self) -> None:
        assert _excel_cell_as_clean_str(3.0) == "3"

    def test_float_decimal(self) -> None:
        assert _excel_cell_as_clean_str(3.14) == "3.14"

    def test_inf_float(self) -> None:
        assert _excel_cell_as_clean_str(float("inf")) == ""

    def test_nan_string(self) -> None:
        assert _excel_cell_as_clean_str("nan") == ""

    def test_none_string(self) -> None:
        assert _excel_cell_as_clean_str("none") == ""

    def test_null_string(self) -> None:
        assert _excel_cell_as_clean_str("null") == ""

    def test_normal_string(self) -> None:
        assert _excel_cell_as_clean_str("hello") == "hello"

    def test_string_with_whitespace(self) -> None:
        assert _excel_cell_as_clean_str("  hello  ") == "hello"


class TestExcelCellAsFloat:
    """Cover _excel_cell_as_float."""

    def test_none(self) -> None:
        assert _excel_cell_as_float(None) == 0.0

    def test_nan_float(self) -> None:
        assert _excel_cell_as_float(float("nan")) == 0.0

    def test_integer(self) -> None:
        assert _excel_cell_as_float(42) == 42.0

    def test_float(self) -> None:
        assert _excel_cell_as_float(3.14) == 3.14

    def test_string_number(self) -> None:
        assert _excel_cell_as_float("3.14") == 3.14

    def test_invalid_string(self) -> None:
        assert _excel_cell_as_float("abc") == 0.0

    def test_with_custom_default(self) -> None:
        assert _excel_cell_as_float(None, default=-1.0) == -1.0

    def test_nan_result_returns_default(self) -> None:
        assert _excel_cell_as_float(float("nan"), default=5.0) == 5.0


class TestLooksLikeContractOrFooterLine:
    """Cover _looks_like_contract_or_footer_line."""

    def test_short_text_returns_false(self) -> None:
        assert _looks_like_contract_or_footer_line("短") is False

    def test_empty_returns_false(self) -> None:
        assert _looks_like_contract_or_footer_line("") is False

    def test_with_clause_substring(self) -> None:
        assert _looks_like_contract_or_footer_line("以上价格为含税价") is True

    def test_with_numbered_clause(self) -> None:
        assert _looks_like_contract_or_footer_line("1、以上各种产品请严格按说明施工") is True

    def test_normal_product_name(self) -> None:
        assert _looks_like_contract_or_footer_line("产品A型号M123") is False

    def test_numbered_clause_without_keywords(self) -> None:
        assert _looks_like_contract_or_footer_line("1、普通说明文字内容") is False


class TestInferProductFieldMapping:
    """Cover _infer_product_field_mapping."""

    def test_typical_columns(self) -> None:
        cols = ["产品名称", "型号", "规格", "单价", "单位", "数量", "备注", "品牌", "类别"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("name") == "产品名称"
        assert mapping.get("model_number") == "型号"
        assert mapping.get("specification") == "规格"
        assert mapping.get("price") == "单价"
        assert mapping.get("unit") == "单位"

    def test_with_price_column_hint(self) -> None:
        cols = ["调价前单价", "调价后单价"]
        mapping = _infer_product_field_mapping(cols, price_column_hint="调价前")
        assert mapping.get("price") == "调价前单价"

    def test_empty_columns(self) -> None:
        mapping = _infer_product_field_mapping([])
        assert mapping == {}

    def test_english_columns(self) -> None:
        cols = ["name", "model", "price", "quantity", "unit"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("name") == "name"
        assert mapping.get("model_number") == "model"

    def test_sku_column(self) -> None:
        cols = ["SKU", "name"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("model_number") == "SKU"

    def test_bian_hao_column(self) -> None:
        cols = ["编号", "name"]
        mapping = _infer_product_field_mapping(cols)
        assert mapping.get("model_number") == "编号"

    def test_spec_excluded_from_model(self) -> None:
        # ``规格型号`` contains ``型号`` so it IS mapped to model_number.
        # ``规格`` alone (without 号/编) is skipped from model_number and
        # mapped to specification instead.
        cols_with_hao = ["规格型号", "name"]
        mapping = _infer_product_field_mapping(cols_with_hao)
        # 规格型号 contains 型号 → mapped to model_number
        assert mapping.get("model_number") == "规格型号"

        cols_plain = ["规格", "name"]
        mapping2 = _infer_product_field_mapping(cols_plain)
        # 规格 (no 号/编) is skipped from model_number, mapped to specification
        assert mapping2.get("model_number") is None
        assert mapping2.get("specification") == "规格"


class TestHandleExcelAnalysis:
    """Cover handle_excel_analysis branches."""

    def test_missing_file_path(self) -> None:
        result = handle_excel_analysis({})
        assert result["success"] is False
        assert "file_path" in result["error"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = handle_excel_analysis(
            {"file_path": "missing.xlsx", "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert result["error"] == "file not found"

    def test_unsupported_action(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "weird"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is False
        assert "unsupported_action" in result["error"]

    def test_action_read(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "read"
        assert result["row_count"] == 3

    def test_action_read_with_header_row(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"unnamed": ["header_note", 1, 2], "a": ["A", 10, 20]}).to_excel(
            p, index=False
        )
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "read", "header_row": 2},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result.get("header_row") == 2

    def test_action_query_with_expression(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3, 4]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query", "query_expression": "a > 2"},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_query_without_expression(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "query"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["row_count"] == 2

    def test_action_aggregate_with_group_by(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"category": ["A", "A", "B"], "amount": [10, 20, 30]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["category"],
                "metrics": [{"column": "amount", "op": "sum"}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["action"] == "aggregate"

    def test_action_aggregate_no_group_by(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "aggregate", "metrics": [{"column": "a", "op": "sum"}]},
            workspace_root=str(tmp_path),
        )
        assert result["success"] is True
        assert result["records"] == [{"a_sum": 3}]

    def test_action_aggregate_invalid_metrics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {
                "file_path": str(p),
                "action": "aggregate",
                "group_by": ["a"],
                "metrics": ["not_a_dict", {"column": "", "op": ""}],
            },
            workspace_root=str(tmp_path),
        )
        assert result["success"] is False
        assert result["error"] == "invalid_aggregation_metrics"

    def test_action_statistics(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "statistics"}, workspace_root=str(tmp_path)
        )
        assert result["success"] is True
        assert result["action"] == "statistics"
        assert "dtypes" in result

    def test_action_excel_query(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = handle_excel_analysis(
            {"file_path": str(p), "action": "excel_query", "natural_language": "select all"},
            workspace_root=str(tmp_path),
        )
        assert result["action"] == "excel_query"

    def test_read_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not an excel file")
        with patch(
            "app.application.tools.workflow._read_excel_dataframe",
            side_effect=ValueError("bad excel"),
        ):
            result = handle_excel_analysis(
                {"file_path": str(p), "action": "read"}, workspace_root=str(tmp_path)
            )
            assert result["success"] is False
        assert result["error"] == "read_excel_failed"


class TestRunNaturalLanguagePandas:
    """Cover run_natural_language_pandas."""

    def test_empty_df(self) -> None:
        df = pd.DataFrame()
        with patch("app.application.tools.workflow.adapters.translate_pandas", return_value=None):
            result = run_natural_language_pandas(df, "select all")
        assert result["row_count"] == 0
        assert result["result_kind"] == "dataframe"

    def test_with_valid_df(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        with patch("app.application.tools.workflow.adapters.translate_pandas", return_value=None):
            result = run_natural_language_pandas(df, "select all")
        assert result["row_count"] == 3
        assert "columns" in result

    def test_with_error(self) -> None:
        df = pd.DataFrame({"a": [1, 2]})
        with patch(
            "app.application.tools.workflow.adapters.translate_pandas",
            side_effect=RuntimeError("llm unavailable"),
        ):
            result = run_natural_language_pandas(df, "select all")
        assert result["error"] == "excel_query_failed"
        assert result["row_count"] == 2

    def test_truncation(self) -> None:
        df = pd.DataFrame({"a": list(range(300))})
        with patch("app.application.tools.workflow.adapters.translate_pandas", return_value=None):
            result = run_natural_language_pandas(df, "select all", max_rows=200)
        assert result["truncated"] is True
        assert result["returned_rows"] == 200
        assert result["next_offset"] == 200


class TestInvalidateWorkflowToolRegistry:
    """Cover invalidate_workflow_tool_registry."""

    def test_invalidates_cache(self) -> None:
        from app.application.tools import workflow as wf_mod

        wf_mod._workflow_tool_registry_cache = [{"cached": True}]
        invalidate_workflow_tool_registry()
        assert wf_mod._workflow_tool_registry_cache is None
        assert wf_mod._WORKFLOW_REG_VER > 2 or wf_mod._WORKFLOW_REG_VER == 3


class TestGetWorkflowToolRegistry:
    """Cover get_workflow_tool_registry."""

    def test_cache_hit(self) -> None:
        from app.application.tools import workflow as wf_mod

        # First call to populate cache
        reg1 = get_workflow_tool_registry()
        # Second call should return cached
        reg2 = get_workflow_tool_registry()
        assert reg1 is reg2

    def test_with_bulk_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.application.tools import workflow as wf_mod

        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "test_token")
        # Invalidate cache to force rebuild
        wf_mod._workflow_tool_registry_cache = None
        reg = get_workflow_tool_registry()
        names = [t["function"]["name"] for t in reg]
        assert "products_bulk_import" in names
        # Cleanup
        wf_mod._workflow_tool_registry_cache = None


class TestExecuteWorkflowTool:
    """Cover execute_workflow_tool dispatch."""

    def test_string_args_parsed(self) -> None:
        result = execute_workflow_tool("unknown", '{"x": 1}')
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_invalid_string_args(self) -> None:
        result = execute_workflow_tool("unknown", "not json")
        parsed = json.loads(result)
        assert parsed["success"] is False

    def test_unknown_tool(self) -> None:
        result = execute_workflow_tool("unknown_tool", {})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "unknown_tool"

    def test_excel_chart_recommend(self) -> None:
        result = execute_workflow_tool("excel_chart_recommend", {})
        parsed = json.loads(result)
        assert "suggestions" in parsed

    def test_excel_analysis_dispatch(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = execute_workflow_tool(
            "excel_analysis",
            {"file_path": str(p), "action": "read"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is True


class TestHandleImportExcelToDatabase:
    """Cover _handle_import_excel_to_database."""

    def test_missing_file_path(self) -> None:
        result = _handle_import_excel_to_database({})
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "file_path" in parsed["error"]

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = _handle_import_excel_to_database(
            {"file_path": "missing.xlsx", "import_type": "products"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "file not found"

    def test_with_token_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 设置了 FHD_DB_WRITE_TOKEN 且 workspace_root is None 时，源码 fail-closed：
        # 先做 token 鉴权（在文件存在性检查之前）。未提供 token → requires_token。
        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        result = _handle_import_excel_to_database(
            {"file_path": "/tmp/x.xlsx", "import_type": "products"},
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["requires_token"] is True
        assert parsed["token_name"] == "DB_WRITE_TOKEN"

    def test_with_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 提供了错误 token → 在文件检查之前即返回 invalid_token（fail-closed 安全门）。
        monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "secret")
        result = _handle_import_excel_to_database(
            {"file_path": "/tmp/x.xlsx", "import_type": "products", "db_write_token": "wrong"},
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_token"

    def test_empty_excel_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.xlsx"
        pd.DataFrame().to_excel(p, index=False)
        result = _handle_import_excel_to_database(
            {"file_path": str(p), "import_type": "products"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "empty" in parsed["error"]

    def test_invalid_last_data_row(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2, 3]}).to_excel(p, index=False)
        result = _handle_import_excel_to_database(
            {
                "file_path": str(p),
                "import_type": "products",
                "header_row": 3,
                "last_data_row_1based": 2,
            },
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["error"] == "invalid_last_data_row"

    def test_unknown_import_type(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1, 2]}).to_excel(p, index=False)
        result = _handle_import_excel_to_database(
            {"file_path": str(p), "import_type": "unknown_type"},
            workspace_root=str(tmp_path),
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True

    def test_read_excel_failure(self, tmp_path: Path) -> None:
        p = tmp_path / "data.xlsx"
        p.write_text("not excel")
        # The customer-hint extractor and _read_excel_dataframe both call
        # openpyxl.load_workbook which raises BadZipFile (not a
        # RECOVERABLE_ERROR) on non-xlsx files. We mock both to exercise the
        # read_excel_failed error path with a RECOVERABLE_ERROR.
        with (
            patch(
                "app.application.template_grid_core._extract_customer_hint_from_excel",
                return_value="",
            ),
            patch(
                "app.application.tools.workflow._read_excel_dataframe",
                side_effect=OSError("disk read failed"),
            ),
        ):
            result = _handle_import_excel_to_database(
                {"file_path": str(p), "import_type": "products"},
                workspace_root=str(tmp_path),
            )
        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "read_excel_failed" in parsed["error"]


class TestImportProductsPreviewOrExecute:
    """Cover _import_products_preview_or_execute."""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame({"产品名称": ["A", "B"], "型号": ["M1", "M2"], "单价": [10, 20]})
        result = _import_products_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "products"

    def test_with_clause_like_rows(self) -> None:
        df = pd.DataFrame(
            {
                "产品名称": ["产品A", "以上价格为含税价，请严格按说明施工"],
                "型号": ["M1", ""],
                "单价": [10, 0],
            }
        )
        result = _import_products_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["skipped_clause_like_rows"] >= 1

    def test_confirm_mode_with_service_error(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["M1"], "单价": [10]})
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no")):
            result = _import_products_preview_or_execute(
                df, list(df.columns), "客户A", confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_confirm_mode_success(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["M1"], "单价": [10]})
        with (
            patch(
                "app.domain.shared_services.unified_query_service.find_purchase_unit",
                return_value=None,
            ),
            patch("app.bootstrap.get_customer_app_service") as mock_cust,
            patch("app.bootstrap.get_products_service") as mock_prod,
        ):
            mock_cust_svc = MagicMock()
            mock_cust_svc.create.return_value = {"success": True}
            mock_cust.return_value = mock_cust_svc
            mock_prod_svc = MagicMock()
            mock_prod_svc.batch_add_products.return_value = {
                "success": True,
                "success_count": 1,
                "failed_count": 0,
            }
            mock_prod.return_value = mock_prod_svc
            result = _import_products_preview_or_execute(
                df, list(df.columns), "客户A", confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["imported"] == 1

    def test_empty_df(self) -> None:
        df = pd.DataFrame({"产品名称": [], "型号": [], "单价": []})
        result = _import_products_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=0
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["row_count"] == 0


class TestImportCustomersPreviewOrExecute:
    """Cover _import_customers_preview_or_execute."""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame(
            {
                "名称": ["客户A", "客户B"],
                "联系人": ["张三", "李四"],
                "电话": ["123", "456"],
                "地址": ["地址A", "地址B"],
            }
        )
        result = _import_customers_preview_or_execute(
            df, list(df.columns), confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "customers"

    def test_confirm_mode_success(self) -> None:
        df = pd.DataFrame({"名称": ["客户A"]})
        with patch("app.bootstrap.get_customer_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.create.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _import_customers_preview_or_execute(
                df, list(df.columns), confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["imported"] == 1

    def test_confirm_mode_with_error(self) -> None:
        df = pd.DataFrame({"名称": ["客户A"]})
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no")):
            result = _import_customers_preview_or_execute(
                df, list(df.columns), confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_empty_records(self) -> None:
        df = pd.DataFrame({"名称": []})
        result = _import_customers_preview_or_execute(
            df, list(df.columns), confirm=False, row_count=0
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["row_count"] == 0


class TestImportOrdersPreviewOrExecute:
    """Cover _import_orders_preview_or_execute."""

    def test_preview_mode(self) -> None:
        df = pd.DataFrame(
            {
                "产品名称": ["A", "B"],
                "型号": ["M1", "M2"],
                "数量": [1, 2],
                "购买单位": ["客户A", "客户B"],
            }
        )
        result = _import_orders_preview_or_execute(
            df, list(df.columns), "客户A", confirm=False, row_count=2
        )
        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["preview"] is True
        assert parsed["import_type"] == "orders"

    def test_confirm_mode_success(self) -> None:
        df = pd.DataFrame(
            {
                "产品名称": ["A"],
                "型号": ["M1"],
                "数量": [1],
                "购买单位": ["客户A"],
            }
        )
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _import_orders_preview_or_execute(
                df, list(df.columns), None, confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is True
            assert parsed["imported"] == 1

    def test_confirm_mode_with_error(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"]})
        with patch("app.bootstrap.get_shipment_app_service", side_effect=ImportError("no")):
            result = _import_orders_preview_or_execute(
                df, list(df.columns), None, confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False

    def test_confirm_mode_no_unit(self) -> None:
        df = pd.DataFrame({"产品名称": ["A"], "型号": ["M1"], "数量": [1]})
        with patch("app.bootstrap.get_shipment_app_service") as mock_get:
            mock_svc = MagicMock()
            mock_svc.create_shipment.return_value = {"success": True}
            mock_get.return_value = mock_svc
            result = _import_orders_preview_or_execute(
                df, list(df.columns), None, confirm=True, row_count=1
            )
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["imported"] == 0
            assert parsed["failed"] == 1
            mock_svc.create_shipment.assert_not_called()

    def test_empty_df(self) -> None:
        df = pd.DataFrame({"产品名称": []})
        result = _import_orders_preview_or_execute(
            df, list(df.columns), None, confirm=False, row_count=0
        )
        parsed = json.loads(result)
        assert parsed["success"] is True


@pytest.mark.parametrize(
    "message",
    [
        "你好",
        "查询产品",
        "",
        None,
        "hello there",
        "hi",
        "x" * 200,
        "导入",
        "导入Excel",
        "导入到数据库",
        "写入数据库",
        "帮我导入数据",
        "说明表格",
        "普通消息",
    ],
)
def test_unified_public_chat_never_turns_model_failure_or_import_words_into_success(message):
    from tests.test_application.ai_chat_test_helpers import _make_svc

    svc = _make_svc()
    with (
        patch.object(svc, "_persist_chat_turn"),
        patch.object(svc, "_persist_recallable_chat_turn"),
        patch("app.application.ai_chat.dialogue_memory.prepare_chat_turn", return_value=None),
        patch("app.application.ai_chat.dialogue_memory.settle_chat_turn"),
        patch(
            "app.application.agent_runtime.gateway.run_runtime_task",
            return_value={
                "ok": False,
                "business_completed": False,
                "verified_operations": False,
                "execution_state": "failed",
                "exit_status": "planning_unavailable",
                "error_code": "planning_unavailable",
                "error": "模型未返回可验证的任务目标",
            },
        ) as runtime,
    ):
        result = svc.process_chat("u1", message, source="pro")
    assert result["success"] is False
    assert not result.get("toolCall")
    assert not hasattr(svc, "workflow_planner")
    assert not hasattr(svc, "_pending_workflows")
    if message:
        runtime.assert_called_once()
        assert runtime.call_args.kwargs["task"] == message
        assert runtime.call_args.kwargs["completion_mode"] == "auto"
        assert result["execution_state"] == "failed"
        assert result["business_completed"] is False
        assert result["data"]["error_code"] == "planning_unavailable"
    else:
        runtime.assert_not_called()
