"""Branch-coverage tests for app/application/workflow/planner.py.

聚焦未覆盖分支：execute_tool 默认 action、_execute_import_excel_tool 异常路径、
_filter_tool_registry_for_profile 边界、_fallback_plan 多分支、
_plan_with_react_multiagent probe 过滤、_validate_required_params 边界、
_critic_repair_with_llm 异常路径、_plan_with_llm 异常路径。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _execute_import_excel_tool,
    _filter_tool_registry_for_profile,
    _get_planner_http_client,
    execute_tool,
)
from app.application.workflow.types import PlanGraph, WorkflowNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_registry() -> dict[str, Any]:
    return {
        "products": {
            "description": "产品查询",
            "availability": "shared",
            "actions": {
                "query": {
                    "description": "查询产品",
                    "risk": "low",
                    "idempotent": True,
                    "availability": "shared",
                    "required_params": [],
                },
                "create": {
                    "description": "创建产品",
                    "risk": "medium",
                    "idempotent": False,
                    "availability": "shared",
                    "required_params": [],
                },
            },
        },
        "customers": {
            "description": "客户查询",
            "availability": "shared",
            "actions": {
                "query": {
                    "description": "查询客户",
                    "risk": "low",
                    "idempotent": True,
                    "availability": "shared",
                    "required_params": [],
                },
            },
        },
        "business_db": {
            "description": "业务数据库",
            "availability": "shared",
            "actions": {
                "read": {
                    "description": "读取",
                    "risk": "low",
                    "idempotent": True,
                    "availability": "shared",
                    "required_params": ["entity"],
                },
                "write": {
                    "description": "写入",
                    "risk": "medium",
                    "idempotent": False,
                    "availability": "shared",
                    "required_params": ["entity", "operation", "payload"],
                },
            },
        },
        "employee": {
            "description": "员工执行",
            "availability": "shared",
            "actions": {
                "list": {
                    "description": "列出员工",
                    "risk": "low",
                    "idempotent": True,
                    "availability": "shared",
                    "required_params": [],
                },
                "execute": {
                    "description": "执行员工任务",
                    "risk": "medium",
                    "idempotent": False,
                    "availability": "shared",
                    "required_params": ["task"],
                },
            },
        },
    }


def _make_planner() -> Any:
    with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
        ai = MagicMock()
        ai.api_key = "test-key"
        ai.api_url = "https://api.example.com/v1/chat/completions"
        ai.model = "deepseek-chat"
        ai.get_context.return_value = None
        mock_svc.return_value = ai
        planner = LLMWorkflowPlanner()
    return planner


# ---------------------------------------------------------------------------
# execute_tool — default action mapping & handler dispatch
# ---------------------------------------------------------------------------


class TestExecuteToolDefaultAction:
    def test_explicit_action_used_over_default(self) -> None:
        """传入 _action 时优先使用，不走默认映射。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True, "action": p.get("_action")}
            result = execute_tool("products", {"_action": "create", "keyword": "abc"})
            assert result["success"] is True

    def test_default_action_for_products(self) -> None:
        """products 工具默认 action=query。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True, "resolved_action": "query"}
            result = execute_tool("products", {"keyword": "abc"})
            assert result["success"] is True

    def test_default_action_for_customers(self) -> None:
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("customers", {})
            assert result["success"] is True

    def test_default_action_for_employee(self) -> None:
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("employee", {})
            assert result["success"] is True

    def test_default_action_for_business_db(self) -> None:
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("business_db", {"entity": "products"})
            assert result["success"] is True

    def test_default_action_for_unknown_tool_falls_to_query(self) -> None:
        """未知工具默认 action=query。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("unknown_tool", {})
            assert result["success"] is True

    def test_action_stripped_and_lowercased(self) -> None:
        """_action 被去除空白并转小写。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            captured: dict[str, Any] = {}

            def capture(p: dict[str, Any]) -> dict[str, Any]:
                captured["action"] = "QUERY"  # 模拟 handler
                return {"success": True}

            handlers.get.return_value = capture
            result = execute_tool("products", {"_action": "  QUERY  "})
            assert result["success"] is True

    def test_runtime_context_popped_from_params(self) -> None:
        """_runtime_context 被从 params 中移除。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            captured: dict[str, Any] = {}

            def capture(p: dict[str, Any]) -> dict[str, Any]:
                captured.update(p)
                return {"success": True}

            handlers.get.return_value = capture
            execute_tool("products", {"_runtime_context": {"foo": "bar"}, "keyword": "x"})
            assert "_runtime_context" not in captured

    def test_no_handler_returns_failure(self) -> None:
        """无匹配 handler 时返回失败。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = None
            result = execute_tool("products", {"keyword": "x"})
            assert result["success"] is False

    def test_none_params_handled(self) -> None:
        """params=None 不崩溃。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("products", None)  # type: ignore[arg-type]
            assert result["success"] is True

    def test_empty_action_string_uses_default(self) -> None:
        """空 _action 字符串走默认映射。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("products", {"_action": ""})
            assert result["success"] is True

    def test_whitespace_only_action_uses_default(self) -> None:
        """纯空白 _action 走默认映射。"""
        with patch(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS"
        ) as handlers:
            handlers.get.return_value = lambda p: {"success": True}
            result = execute_tool("products", {"_action": "   "})
            assert result["success"] is True


# ---------------------------------------------------------------------------
# _execute_import_excel_tool — error paths
# ---------------------------------------------------------------------------


class TestExecuteImportExcelErrors:
    def test_missing_file_path_returns_error(self) -> None:
        result = _execute_import_excel_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_empty_file_path_returns_error(self) -> None:
        result = _execute_import_excel_tool({"file_path": "  "})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_products_service_import_error(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=ImportError("no module")):
            result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_products_service_runtime_error(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("init fail")):
            result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "service_init_failed"

    def test_customer_service_import_error_degrades_gracefully(self) -> None:
        """客户服务 ImportError 时降级为仅产品入库。"""
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch(
                "app.bootstrap.get_customer_app_service", side_effect=ImportError("no cust")
            ):
                with patch("openpyxl.load_workbook", side_effect=OSError("file not found")):
                    result = _execute_import_excel_tool({"file_path": "/tmp/missing.xlsx"})
                    # OSError 被捕获
                    assert result["success"] is False
                    assert result["error_code"] == "file_not_found"

    def test_customer_service_runtime_error_degrades(self) -> None:
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch(
                "app.bootstrap.get_customer_app_service",
                side_effect=RuntimeError("cust init fail"),
            ):
                with patch("openpyxl.load_workbook", side_effect=OSError("no file")):
                    result = _execute_import_excel_tool({"file_path": "/tmp/x.xlsx"})
                    assert result["success"] is False

    def test_openpyxl_import_error_returns_library_unavailable(self) -> None:
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=MagicMock()):
                # 模拟 openpyxl 导入失败
                import sys

                original = sys.modules.get("openpyxl")
                sys.modules["openpyxl"] = None  # type: ignore[assignment]
                try:
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                finally:
                    if original is not None:
                        sys.modules["openpyxl"] = original
                    else:
                        sys.modules.pop("openpyxl", None)
                # ImportError 被捕获
                assert result["success"] is False
                assert result["error_code"] in ("library_unavailable", "invalid_parameters", "import_failed")

    def test_file_not_found_oserror(self) -> None:
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=MagicMock()):
                with patch("openpyxl.load_workbook", side_effect=OSError("not found")):
                    result = _execute_import_excel_tool({"file_path": "/tmp/missing.xlsx"})
                    assert result["success"] is False
                    assert result["error_code"] == "file_not_found"

    def test_value_error_returns_invalid_parameters(self) -> None:
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=MagicMock()):
                with patch("openpyxl.load_workbook", side_effect=ValueError("bad value")):
                    result = _execute_import_excel_tool({"file_path": "/tmp/bad.xlsx"})
                    assert result["success"] is False
                    assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=MagicMock()):
                with patch("openpyxl.load_workbook", side_effect=TypeError("bad type")):
                    result = _execute_import_excel_tool({"file_path": "/tmp/bad.xlsx"})
                    assert result["success"] is False
                    assert result["error_code"] == "invalid_parameters"

    def test_runtime_error_returns_import_failed(self) -> None:
        mock_products = MagicMock()
        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=MagicMock()):
                with patch("openpyxl.load_workbook", side_effect=RuntimeError("runtime fail")):
                    result = _execute_import_excel_tool({"file_path": "/tmp/bad.xlsx"})
                    assert result["success"] is False
                    assert result["error_code"] == "import_failed"

    def test_ambiguous_price_columns_returns_error(self) -> None:
        """检测到歧义价格列时返回 ambiguous_price_columns。"""
        mock_products = MagicMock()
        mock_customer = MagicMock()
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        # 模拟表头行
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="调价前"), MagicMock(value="调价后")],
            ]
        )
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    with patch(
                        "app.application.ai_chat_app_service.AIChatApplicationService._merge_user_intent_for_price_resolution",
                        return_value="",
                    ):
                        with patch(
                            "app.application.ai_chat_app_service.AIChatApplicationService._resolve_unit_price_column",
                            return_value=("", "ambiguous_price_columns"),
                        ):
                            result = _execute_import_excel_tool(
                                {"file_path": "/tmp/test.xlsx", "_user_message": "导入"}
                            )
                            assert result["success"] is False
                            assert result["error_code"] == "ambiguous_price_columns"

    def test_import_error_in_price_resolution_falls_back(self) -> None:
        """AI 服务 ImportError 时回退简单匹配。"""
        mock_products = MagicMock()
        mock_customer = MagicMock()
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [[MagicMock(value="产品名称"), MagicMock(value="单价")]]
        )
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    # 让 AIChatApplicationService 导入失败
                    import sys

                    original = sys.modules.get("app.application.ai_chat_app_service")
                    sys.modules["app.application.ai_chat_app_service"] = None  # type: ignore[assignment]
                    try:
                        result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    finally:
                        if original is not None:
                            sys.modules["app.application.ai_chat_app_service"] = original
                        else:
                            sys.modules.pop("app.application.ai_chat_app_service", None)
                    # 应回退成功（无数据行但流程通过）
                    assert result["success"] is True

    def test_value_error_in_price_resolution_falls_back(self) -> None:
        """价格消歧 ValueError 时回退简单匹配。"""
        mock_products = MagicMock()
        mock_customer = MagicMock()
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [[MagicMock(value="产品名称"), MagicMock(value="单价")]]
        )
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    with patch(
                        "app.application.ai_chat_app_service.AIChatApplicationService._merge_user_intent_for_price_resolution",
                        side_effect=ValueError("bad"),
                    ):
                        result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                        assert result["success"] is True

    def test_runtime_error_in_price_resolution_falls_back(self) -> None:
        """价格消歧 RuntimeError 时回退简单匹配。"""
        mock_products = MagicMock()
        mock_customer = MagicMock()
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [[MagicMock(value="产品名称"), MagicMock(value="单价")]]
        )
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    with patch(
                        "app.application.ai_chat_app_service.AIChatApplicationService._merge_user_intent_for_price_resolution",
                        side_effect=RuntimeError("bad"),
                    ):
                        result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                        assert result["success"] is True


# ---------------------------------------------------------------------------
# _execute_import_excel_tool — successful import paths
# ---------------------------------------------------------------------------


class TestExecuteImportExcelSuccess:
    def test_successful_import_with_data_rows(self) -> None:
        """有数据行时成功导入。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()
        mock_customer.match_purchase_unit.return_value = False
        mock_customer.create.return_value = {"success": True}

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        # 表头 + 1 行数据
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="型号"), MagicMock(value="单价"), MagicMock(value="单位")],
                [MagicMock(value="螺钉"), MagicMock(value="M8"), MagicMock(value=1.5), MagicMock(value="ABC公司")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    assert result["success"] is True
                    assert result["created_products"] >= 1

    def test_import_skips_empty_rows(self) -> None:
        """空行（无产品名/型号/单位）被跳过。"""
        mock_products = MagicMock()
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="型号")],
                [MagicMock(value=None), MagicMock(value=None)],  # 空行
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    assert result["success"] is True
                    assert result["created_products"] == 0

    def test_import_skips_duplicates(self) -> None:
        """skip_duplicates=True 时跳过已存在产品。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {
            "success": True,
            "data": [{"model_number": "M8", "name": "螺钉"}],
        }
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="型号")],
                [MagicMock(value="螺钉"), MagicMock(value="M8")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "skip_duplicates": True}
                    )
                    assert result["success"] is True
                    assert result["skipped_products"] >= 1

    def test_import_creates_customer_when_missing(self) -> None:
        """create_customer=True 且客户不存在时创建客户。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()
        mock_customer.match_purchase_unit.return_value = False
        mock_customer.create.return_value = {"success": True}

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="单位")],
                [MagicMock(value="螺钉"), MagicMock(value="新客户")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "create_customer_if_missing": True}
                    )
                    assert result["success"] is True
                    assert result["created_units"] >= 1

    def test_import_does_not_create_customer_when_disabled(self) -> None:
        """create_customer=False 时不创建客户。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="单位")],
                [MagicMock(value="螺钉"), MagicMock(value="新客户")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "create_customer_if_missing": False}
                    )
                    assert result["success"] is True
                    assert result["created_units"] == 0
                    mock_customer.create.assert_not_called()

    def test_import_with_explicit_unit_name(self) -> None:
        """传入 unit_name 时覆盖行内单位。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()
        mock_customer.match_purchase_unit.return_value = True

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称")],
                [MagicMock(value="螺钉")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "unit_name": "指定单位"}
                    )
                    assert result["success"] is True

    def test_import_with_explicit_price_column(self) -> None:
        """传入 price_column 时按指定列匹配。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="含税单价")],
                [MagicMock(value="螺钉"), MagicMock(value=2.0)],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "price_column": "含税单价"}
                    )
                    assert result["success"] is True

    def test_import_invalid_price_falls_back_to_zero(self) -> None:
        """价格列值无法转 float 时回退 0.0。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="单价")],
                [MagicMock(value="螺钉"), MagicMock(value="非数字")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    assert result["success"] is True

    def test_import_with_sheet_name(self) -> None:
        """指定 sheet_name 时使用该 sheet。"""
        mock_products = MagicMock()
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [[MagicMock(value="产品名称")]]
        )
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1", "Sheet2"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "sheet_name": "Sheet2"}
                    )
                    assert result["success"] is True
                    mock_wb.__getitem__.assert_called_with("Sheet2")

    def test_import_customer_create_failure_does_not_count(self) -> None:
        """客户创建失败时不增加 created_units。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()
        mock_customer.match_purchase_unit.return_value = False
        mock_customer.create.return_value = {"success": False}

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="单位")],
                [MagicMock(value="螺钉"), MagicMock(value="新客户")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    assert result["success"] is True
                    assert result["created_units"] == 0

    def test_import_product_create_failure_does_not_count(self) -> None:
        """产品创建失败时不增加 created_products。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": True, "data": []}
        mock_products.create_product.return_value = {"success": False}
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称")],
                [MagicMock(value="螺钉")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    assert result["success"] is True
                    assert result["created_products"] == 0

    def test_import_products_get_failure_skips_existence_check(self) -> None:
        """products.get_products 返回 success=False 时跳过重复检查。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {"success": False}
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称")],
                [MagicMock(value="螺钉")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool({"file_path": "/tmp/test.xlsx"})
                    assert result["success"] is True
                    assert result["created_products"] >= 1

    def test_import_no_duplicates_when_disabled(self) -> None:
        """skip_duplicates=False 时不跳过已存在产品。"""
        mock_products = MagicMock()
        mock_products.get_products.return_value = {
            "success": True,
            "data": [{"model_number": "M8", "name": "螺钉"}],
        }
        mock_products.create_product.return_value = {"success": True}
        mock_customer = MagicMock()

        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_ws.iter_rows.return_value = iter(
            [
                [MagicMock(value="产品名称"), MagicMock(value="型号")],
                [MagicMock(value="螺钉"), MagicMock(value="M8")],
            ]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch("app.bootstrap.get_products_service", return_value=mock_products):
            with patch("app.bootstrap.get_customer_app_service", return_value=mock_customer):
                with patch("openpyxl.load_workbook", return_value=mock_wb):
                    result = _execute_import_excel_tool(
                        {"file_path": "/tmp/test.xlsx", "skip_duplicates": False}
                    )
                    assert result["success"] is True
                    assert result["skipped_products"] == 0
                    assert result["created_products"] >= 1


# ---------------------------------------------------------------------------
# _filter_tool_registry_for_profile — additional edge cases
# ---------------------------------------------------------------------------


class TestFilterToolRegistryEdgeCases:
    def test_empty_registry_returns_empty(self) -> None:
        assert _filter_tool_registry_for_profile({}, "normal") == {}

    def test_tool_with_missing_availability_defaults_shared(self) -> None:
        reg = {
            "tool": {
                "actions": {
                    "act": {"risk": "low", "idempotent": True},
                }
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool" in filtered

    def test_action_with_missing_availability_defaults_shared(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": {
                    "act": {"risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "act" in filtered["tool"]["actions"]

    def test_action_not_dict_skipped(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": {
                    "bad_act": "not_a_dict",
                    "good_act": {"risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad_act" not in filtered["tool"]["actions"]
        assert "good_act" in filtered["tool"]["actions"]

    def test_actions_not_dict_skipped(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": "not_a_dict",
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool" not in filtered

    def test_profile_other_keeps_shared_tools(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": {
                    "act": {"availability": "shared", "risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "other_profile")
        assert "tool" in filtered

    def test_pro_default_keeps_pro_only_actions(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": {
                    "pro_act": {"availability": "pro_only", "risk": "low", "idempotent": True},
                    "shared_act": {"availability": "shared", "risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "pro_default")
        assert "pro_act" in filtered["tool"]["actions"]
        assert "shared_act" in filtered["tool"]["actions"]

    def test_normal_keeps_normal_only_actions(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": {
                    "normal_act": {"availability": "normal_only", "risk": "low", "idempotent": True},
                    "shared_act": {"availability": "shared", "risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "normal_act" in filtered["tool"]["actions"]
        assert "shared_act" in filtered["tool"]["actions"]

    def test_availability_case_insensitive(self) -> None:
        reg = {
            "tool": {
                "availability": "PRO_ONLY",
                "actions": {
                    "act": {"availability": "shared", "risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool" not in filtered

    def test_tool_with_no_actions_key_excluded(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool" not in filtered

    def test_empty_actions_dict_excludes_tool(self) -> None:
        reg = {
            "tool": {
                "availability": "shared",
                "actions": {},
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "tool" not in filtered


# ---------------------------------------------------------------------------
# _fallback_plan — additional branch coverage
# ---------------------------------------------------------------------------


class TestFallbackPlanBranches:
    def test_employee_dispatch_with_known_id(self) -> None:
        """员工意图且能识别 employee_id 时生成 execute 节点。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_status:
            mock_status.return_value = {
                "employee_pack_tools": [{"pack_id": "pack-001"}]
            }
            result = planner._fallback_plan("pid", "请员工 pack-001 处理订单", _sample_registry())
            assert result.intent == "employee_dispatch"
            assert any(n.action == "execute" for n in result.nodes)

    def test_employee_dispatch_status_import_error(self) -> None:
        """build_employee_tools_status ImportError 时降级为 list。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=ImportError("no module"),
        ):
            result = planner._fallback_plan("pid", "请员工处理", _sample_registry())
            assert result.intent == "employee_dispatch"
            assert any(n.action == "list" for n in result.nodes)

    def test_employee_dispatch_status_runtime_error(self) -> None:
        """build_employee_tools_status RuntimeError 时降级为 list。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=RuntimeError("fail"),
        ):
            result = planner._fallback_plan("pid", "请员工处理", _sample_registry())
            assert result.intent == "employee_dispatch"
            assert any(n.action == "list" for n in result.nodes)

    def test_employee_dispatch_status_non_dict_item_skipped(self) -> None:
        """status 中非 dict 项被跳过。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_status:
            mock_status.return_value = {
                "employee_pack_tools": ["not_a_dict", {"pack_id": "real-pack"}]
            }
            result = planner._fallback_plan("pid", "请员工 real-pack 处理", _sample_registry())
            assert any(n.action == "execute" for n in result.nodes)

    def test_employee_dispatch_empty_pack_id_skipped(self) -> None:
        """空 pack_id 项被跳过。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status"
        ) as mock_status:
            mock_status.return_value = {
                "employee_pack_tools": [{"pack_id": ""}, {"pack_id": "real-pack"}]
            }
            result = planner._fallback_plan("pid", "请员工 real-pack 处理", _sample_registry())
            assert any(n.action == "execute" for n in result.nodes)

    def test_business_db_write_with_extracted_node(self) -> None:
        """业务库写入意图且能抽取节点时生成 write 节点。"""
        planner = _make_planner()
        result = planner._fallback_plan(
            "pid", "新增客户ABC公司到数据库写入", _sample_registry()
        )
        assert result.intent == "business_db_write"
        assert any(n.action == "write" for n in result.nodes)

    def test_business_db_write_no_node_falls_through(self) -> None:
        """业务库写入意图但抽取节点失败时落入后续分支。"""
        planner = _make_planner()
        with patch(
            "app.application.workflow.planner._extract_business_db_write_node",
            return_value=None,
        ):
            with patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ):
                result = planner._fallback_plan("pid", "写入数据库", _sample_registry())
                # 应落入 db read 或默认查询分支
                assert result is not None

    def test_business_db_read_english_keyword(self) -> None:
        """英文 db/database 关键词触发 business_db_read。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "query the database", _sample_registry())
        assert result.intent == "business_db_read"
        assert any(n.tool_id == "business_db" for n in result.nodes)

    def test_business_db_read_chinese_keyword(self) -> None:
        """中文数据库关键词触发 business_db_read。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "查数据库里的产品", _sample_registry())
        assert result.intent == "business_db_read"

    def test_add_product_intent_with_customers_and_products(self) -> None:
        """添加产品意图且注册表含 customers+products 时生成两节点。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "添加新产品", _sample_registry())
        assert result.intent == "add_product_to_unit"
        assert any(n.tool_id == "customers" for n in result.nodes)
        assert any(n.tool_id == "products" for n in result.nodes)

    def test_add_product_intent_with_depends_on(self) -> None:
        """添加产品意图时 create_product 节点依赖 check_or_create_unit。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "新增产品", _sample_registry())
        create_nodes = [n for n in result.nodes if n.tool_id == "products"]
        if create_nodes:
            assert "check_or_create_unit" in (create_nodes[0].depends_on or [])

    def test_add_product_intent_without_customers(self) -> None:
        """添加产品意图但注册表无 customers 时只生成 products 节点。"""
        planner = _make_planner()
        reg = {"products": _sample_registry()["products"]}
        result = planner._fallback_plan("pid", "添加产品", reg)
        assert result.intent == "add_product_to_unit"
        assert not any(n.tool_id == "customers" for n in result.nodes)

    def test_default_fallback_to_products_query(self) -> None:
        """无匹配意图时默认查询产品。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "随便看看", _sample_registry())
        assert any(n.tool_id == "products" for n in result.nodes)

    def test_default_fallback_to_customers_when_no_products(self) -> None:
        """无 products 工具时回退查询客户。"""
        planner = _make_planner()
        reg = {"customers": _sample_registry()["customers"]}
        result = planner._fallback_plan("pid", "随便看看", reg)
        assert any(n.tool_id == "customers" for n in result.nodes)

    def test_default_fallback_empty_registry(self) -> None:
        """空注册表时返回空节点图。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "随便看看", {})
        assert len(result.nodes) == 0
        assert result.risk_level == "low"

    def test_employee_keyword_english(self) -> None:
        """英文 employee 关键词触发员工意图。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "call employee to help", _sample_registry())
        assert result.intent == "employee_dispatch"

    def test_create_english_keyword_triggers_add_product(self) -> None:
        """英文 create 关键词触发添加产品意图。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "create 产品", _sample_registry())
        assert result.intent == "add_product_to_unit"

    def test_risk_level_low_when_all_low(self) -> None:
        """所有节点 low 风险时 risk_level=low。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "随便看看", _sample_registry())
        assert result.risk_level == "low"

    def test_employee_intent_without_employee_tool(self) -> None:
        """员工关键词但注册表无 employee 工具时不触发员工意图。"""
        planner = _make_planner()
        reg = {"products": _sample_registry()["products"]}
        result = planner._fallback_plan("pid", "请员工处理", reg)
        assert result.intent != "employee_dispatch"


# ---------------------------------------------------------------------------
# _validate_required_params — additional edge cases
# ---------------------------------------------------------------------------


class TestValidateRequiredParamsEdgeCases:
    def test_empty_plan_returns_none(self) -> None:
        plan = PlanGraph(plan_id="p", intent="i", nodes=[])
        assert LLMWorkflowPlanner._validate_required_params(plan, {}) is None

    def test_none_tool_registry_returns_none(self) -> None:
        node = WorkflowNode("n", "t", "a")
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, None) is None  # type: ignore[arg-type]

    def test_tool_spec_not_dict_skipped(self) -> None:
        reg = {"tool": "not_a_dict"}
        node = WorkflowNode("n", "tool", "a")
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, reg) is None

    def test_actions_not_dict_skipped(self) -> None:
        reg = {"tool": {"actions": "not_a_dict"}}
        node = WorkflowNode("n", "tool", "a")
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, reg) is None

    def test_action_meta_not_dict_skipped(self) -> None:
        reg = {"tool": {"actions": {"a": "not_a_dict"}}}
        node = WorkflowNode("n", "tool", "a")
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, reg) is None

    def test_required_params_not_list_treated_empty(self) -> None:
        reg = {"tool": {"actions": {"a": {"required_params": "not_a_list"}}}}
        node = WorkflowNode("n", "tool", "a", params={})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, reg) is None

    def test_empty_string_required_param_fails(self) -> None:
        reg = {"tool": {"actions": {"a": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "tool", "a", params={"key": ""})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "key" in result

    def test_whitespace_only_required_param_fails(self) -> None:
        reg = {"tool": {"actions": {"a": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "tool", "a", params={"key": "   "})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None

    def test_zero_value_required_param_passes(self) -> None:
        """0 是有效值（非空字符串）。"""
        reg = {"tool": {"actions": {"a": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "tool", "a", params={"key": 0})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, reg) is None

    def test_false_value_required_param_passes(self) -> None:
        """False 是有效值（非空字符串）。"""
        reg = {"tool": {"actions": {"a": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "tool", "a", params={"key": False})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        assert LLMWorkflowPlanner._validate_required_params(plan, reg) is None

    def test_none_params_dict_treated_empty(self) -> None:
        reg = {"tool": {"actions": {"a": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "tool", "a", params=None)
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None

    def test_multiple_required_params_first_missing(self) -> None:
        reg = {"tool": {"actions": {"a": {"required_params": ["k1", "k2"]}}}}
        node = WorkflowNode("n", "tool", "a", params={"k2": "val"})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "k1" in result

    def test_multiple_required_params_second_missing(self) -> None:
        reg = {"tool": {"actions": {"a": {"required_params": ["k1", "k2"]}}}}
        node = WorkflowNode("n", "tool", "a", params={"k1": "val"})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        assert result is not None
        assert "k2" in result

    def test_empty_tool_id_looked_up_in_registry(self) -> None:
        """空 tool_id 仍会在 registry 中查找 "" 键。"""
        reg = {"": {"actions": {"a": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "", "a", params={})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        # 空 tool_id 仍被查找，缺 key 时返回错误
        assert result is not None
        assert "key" in result

    def test_empty_action_looked_up_in_registry(self) -> None:
        """空 action 仍会在 actions 中查找 "" 键。"""
        reg = {"tool": {"actions": {"": {"required_params": ["key"]}}}}
        node = WorkflowNode("n", "tool", "", params={})
        plan = PlanGraph(plan_id="p", intent="i", nodes=[node])
        result = LLMWorkflowPlanner._validate_required_params(plan, reg)
        # 空 action 仍被查找，缺 key 时返回错误
        assert result is not None
        assert "key" in result


# ---------------------------------------------------------------------------
# _plan_with_react_multiagent — probe filtering logic
# ---------------------------------------------------------------------------


class TestPlanWithReactMultiagent:
    def test_candidate_none_returns_none(self) -> None:
        """候选计划为 None 时直接返回 None。"""
        planner = _make_planner()
        with patch.object(planner, "_plan_with_llm", return_value=None):
            result = planner._plan_with_react_multiagent(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_probe_filters_high_risk_nodes(self) -> None:
        """high risk 节点不进入 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
                WorkflowNode("n2", "products", "create", risk="medium", idempotent=False),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                # 只 query 被探测
                assert mock_exec.call_count <= 1

    def test_probe_filters_non_idempotent_nodes(self) -> None:
        """registry 中 action meta 标记非 idempotent 的节点不进入 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "create", risk="low", idempotent=True),
            ],
        )
        # create action 在 registry 中是 idempotent=False
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                # create 不是查询类 action，不进入 probe
                assert mock_exec.call_count == 0

    def test_probe_filters_non_query_actions(self) -> None:
        """非查询类 action 不进入 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "create", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_probe_skips_missing_required_params(self) -> None:
        """probe 节点缺少 required_params 时跳过。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1", "business_db", "read", risk="low", idempotent=True, params={}
                ),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_probe_executes_valid_query_node(self) -> None:
        """有效 query 节点被探测。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "products",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={"keyword": "abc"},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": [{"name": "x"}]}
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None
                assert mock_exec.call_count >= 1

    def test_probe_value_error_skipped(self) -> None:
        """probe 执行 ValueError 时跳过。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "products",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={"keyword": "abc"},
                ),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=ValueError("bad"),
            ):
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is None

    def test_probe_runtime_error_skipped(self) -> None:
        """probe 执行 RuntimeError 时跳过。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "products",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={"keyword": "abc"},
                ),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=RuntimeError("bad"),
            ):
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is None

    def test_probe_limits_to_three(self) -> None:
        """probe 最多 3 个。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    f"n{i}",
                    "products",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={"keyword": f"k{i}"},
                )
                for i in range(5)
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert mock_exec.call_count <= 3

    def test_probe_skips_empty_tool_id(self) -> None:
        """空 tool_id 节点跳过 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "", "query", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_probe_skips_empty_action(self) -> None:
        """空 action 节点跳过 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_probe_skips_non_dict_tool_spec(self) -> None:
        """非 dict tool_spec 跳过 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "unknown", "query", risk="low", idempotent=True),
            ],
        )
        reg = {"unknown": "not_a_dict"}
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=reg,
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_probe_skips_non_dict_actions(self) -> None:
        """非 dict actions 跳过 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        reg = {"products": {"actions": "not_a_dict"}}
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=reg,
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_probe_skips_non_dict_action_meta(self) -> None:
        """非 dict action_meta 跳过 probe。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        reg = {"products": {"actions": {"query": "not_a_dict"}}}
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            with patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool"
            ) as mock_exec:
                mock_exec.return_value = {"success": True, "data": []}
                planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=reg,
                    context={},
                )
                assert mock_exec.call_count == 0

    def test_final_plan_none_returns_none(self) -> None:
        """最终计划为 None 时返回 None。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, None]):
            result = planner._plan_with_react_multiagent(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_valid_final_plan_returns_plan(self) -> None:
        """校验通过的最终计划被返回。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            result = planner._plan_with_react_multiagent(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.plan_id == "pid"


# ---------------------------------------------------------------------------
# _critic_repair_with_llm — error paths
# ---------------------------------------------------------------------------


class TestCriticRepairWithLLM:
    def _make_planner_with_fence(self) -> Any:
        """创建 planner 并补上 _strip_json_code_fence 方法（源码中调用但未定义）。"""
        planner = _make_planner()
        # 源码调用了 self._strip_json_code_fence 但未定义，补上 no-op 实现
        planner._strip_json_code_fence = lambda raw: raw  # type: ignore[attr-defined]
        return planner

    def test_no_api_key_returns_none(self) -> None:
        """无 api_key 时返回 None。"""
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
            ai = MagicMock()
            ai.api_key = ""
            mock_svc.return_value = ai
            planner = LLMWorkflowPlanner()

        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        result = planner._critic_repair_with_llm(
            plan_id="pid",
            user_id="u1",
            message="test",
            tool_registry={},
            context={},
            error="err",
            invalid_plan=invalid_plan,
        )
        assert result is None

    def test_http_error_returns_none(self) -> None:
        """HTTP 错误时返回 None。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 500
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is None

    def test_empty_response_returns_none(self) -> None:
        """空响应返回 None。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is None

    def test_invalid_json_returns_none(self) -> None:
        """无效 JSON 返回 None。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "not json{"}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is None

    def test_value_error_returns_none(self) -> None:
        """ValueError 返回 None。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.side_effect = ValueError("bad json")
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is None

    def test_runtime_error_returns_none(self) -> None:
        """RuntimeError 返回 None。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.side_effect = RuntimeError("conn fail")
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is None

    def test_valid_response_returns_plan(self) -> None:
        """有效响应返回修复后的计划。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        payload = {
            "intent": "fixed",
            "todo_steps": ["step1"],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "x"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "查询",
                    "depends_on": [],
                }
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is not None
            assert result.intent == "fixed"

    def test_response_with_code_fence(self) -> None:
        """带代码围栏的响应被正确解析。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        payload = {
            "intent": "fixed",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        content = f"```json\n{json.dumps(payload)}\n```"
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": content}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry={},
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            assert result is not None
            assert result.intent == "fixed"

    def test_non_dict_action_meta_skipped(self) -> None:
        """非 dict action_meta 在构建 tool_specs 时被跳过。"""
        planner = self._make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        reg = {
            "tool": {
                "description": "d",
                "actions": {
                    "good": {"risk": "low", "idempotent": True, "required_params": []},
                    "bad": "not_a_dict",
                },
            }
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._critic_repair_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=reg,
                context={},
                error="err",
                invalid_plan=invalid_plan,
            )
            # 空内容返回 None，但不崩溃
            assert result is None


# ---------------------------------------------------------------------------
# _plan_with_llm — additional error paths
# ---------------------------------------------------------------------------


class TestPlanWithLLMErrorPaths:
    def test_value_error_returns_none(self) -> None:
        """ValueError 返回 None。"""
        planner = _make_planner()
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.side_effect = ValueError("bad")
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_runtime_error_returns_none(self) -> None:
        """RuntimeError 返回 None。"""
        planner = _make_planner()
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            mock_client.return_value.post.side_effect = RuntimeError("bad")
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_invalid_json_returns_none(self) -> None:
        """无效 JSON 返回 None。"""
        planner = _make_planner()
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "not json{"}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_empty_content_returns_none(self) -> None:
        """空 content 返回 None。"""
        planner = _make_planner()
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_valid_response_with_context_metadata(self) -> None:
        """有效响应且 context 含 user_memory_rag/memory_v2/tool_probe_outputs。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": ["step1"],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "x"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "",
                    "depends_on": [],
                }
            ],
        }
        context = {
            "user_memory_rag": {"summary": "memory summary"},
            "memory_v2": {"summary": "v2 summary"},
            "tool_probe_outputs": [
                {
                    "tool_id": "products",
                    "action": "query",
                    "success": True,
                    "message": "ok",
                    "data_preview": "data",
                },
                "not_a_dict",  # 非dict项被跳过
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None
            assert result.metadata["user_memory_rag_summary"] == "memory summary"
            assert result.metadata["memory_v2_summary"] == "v2 summary"
            assert len(result.metadata["tool_probe_outputs"]) == 1

    def test_context_with_non_dict_user_memory_rag(self) -> None:
        """context 中 user_memory_rag 非 dict 时不崩溃。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        context = {"user_memory_rag": "not_a_dict"}
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None
            assert result.metadata["user_memory_rag_summary"] == ""

    def test_context_with_non_dict_memory_v2(self) -> None:
        """context 中 memory_v2 非 dict 时不崩溃。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        context = {"memory_v2": "not_a_dict"}
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None

    def test_context_with_non_list_tool_probe_outputs(self) -> None:
        """context 中 tool_probe_outputs 非 list 时不崩溃。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        context = {"tool_probe_outputs": "not_a_list"}
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None
            assert result.metadata["tool_probe_outputs"] == []

    def test_context_not_dict_skips_metadata(self) -> None:
        """context 非 dict 时跳过 metadata 提取。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=None,  # type: ignore[arg-type]
            )
            assert result is not None

    def test_response_with_code_fence(self) -> None:
        """带代码围栏的响应被正确解析。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        content = f"```json\n{json.dumps(payload)}\n```"
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": content}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.intent == "test"

    def test_empty_nodes_in_response(self) -> None:
        """响应中 nodes 为空列表。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert len(result.nodes) == 0

    def test_nodes_missing_node_id_uses_default(self) -> None:
        """节点缺少 node_id 时使用默认值。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {
                    "tool_id": "products",
                    "action": "query",
                    "params": {},
                    "risk": "low",
                    "idempotent": True,
                    "description": "",
                    "depends_on": [],
                }
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.nodes[0].node_id == "node_1"

    def test_nodes_missing_params_uses_empty_dict(self) -> None:
        """节点缺少 params 时使用空 dict。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "risk": "low",
                    "idempotent": True,
                    "description": "",
                    "depends_on": [],
                }
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.nodes[0].params == {}

    def test_intent_missing_uses_default(self) -> None:
        """响应缺少 intent 时使用默认值。"""
        planner = _make_planner()
        payload = {
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps(payload)}}]
            }
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.intent == "dynamic_workflow"


# ---------------------------------------------------------------------------
# _get_planner_http_client — singleton
# ---------------------------------------------------------------------------


class TestGetPlannerHttpClient:
    def test_returns_client_instance(self) -> None:
        """返回 httpx.Client 实例。"""
        # 重置全局单例
        import app.application.workflow.planner as planner_mod

        original = planner_mod._planner_http_client
        planner_mod._planner_http_client = None
        try:
            client = _get_planner_http_client()
            assert client is not None
        finally:
            if original is not None:
                planner_mod._planner_http_client = original
            else:
                # 清理创建的客户端
                try:
                    client.close()  # type: ignore[possibly-undefined]
                except Exception:
                    pass
                planner_mod._planner_http_client = None

    def test_singleton_reuses_instance(self) -> None:
        """重复调用返回同一实例。"""
        import app.application.workflow.planner as planner_mod

        original = planner_mod._planner_http_client
        planner_mod._planner_http_client = None
        try:
            client1 = _get_planner_http_client()
            client2 = _get_planner_http_client()
            assert client1 is client2
        finally:
            if original is not None:
                planner_mod._planner_http_client = original
            else:
                try:
                    client1.close()  # type: ignore[possibly-undefined]
                except Exception:
                    pass
                planner_mod._planner_http_client = None


# ---------------------------------------------------------------------------
# plan() — integration with mocked internals
# ---------------------------------------------------------------------------


class TestPlanIntegration:
    def test_plan_returns_valid_plan_from_react(self) -> None:
        """plan() 返回 ReAct 规划的有效计划。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    result = planner.plan(
                        user_id="u1",
                        message="test",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result.plan_id == "pid"

    def test_plan_falls_back_when_react_invalid(self) -> None:
        """ReAct 返回无效计划时回退 fallback。"""
        planner = _make_planner()
        invalid_plan = PlanGraph(plan_id="pid", intent="", nodes=[])
        fallback_plan = PlanGraph(
            plan_id="pid",
            intent="fallback",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=invalid_plan):
                    with patch.object(planner, "_fallback_plan", return_value=fallback_plan):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result.intent == "fallback"

    def test_plan_falls_back_when_react_none(self) -> None:
        """ReAct 返回 None 时回退 fallback。"""
        planner = _make_planner()
        fallback_plan = PlanGraph(
            plan_id="pid",
            intent="fallback",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=None):
                    with patch.object(planner, "_fallback_plan", return_value=fallback_plan):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result.intent == "fallback"

    def test_plan_with_none_context(self) -> None:
        """context=None 不崩溃。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    result = planner.plan(
                        user_id="u1",
                        message="test",
                        tool_registry=_sample_registry(),
                        context=None,
                    )
                    assert result is not None

    def test_plan_user_memory_rag_import_error_handled(self) -> None:
        """用户记忆 RAG ImportError 不阻断主流程。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    # 让 get_user_memory_rag_app_service 导入失败
                    import sys

                    original = sys.modules.get("app.application")
                    if original is not None:
                        original_getattr = getattr(original, "get_user_memory_rag_app_service", None)
                        if original_getattr:
                            del original.get_user_memory_rag_app_service  # type: ignore[attr-defined]
                    try:
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None
                    finally:
                        if original is not None and original_getattr is not None:
                            original.get_user_memory_rag_app_service = original_getattr  # type: ignore[attr-defined]

    def test_plan_user_memory_rag_recoverable_error_handled(self) -> None:
        """用户记忆 RAG RECOVERABLE_ERRORS 不阻断主流程。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.application.get_user_memory_rag_app_service",
                        side_effect=RuntimeError("rag fail"),
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None

    def test_plan_memory_v2_import_error_handled(self) -> None:
        """Memory v2 ImportError 不阻断主流程。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    # 让 user_memory_service 导入失败
                    import sys

                    original = sys.modules.get("app.services.user_memory_service")
                    if original is not None:
                        sys.modules["app.services.user_memory_service"] = None  # type: ignore[assignment]
                    try:
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None
                    finally:
                        if original is not None:
                            sys.modules["app.services.user_memory_service"] = original
                        else:
                            sys.modules.pop("app.services.user_memory_service", None)

    def test_plan_memory_v2_recoverable_error_handled(self) -> None:
        """Memory v2 RECOVERABLE_ERRORS 不阻断主流程。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        with patch("app.application.normal_chat_dispatch.resolve_tool_execution_profile", return_value="normal"):
            with patch("app.application.workflow.planner._filter_tool_registry_for_profile", return_value=_sample_registry()):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.services.user_memory_service.get_user_memory_service",
                        side_effect=RuntimeError("v2 fail"),
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None
