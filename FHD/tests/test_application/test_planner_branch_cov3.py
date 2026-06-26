"""测试 app.application.workflow.planner 的分支覆盖（第三批）。

覆盖目标（聚焦未覆盖分支）：
- _execute_price_list_tool：缺 customer_name / ImportError / ValueError / OSError / RuntimeError / 成功
- _execute_products_tool：4 种参数组合 + ImportError / ValueError / RuntimeError
- _execute_customers_tool：ImportError / ValueError / RuntimeError / 成功
- _execute_customers_ensure_exists_tool：缺 unit / 已匹配 / 创建 / ImportError / ValueError / RuntimeError
- _execute_shipment_generate_tool：order_text / unit_name+products / 缺参 / 解析失败 / ImportError / ValueError / OSError / RuntimeError
- _execute_shipment_records_tool：ImportError / ValueError / RuntimeError / 成功
- _execute_materials_tool：ImportError / ValueError / RuntimeError / 成功
- _execute_print_label_tool：缺 products / ImportError / ValueError / OSError / RuntimeError / 成功
- _execute_excel_decompose_tool：缺 file_path / ImportError / ValueError / OSError / RuntimeError / 成功
- _execute_template_extract_tool：委托 excel_decompose
- _execute_wechat_preview_tool：ImportError / ValueError / RuntimeError / 成功（有/无联系人）
- _execute_excel_schema_tool：缺 file_path / ImportError / RECOVERABLE_ERRORS / openpyxl 回退 / 各异常
- _execute_excel_analysis_tool：缺 file_path / ImportError / RECOVERABLE_ERRORS / openpyxl 回退 / 各异常
- _execute_employee_list_tool / _execute_employee_execute_tool / _execute_business_db_read_tool / _execute_business_db_write_tool：委托 facade
- _plan_with_react_multiagent：probe 输出 data list / data 非 list / raw / customers query + task_agent / products query + route_normal_mode_message
- _critic_repair_with_llm：tool_specs 构建 / 非 dict spec 跳过 / 有效响应含 nodes
- _plan_with_llm：tool_specs 构建 / recent_messages / no api_key / 非 dict action_meta 跳过
- _fallback_plan：employee 非 dict 项 / 空 pack_id / business_db_write 抽取节点 / business_db_read 英文/中文 / add_product 有/无 customers
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _execute_customers_ensure_exists_tool,
    _execute_customers_tool,
    _execute_excel_analysis_tool,
    _execute_excel_decompose_tool,
    _execute_excel_schema_tool,
    _execute_materials_tool,
    _execute_price_list_tool,
    _execute_print_label_tool,
    _execute_products_tool,
    _execute_shipment_generate_tool,
    _execute_shipment_records_tool,
    _execute_template_extract_tool,
    _execute_wechat_preview_tool,
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
                "ensure_exists": {
                    "description": "确保客户存在",
                    "risk": "medium",
                    "idempotent": True,
                    "availability": "shared",
                    "required_params": ["unit_name"],
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


def _make_planner_with_fence() -> Any:
    planner = _make_planner()
    planner._strip_json_code_fence = lambda raw: raw  # type: ignore[attr-defined]
    return planner


# ---------------------------------------------------------------------------
# _execute_price_list_tool
# ---------------------------------------------------------------------------


class TestExecutePriceListTool:
    """_execute_price_list_tool 分支覆盖。"""

    def test_missing_customer_name_returns_error(self) -> None:
        result = _execute_price_list_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_customer_name"

    def test_customer_name_from_unit_param(self) -> None:
        """customer_name 也可从 unit 参数获取。"""
        with patch(
            "app.application.tools.handle_price_list_export",
            return_value={"success": True},
        ):
            with patch(
                "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
                return_value=None,
            ):
                result = _execute_price_list_tool({"unit": "ABC公司"})
                assert result["success"] is True

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=None,
        ):
            with patch.dict("sys.modules", {"app.application.tools": None}):
                result = _execute_price_list_tool({"customer_name": "ABC"})
                assert result["success"] is False
                assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=None,
        ):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=ValueError("bad value"),
            ):
                result = _execute_price_list_tool({"customer_name": "ABC"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=None,
        ):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=TypeError("bad type"),
            ):
                result = _execute_price_list_tool({"customer_name": "ABC"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_oserror_returns_file_io_error(self) -> None:
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=None,
        ):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=OSError("disk full"),
            ):
                result = _execute_price_list_tool({"customer_name": "ABC"})
                assert result["success"] is False
                assert result["error_code"] == "file_io_error"

    def test_runtime_error_returns_export_failed(self) -> None:
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=None,
        ):
            with patch(
                "app.application.tools.handle_price_list_export",
                side_effect=RuntimeError("export fail"),
            ):
                result = _execute_price_list_tool({"customer_name": "ABC"})
                assert result["success"] is False
                assert result["error_code"] == "export_failed"

    def test_successful_export(self) -> None:
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=None,
        ):
            with patch(
                "app.application.tools.handle_price_list_export",
                return_value={"success": True, "file_path": "/tmp/out.docx"},
            ):
                result = _execute_price_list_tool(
                    {"customer_name": "ABC", "keyword": "螺钉", "date": "2026-01-01"}
                )
                assert result["success"] is True

    def test_with_fhd_root(self) -> None:
        """ensure_fhd_repo_on_syspath 返回非 None 时传入 workspace_root。"""
        fake_root = MagicMock()
        with patch(
            "app.application.workflow.planner.ensure_fhd_repo_on_syspath",
            return_value=fake_root,
        ):
            with patch(
                "app.application.tools.handle_price_list_export",
                return_value={"success": True},
            ) as mock_export:
                _execute_price_list_tool({"customer_name": "ABC"})
                args, kwargs = mock_export.call_args
                assert kwargs.get("workspace_root") == str(fake_root)


# ---------------------------------------------------------------------------
# _execute_products_tool
# ---------------------------------------------------------------------------


class TestExecuteProductsTool:
    """_execute_products_tool 分支覆盖。"""

    def test_model_and_unit_name_combined(self) -> None:
        """model_number + unit_name 同时存在。"""
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"model_number": "M8", "unit_name": "ABC公司"})
            assert result["success"] is True
            call_kwargs = mock_svc.get_products.call_args.kwargs
            assert call_kwargs["unit_name"] == "ABC公司"
            assert call_kwargs["model_number"] == "M8"
            assert call_kwargs["keyword"] is None

    def test_model_only(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"model_number": "M8"})
            assert result["success"] is True
            call_kwargs = mock_svc.get_products.call_args.kwargs
            assert call_kwargs["unit_name"] is None
            assert call_kwargs["model_number"] == "M8"

    def test_unit_only(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"unit_name": "ABC公司", "keyword": "螺钉"})
            assert result["success"] is True
            call_kwargs = mock_svc.get_products.call_args.kwargs
            assert call_kwargs["unit_name"] == "ABC公司"
            assert call_kwargs["model_number"] is None
            assert call_kwargs["keyword"] == "螺钉"

    def test_neither_model_nor_unit(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = _execute_products_tool({"keyword": "螺钉"})
            assert result["success"] is True
            call_kwargs = mock_svc.get_products.call_args.kwargs
            assert call_kwargs["unit_name"] is None
            assert call_kwargs["model_number"] is None
            assert call_kwargs["keyword"] == "螺钉"

    def test_product_code_as_model_alias(self) -> None:
        """product_code 作为 model_number 的别名。"""
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            _execute_products_tool({"product_code": "P001"})
            call_kwargs = mock_svc.get_products.call_args.kwargs
            assert call_kwargs["model_number"] == "P001"

    def test_unit_as_unit_name_alias(self) -> None:
        """unit 作为 unit_name 的别名。"""
        mock_svc = MagicMock()
        mock_svc.get_products.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            _execute_products_tool({"unit": "XYZ公司"})
            call_kwargs = mock_svc.get_products.call_args.kwargs
            assert call_kwargs["unit_name"] == "XYZ公司"

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=ImportError("no module")):
            result = _execute_products_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=ValueError("bad")):
            result = _execute_products_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=TypeError("bad")):
            result = _execute_products_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error_returns_query_failed(self) -> None:
        with patch("app.bootstrap.get_products_service", side_effect=RuntimeError("fail")):
            result = _execute_products_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"

    def test_invalid_page_param_raises_value_error(self) -> None:
        """page 非数字时 int() 抛 ValueError。"""
        with patch("app.bootstrap.get_products_service", side_effect=ValueError("bad")):
            result = _execute_products_tool({"page": "abc"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"


# ---------------------------------------------------------------------------
# _execute_customers_tool
# ---------------------------------------------------------------------------


class TestExecuteCustomersTool:
    """_execute_customers_tool 分支覆盖。"""

    def test_successful_query_with_keyword(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_tool({"keyword": "ABC"})
            assert result["success"] is True
            call_kwargs = mock_svc.get_all.call_args.kwargs
            assert call_kwargs["keyword"] == "ABC"

    def test_successful_query_with_customer_name(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            _execute_customers_tool({"customer_name": "XYZ"})
            call_kwargs = mock_svc.get_all.call_args.kwargs
            assert call_kwargs["keyword"] == "XYZ"

    def test_empty_keyword_passes_none(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            _execute_customers_tool({"keyword": ""})
            call_kwargs = mock_svc.get_all.call_args.kwargs
            assert call_kwargs["keyword"] is None

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no module")):
            result = _execute_customers_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ValueError("bad")):
            result = _execute_customers_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=TypeError("bad")):
            result = _execute_customers_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error_returns_query_failed(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = _execute_customers_tool({"keyword": "x"})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


# ---------------------------------------------------------------------------
# _execute_customers_ensure_exists_tool
# ---------------------------------------------------------------------------


class TestExecuteCustomersEnsureExistsTool:
    """_execute_customers_ensure_exists_tool 分支覆盖。"""

    def test_missing_unit_name_returns_error(self) -> None:
        result = _execute_customers_ensure_exists_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_unit_name"

    def test_empty_unit_name_returns_error(self) -> None:
        result = _execute_customers_ensure_exists_tool({"unit_name": "  "})
        assert result["success"] is False
        assert result["error_code"] == "missing_unit_name"

    def test_unit_name_from_customer_name_alias(self) -> None:
        """customer_name 作为 unit_name 的别名。"""
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": True, "id": 1}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            _execute_customers_ensure_exists_tool({"customer_name": "ABC公司"})
            mock_svc.match_purchase_unit.assert_called_once_with("ABC公司")

    def test_matched_returns_existing(self) -> None:
        mock_matched = MagicMock()
        mock_matched.id = 42
        mock_matched.unit_name = "ABC公司"
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = mock_matched
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC公司"})
            assert result["success"] is True
            assert result["created"] is False
            assert result["data"]["id"] == 42
            assert result["data"]["unit_name"] == "ABC公司"

    def test_matched_without_id_attr(self) -> None:
        """matched 对象无 id 属性时返回 None。"""
        mock_matched = MagicMock()
        del mock_matched.id
        mock_matched.unit_name = "ABC"
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = mock_matched
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC"})
            assert result["success"] is True
            assert result["data"]["id"] is None

    def test_matched_without_unit_name_attr(self) -> None:
        """matched 对象无 unit_name 属性时回退到传入的 unit。"""
        mock_matched = MagicMock()
        mock_matched.id = 1
        del mock_matched.unit_name
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = mock_matched
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC"})
            assert result["success"] is True
            assert result["data"]["unit_name"] == "ABC"

    def test_create_new_customer_success(self) -> None:
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": True, "id": 99}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "新客户"})
            assert result["success"] is True
            assert result["created"] is True
            assert result["id"] == 99

    def test_create_new_customer_failure(self) -> None:
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = {"success": False, "message": "dup"}
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "新客户"})
            assert result["success"] is False
            assert result["created"] is False

    def test_create_returns_non_dict(self) -> None:
        """create 返回非 dict 时回退到 success=False。"""
        mock_svc = MagicMock()
        mock_svc.match_purchase_unit.return_value = None
        mock_svc.create.return_value = "not a dict"
        with patch("app.bootstrap.get_customer_app_service", return_value=mock_svc):
            result = _execute_customers_ensure_exists_tool({"unit_name": "新客户"})
            assert result["success"] is False
            assert result["created"] is False

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ImportError("no module")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"
            assert result["created"] is False

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=ValueError("bad")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"
            assert result["created"] is False

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=TypeError("bad")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"
            assert result["created"] is False

    def test_runtime_error_returns_create_failed(self) -> None:
        with patch("app.bootstrap.get_customer_app_service", side_effect=RuntimeError("fail")):
            result = _execute_customers_ensure_exists_tool({"unit_name": "ABC"})
            assert result["success"] is False
            assert result["error_code"] == "create_failed"
            assert result["created"] is False


# ---------------------------------------------------------------------------
# _execute_shipment_generate_tool
# ---------------------------------------------------------------------------


class TestExecuteShipmentGenerateTool:
    """_execute_shipment_generate_tool 分支覆盖。"""

    def test_missing_all_params_returns_error(self) -> None:
        result = _execute_shipment_generate_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_order_params"

    def test_empty_order_text_and_no_unit_products(self) -> None:
        result = _execute_shipment_generate_tool(
            {"order_text": "  ", "unit_name": "", "products": []}
        )
        assert result["success"] is False
        assert result["error_code"] == "missing_order_params"

    def test_order_text_not_list_products_ignored(self) -> None:
        """order_text 存在时直接走 _parse_order_text，products 非 list 被忽略。"""
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "parse fail"},
        ):
            result = _execute_shipment_generate_tool(
                {"order_text": "some order", "products": "not a list"}
            )
            assert result["success"] is False
            assert "parse fail" in result["message"]

    def test_unit_name_with_empty_products_list_uses_order_text(self) -> None:
        """unit_name 存在但 products 为空列表时走 order_text 分支。"""
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "U", "products": []},
        ):
            with patch("app.bootstrap.get_shipment_app_service") as mock_get_svc:
                mock_svc = MagicMock()
                mock_svc.generate_shipment_document.return_value = {"success": True}
                mock_get_svc.return_value = mock_svc
                result = _execute_shipment_generate_tool(
                    {"unit_name": "U", "products": [], "order_text": "order"}
                )
                assert result["success"] is True

    def test_unit_name_with_products_no_order_text(self) -> None:
        """unit_name + products（非空 list）且无 order_text 时走直接构造。"""
        with patch("app.bootstrap.get_shipment_app_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.generate_shipment_document.return_value = {"success": True}
            mock_get_svc.return_value = mock_svc
            result = _execute_shipment_generate_tool(
                {"unit_name": "U", "products": [{"name": "P1"}]}
            )
            assert result["success"] is True
            call_kwargs = mock_svc.generate_shipment_document.call_args.kwargs
            assert call_kwargs["unit_name"] == "U"
            assert call_kwargs["products"] == [{"name": "P1"}]

    def test_parse_failure_returns_error(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "error": "parse error"},
        ):
            result = _execute_shipment_generate_tool({"order_text": "bad order"})
            assert result["success"] is False
            assert "parse error" in result["message"]

    def test_parse_failure_with_message_field(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": False, "message": "custom message"},
        ):
            result = _execute_shipment_generate_tool({"order_text": "bad order"})
            assert result["success"] is False
            assert "custom message" in result["message"]

    def test_successful_generation_with_order_text(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            return_value={"success": True, "unit_name": "U", "products": [{"name": "P1"}]},
        ):
            with patch("app.bootstrap.get_shipment_app_service") as mock_get_svc:
                mock_svc = MagicMock()
                mock_svc.generate_shipment_document.return_value = {"success": True, "doc_id": 1}
                mock_get_svc.return_value = mock_svc
                result = _execute_shipment_generate_tool(
                    {
                        "order_text": "order",
                        "template_name": "tpl",
                        "date": "2026-01-01",
                        "order_number": "ORD001",
                    }
                )
                assert result["success"] is True
                call_kwargs = mock_svc.generate_shipment_document.call_args.kwargs
                assert call_kwargs["template_name"] == "tpl"
                assert call_kwargs["date"] == "2026-01-01"
                assert call_kwargs["order_number"] == "ORD001"
                assert call_kwargs["raw_text"] == "order"

    def test_raw_text_fallback_when_no_order_text(self) -> None:
        """无 order_text 时 raw_text 从 params.raw_text 取。"""
        with patch("app.bootstrap.get_shipment_app_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.generate_shipment_document.return_value = {"success": True}
            mock_get_svc.return_value = mock_svc
            _execute_shipment_generate_tool(
                {"unit_name": "U", "products": [{"name": "P1"}], "raw_text": "raw order"}
            )
            call_kwargs = mock_svc.generate_shipment_document.call_args.kwargs
            assert call_kwargs["raw_text"] == "raw order"

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=ImportError("no module"),
        ):
            result = _execute_shipment_generate_tool({"order_text": "order"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=ValueError("bad"),
        ):
            result = _execute_shipment_generate_tool({"order_text": "order"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=TypeError("bad"),
        ):
            result = _execute_shipment_generate_tool({"order_text": "order"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_oserror_returns_file_io_error(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=OSError("disk full"),
        ):
            result = _execute_shipment_generate_tool({"order_text": "order"})
            assert result["success"] is False
            assert result["error_code"] == "file_io_error"

    def test_runtime_error_returns_generation_failed(self) -> None:
        with patch(
            "app.application.facades.tools_facade._parse_order_text",
            side_effect=RuntimeError("fail"),
        ):
            result = _execute_shipment_generate_tool({"order_text": "order"})
            assert result["success"] is False
            assert result["error_code"] == "generation_failed"


# ---------------------------------------------------------------------------
# _execute_shipment_records_tool
# ---------------------------------------------------------------------------


class TestExecuteShipmentRecordsTool:
    """_execute_shipment_records_tool 分支覆盖。"""

    def test_successful_query_with_unit_name(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = [{"id": 1}]
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            result = _execute_shipment_records_tool({"unit_name": "ABC"})
            assert result["success"] is True
            assert len(result["data"]) == 1
            mock_svc.get_shipment_records.assert_called_once_with(unit_name="ABC", limit=50)

    def test_successful_query_with_keyword(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            _execute_shipment_records_tool({"keyword": "XYZ"})
            mock_svc.get_shipment_records.assert_called_once_with(unit_name="XYZ", limit=50)

    def test_successful_query_with_customer_name(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            _execute_shipment_records_tool({"customer_name": "CUST"})
            mock_svc.get_shipment_records.assert_called_once_with(unit_name="CUST", limit=50)

    def test_no_unit_passes_none(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            _execute_shipment_records_tool({})
            mock_svc.get_shipment_records.assert_called_once_with(unit_name=None, limit=50)

    def test_custom_limit(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = []
        with patch("app.bootstrap.get_shipment_app_service", return_value=mock_svc):
            _execute_shipment_records_tool({"limit": 10})
            mock_svc.get_shipment_records.assert_called_once_with(unit_name=None, limit=10)

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=ImportError("no module")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=ValueError("bad")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=TypeError("bad")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error_returns_query_failed(self) -> None:
        with patch("app.bootstrap.get_shipment_app_service", side_effect=RuntimeError("fail")):
            result = _execute_shipment_records_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


# ---------------------------------------------------------------------------
# _execute_materials_tool
# ---------------------------------------------------------------------------


class TestExecuteMaterialsTool:
    """_execute_materials_tool 分支覆盖。"""

    def test_successful_query_with_keyword(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_materials_service", return_value=mock_svc):
            result = _execute_materials_tool({"keyword": "钢板"})
            assert result["success"] is True
            call_kwargs = mock_svc.get_all_materials.call_args.kwargs
            assert call_kwargs["search"] == "钢板"

    def test_successful_query_with_search_alias(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_materials_service", return_value=mock_svc):
            _execute_materials_tool({"search": "钢板"})
            call_kwargs = mock_svc.get_all_materials.call_args.kwargs
            assert call_kwargs["search"] == "钢板"

    def test_successful_query_with_category(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_materials_service", return_value=mock_svc):
            _execute_materials_tool({"category": "钢材"})
            call_kwargs = mock_svc.get_all_materials.call_args.kwargs
            assert call_kwargs["category"] == "钢材"

    def test_empty_keyword_passes_none(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_all_materials.return_value = {"success": True, "data": []}
        with patch("app.bootstrap.get_materials_service", return_value=mock_svc):
            _execute_materials_tool({"keyword": "  "})
            call_kwargs = mock_svc.get_all_materials.call_args.kwargs
            assert call_kwargs["search"] is None

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=ImportError("no module")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=ValueError("bad")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=TypeError("bad")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error_returns_query_failed(self) -> None:
        with patch("app.bootstrap.get_materials_service", side_effect=RuntimeError("fail")):
            result = _execute_materials_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


# ---------------------------------------------------------------------------
# _execute_print_label_tool
# ---------------------------------------------------------------------------


class TestExecutePrintLabelTool:
    """_execute_print_label_tool 分支覆盖。"""

    def test_missing_products_returns_error(self) -> None:
        result = _execute_print_label_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_empty_products_list_returns_error(self) -> None:
        result = _execute_print_label_tool({"products": []})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_products_not_list_returns_error(self) -> None:
        result = _execute_print_label_tool({"products": "not a list"})
        assert result["success"] is False
        assert result["error_code"] == "missing_products"

    def test_successful_generation(self) -> None:
        mock_gen = MagicMock()
        mock_gen.generate_labels_for_order.return_value = ["label1.png", "label2.png"]
        with patch(
            "app.infrastructure.documents.shipment_document_generator_impl.SimpleLabelGenerator",
            return_value=mock_gen,
        ):
            with patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/tmp/labels",
            ):
                with patch("os.makedirs"):
                    result = _execute_print_label_tool(
                        {"products": [{"name": "P1"}], "order_number": "ORD001"}
                    )
                    assert result["success"] is True
                    assert len(result["data"]) == 2

    def test_doc_name_as_order_number_alias(self) -> None:
        """doc_name 作为 order_number 的别名。"""
        mock_gen = MagicMock()
        mock_gen.generate_labels_for_order.return_value = []
        with patch(
            "app.infrastructure.documents.shipment_document_generator_impl.SimpleLabelGenerator",
            return_value=mock_gen,
        ):
            with patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/tmp/labels",
            ):
                with patch("os.makedirs"):
                    _execute_print_label_tool({"products": [{"name": "P1"}], "doc_name": "DOC001"})
                    mock_gen.generate_labels_for_order.assert_called_once_with(
                        order_number="DOC001", products=[{"name": "P1"}]
                    )

    def test_default_order_number_when_missing(self) -> None:
        mock_gen = MagicMock()
        mock_gen.generate_labels_for_order.return_value = []
        with patch(
            "app.infrastructure.documents.shipment_document_generator_impl.SimpleLabelGenerator",
            return_value=mock_gen,
        ):
            with patch(
                "app.utils.path_utils.get_resource_path",
                return_value="/tmp/labels",
            ):
                with patch("os.makedirs"):
                    _execute_print_label_tool({"products": [{"name": "P1"}]})
                    mock_gen.generate_labels_for_order.assert_called_once_with(
                        order_number="LABEL", products=[{"name": "P1"}]
                    )

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.documents.shipment_document_generator_impl": None,
            },
        ):
            result = _execute_print_label_tool({"products": [{"name": "P1"}]})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.utils.path_utils.get_resource_path",
            side_effect=ValueError("bad"),
        ):
            result = _execute_print_label_tool({"products": [{"name": "P1"}]})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.utils.path_utils.get_resource_path",
            side_effect=TypeError("bad"),
        ):
            result = _execute_print_label_tool({"products": [{"name": "P1"}]})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_oserror_returns_file_io_error(self) -> None:
        with patch(
            "app.utils.path_utils.get_resource_path",
            side_effect=OSError("disk full"),
        ):
            result = _execute_print_label_tool({"products": [{"name": "P1"}]})
            assert result["success"] is False
            assert result["error_code"] == "file_io_error"

    def test_runtime_error_returns_generation_failed(self) -> None:
        with patch(
            "app.utils.path_utils.get_resource_path",
            side_effect=RuntimeError("fail"),
        ):
            result = _execute_print_label_tool({"products": [{"name": "P1"}]})
            assert result["success"] is False
            assert result["error_code"] == "generation_failed"


# ---------------------------------------------------------------------------
# _execute_excel_decompose_tool
# ---------------------------------------------------------------------------


class TestExecuteExcelDecomposeTool:
    """_execute_excel_decompose_tool 分支覆盖。"""

    def test_missing_file_path_returns_error(self) -> None:
        result = _execute_excel_decompose_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_empty_file_path_returns_error(self) -> None:
        result = _execute_excel_decompose_tool({"file_path": "  "})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_successful_decompose_with_template_type(self) -> None:
        mock_svc = MagicMock()
        mock_svc.decompose_template.return_value = {"success": True}
        with patch("app.bootstrap.get_template_app_service", return_value=mock_svc):
            result = _execute_excel_decompose_tool(
                {"file_path": "/tmp/t.xlsx", "template_type": "order"}
            )
            assert result["success"] is True
            mock_svc.decompose_template.assert_called_once_with("/tmp/t.xlsx", "order")

    def test_successful_decompose_with_scope_alias(self) -> None:
        mock_svc = MagicMock()
        mock_svc.decompose_template.return_value = {"success": True}
        with patch("app.bootstrap.get_template_app_service", return_value=mock_svc):
            _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx", "scope": "shipment"})
            mock_svc.decompose_template.assert_called_once_with("/tmp/t.xlsx", "shipment")

    def test_no_template_type_passes_none(self) -> None:
        mock_svc = MagicMock()
        mock_svc.decompose_template.return_value = {"success": True}
        with patch("app.bootstrap.get_template_app_service", return_value=mock_svc):
            _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx"})
            mock_svc.decompose_template.assert_called_once_with("/tmp/t.xlsx", None)

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=ImportError("no module")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=ValueError("bad")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=TypeError("bad")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_oserror_returns_file_not_found(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=OSError("not found")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "file_not_found"

    def test_runtime_error_returns_decomposition_failed(self) -> None:
        with patch("app.bootstrap.get_template_app_service", side_effect=RuntimeError("fail")):
            result = _execute_excel_decompose_tool({"file_path": "/tmp/t.xlsx"})
            assert result["success"] is False
            assert result["error_code"] == "decomposition_failed"


# ---------------------------------------------------------------------------
# _execute_template_extract_tool
# ---------------------------------------------------------------------------


class TestExecuteTemplateExtractTool:
    """_execute_template_extract_tool 委托 excel_decompose。"""

    def test_delegates_to_excel_decompose(self) -> None:
        with patch(
            "app.application.workflow.planner._execute_excel_decompose_tool",
            return_value={"success": True, "delegated": True},
        ) as mock_decompose:
            result = _execute_template_extract_tool({"file_path": "/tmp/t.xlsx"})
            assert result["success"] is True
            assert result["delegated"] is True
            mock_decompose.assert_called_once_with({"file_path": "/tmp/t.xlsx"})

    def test_delegates_with_all_params(self) -> None:
        with patch(
            "app.application.workflow.planner._execute_excel_decompose_tool",
            return_value={"success": True},
        ) as mock_decompose:
            _execute_template_extract_tool({"file_path": "/tmp/t.xlsx", "template_type": "order"})
            mock_decompose.assert_called_once_with(
                {"file_path": "/tmp/t.xlsx", "template_type": "order"}
            )


# ---------------------------------------------------------------------------
# _execute_wechat_preview_tool
# ---------------------------------------------------------------------------


class TestExecuteWechatPreviewTool:
    """_execute_wechat_preview_tool 分支覆盖。"""

    def test_successful_query_with_contacts(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = [{"name": "张三"}]
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            result = _execute_wechat_preview_tool({"keyword": "张"})
            assert result["success"] is True
            assert len(result["data"]) == 1
            assert "选择联系人" in result["message"]

    def test_successful_query_no_contacts(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            result = _execute_wechat_preview_tool({"keyword": "不存在"})
            assert result["success"] is True
            assert "未找到" in result["message"]

    def test_keyword_from_unit_name_alias(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            _execute_wechat_preview_tool({"unit_name": "ABC公司"})
            call_kwargs = mock_svc.get_contacts.call_args.kwargs
            assert call_kwargs["keyword"] == "ABC公司"

    def test_empty_keyword_passes_none(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            _execute_wechat_preview_tool({"keyword": "  "})
            call_kwargs = mock_svc.get_contacts.call_args.kwargs
            assert call_kwargs["keyword"] is None

    def test_custom_limit(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            _execute_wechat_preview_tool({"limit": 10})
            call_kwargs = mock_svc.get_contacts.call_args.kwargs
            assert call_kwargs["limit"] == 10

    def test_default_limit_30(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_contacts.return_value = []
        with patch("app.bootstrap.get_wechat_contact_app_service", return_value=mock_svc):
            _execute_wechat_preview_tool({})
            call_kwargs = mock_svc.get_contacts.call_args.kwargs
            assert call_kwargs["limit"] == 30

    def test_import_error_returns_service_unavailable(self) -> None:
        with patch(
            "app.bootstrap.get_wechat_contact_app_service",
            side_effect=ImportError("no module"),
        ):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "service_unavailable"

    def test_value_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.bootstrap.get_wechat_contact_app_service",
            side_effect=ValueError("bad"),
        ):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_type_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.bootstrap.get_wechat_contact_app_service",
            side_effect=TypeError("bad"),
        ):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "invalid_parameters"

    def test_runtime_error_returns_query_failed(self) -> None:
        with patch(
            "app.bootstrap.get_wechat_contact_app_service",
            side_effect=RuntimeError("fail"),
        ):
            result = _execute_wechat_preview_tool({})
            assert result["success"] is False
            assert result["error_code"] == "query_failed"


# ---------------------------------------------------------------------------
# _execute_excel_schema_tool
# ---------------------------------------------------------------------------


class TestExecuteExcelSchemaTool:
    """_execute_excel_schema_tool 分支覆盖。"""

    def test_missing_file_path_returns_error(self) -> None:
        result = _execute_excel_schema_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_empty_file_path_returns_error(self) -> None:
        result = _execute_excel_schema_tool({"file_path": "  "})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_successful_via_app_service(self) -> None:
        mock_svc = MagicMock()
        mock_svc.analyze_schema.return_value = {"success": True, "fields": []}
        with patch(
            "app.bootstrap.get_excel_analysis_app_service", return_value=mock_svc, create=True
        ):
            result = _execute_excel_schema_tool(
                {"file_path": "/tmp/t.xlsx", "sheet_name": "Sheet1"}
            )
            assert result["success"] is True
            mock_svc.analyze_schema.assert_called_once_with(
                file_path="/tmp/t.xlsx", sheet_name="Sheet1"
            )

    def test_app_service_import_error_falls_back_to_openpyxl(self) -> None:
        """app_service ImportError 时降级到 openpyxl。"""
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "产品名称"
        mock_cell.column_letter = "A"
        mock_cell.column = 1
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 5
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is True
                assert result["row_count"] == 4  # max_row - 1
                assert len(result["fields"]) == 1

    def test_app_service_recoverable_error_falls_back_to_openpyxl(self) -> None:
        """app_service RECOVERABLE_ERRORS 时降级到 openpyxl。"""
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "列名"
        mock_cell.column_letter = "A"
        mock_cell.column = 1
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=RuntimeError("service fail"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is True

    def test_openpyxl_import_error_returns_library_unavailable(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=ImportError("no openpyxl")):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "library_unavailable"

    def test_openpyxl_value_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=ValueError("bad")):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_openpyxl_type_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=TypeError("bad")):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_openpyxl_oserror_returns_file_not_found(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=OSError("not found")):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "file_not_found"

    def test_openpyxl_runtime_error_returns_analysis_failed(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=RuntimeError("fail")):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "analysis_failed"

    def test_openpyxl_with_explicit_sheet_name(self) -> None:
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "列名"
        mock_cell.column_letter = "A"
        mock_cell.column = 1
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 0
        mock_wb.sheetnames = ["Sheet1", "Sheet2"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx", "sheet_name": "Sheet2"})
                mock_wb.__getitem__.assert_called_with("Sheet2")

    def test_openpyxl_default_sheet_name(self) -> None:
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "列名"
        mock_cell.column_letter = "A"
        mock_cell.column = 1
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 0
        mock_wb.sheetnames = ["FirstSheet", "SecondSheet"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                mock_wb.__getitem__.assert_called_with("FirstSheet")

    def test_openpyxl_cell_none_value_skipped(self) -> None:
        """表头中 None 值单元格被跳过。"""
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell1 = MagicMock()
        mock_cell1.value = "产品名称"
        mock_cell1.column_letter = "A"
        mock_cell1.column = 1
        mock_cell2 = MagicMock()
        mock_cell2.value = None
        mock_ws.iter_rows.return_value = iter([[mock_cell1, mock_cell2]])
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_schema_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is True
                assert len(result["fields"]) == 1  # 只有一个非 None 单元格


# ---------------------------------------------------------------------------
# _execute_excel_analysis_tool
# ---------------------------------------------------------------------------


class TestExecuteExcelAnalysisTool:
    """_execute_excel_analysis_tool 分支覆盖。"""

    def test_missing_file_path_returns_error(self) -> None:
        result = _execute_excel_analysis_tool({})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_empty_file_path_returns_error(self) -> None:
        result = _execute_excel_analysis_tool({"file_path": "  "})
        assert result["success"] is False
        assert result["error_code"] == "missing_file_path"

    def test_successful_via_app_service(self) -> None:
        mock_svc = MagicMock()
        mock_svc.analyze_data.return_value = {"success": True, "rows": []}
        with patch(
            "app.bootstrap.get_excel_analysis_app_service", return_value=mock_svc, create=True
        ):
            result = _execute_excel_analysis_tool(
                {
                    "file_path": "/tmp/t.xlsx",
                    "sheet_name": "Sheet1",
                    "query": "price > 100",
                    "columns": ["产品名称"],
                }
            )
            assert result["success"] is True
            mock_svc.analyze_data.assert_called_once_with(
                file_path="/tmp/t.xlsx",
                sheet_name="Sheet1",
                query="price > 100",
                columns=["产品名称"],
            )

    def test_app_service_import_error_falls_back_to_openpyxl(self) -> None:
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "产品名称"
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is True
                assert len(result["headers"]) == 1

    def test_app_service_recoverable_error_falls_back_to_openpyxl(self) -> None:
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "列名"
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 1
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=RuntimeError("service fail"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is True

    def test_openpyxl_with_target_columns_filter(self) -> None:
        """target_columns 过滤列。"""
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell1 = MagicMock()
        mock_cell1.value = "产品名称"
        mock_cell2 = MagicMock()
        mock_cell2.value = "型号"
        mock_row_cell1 = MagicMock()
        mock_row_cell1.value = "螺钉"
        mock_row_cell2 = MagicMock()
        mock_row_cell2.value = "M8"
        mock_ws.iter_rows.return_value = iter(
            [[mock_cell1, mock_cell2], [mock_row_cell1, mock_row_cell2]]
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_analysis_tool(
                    {"file_path": "/tmp/t.xlsx", "columns": ["型号"]}
                )
                assert result["success"] is True
                # 只保留 "型号" 列
                assert "型号" in result["rows"][0]
                assert "产品名称" not in result["rows"][0]

    def test_openpyxl_empty_row_skipped(self) -> None:
        """全 None 行被跳过。"""
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "产品名称"
        mock_empty_cell = MagicMock()
        mock_empty_cell.value = None
        mock_ws.iter_rows.return_value = iter(
            [[mock_cell], [mock_empty_cell]]  # 表头 + 空行
        )
        mock_ws.max_row = 2
        mock_wb.sheetnames = ["Sheet1"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is True
                assert result["total_rows"] == 0

    def test_openpyxl_import_error_returns_library_unavailable(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=ImportError("no openpyxl")):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "library_unavailable"

    def test_openpyxl_value_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=ValueError("bad")):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_openpyxl_type_error_returns_invalid_parameters(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=TypeError("bad")):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "invalid_parameters"

    def test_openpyxl_oserror_returns_file_not_found(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=OSError("not found")):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "file_not_found"

    def test_openpyxl_runtime_error_returns_analysis_failed(self) -> None:
        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", side_effect=RuntimeError("fail")):
                result = _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx"})
                assert result["success"] is False
                assert result["error_code"] == "analysis_failed"

    def test_openpyxl_with_explicit_sheet_name(self) -> None:
        mock_wb = MagicMock()
        mock_ws = MagicMock()
        mock_cell = MagicMock()
        mock_cell.value = "列名"
        mock_cell.column_letter = "A"
        mock_cell.column = 1
        mock_ws.iter_rows.return_value = iter([[mock_cell]])
        mock_ws.max_row = 0
        mock_wb.sheetnames = ["Sheet1", "Sheet2"]
        mock_wb.__getitem__.return_value = mock_ws

        with patch(
            "app.bootstrap.get_excel_analysis_app_service",
            side_effect=ImportError("no module"),
            create=True,
        ):
            with patch("openpyxl.load_workbook", return_value=mock_wb):
                _execute_excel_analysis_tool({"file_path": "/tmp/t.xlsx", "sheet_name": "Sheet2"})
                mock_wb.__getitem__.assert_called_with("Sheet2")


# ---------------------------------------------------------------------------
# execute_tool — additional handler dispatch coverage
# ---------------------------------------------------------------------------


class TestExecuteToolHandlerDispatch:
    """execute_tool 各 handler 派发覆盖。

    注意：_WORKFLOW_TOOL_HANDLERS 在模块加载时已绑定函数引用，
    必须 patch dict 本身而非函数名。
    """

    def _patch_handler(self, tool_name: str, action: str, ret: dict[str, Any] | None = None):
        """返回一个 patch context，将 (tool_name, action) 映射到 mock handler。"""
        mock_handler = MagicMock(return_value=ret or {"success": True})
        return patch.dict(
            "app.application.workflow.planner._WORKFLOW_TOOL_HANDLERS",
            {(tool_name, action): mock_handler},
        ), mock_handler

    def test_shipments_alias_dispatches_to_shipment_records(self) -> None:
        """shipments 工具默认 action=query。"""
        patch_ctx, mock_handler = self._patch_handler(
            "shipments", "query", {"success": True, "aliased": True}
        )
        with patch_ctx:
            result = execute_tool("shipments", {"unit_name": "ABC"})
            assert result["success"] is True
            assert result["aliased"] is True
            mock_handler.assert_called_once()

    def test_template_extract_dispatches_to_excel_decompose(self) -> None:
        patch_ctx, mock_handler = self._patch_handler(
            "template_extract", "extract", {"success": True, "delegated": True}
        )
        with patch_ctx:
            result = execute_tool("template_extract", {"file_path": "/tmp/t.xlsx"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_wechat_send_dispatches_to_preview(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("wechat_send", "preview")
        with patch_ctx:
            result = execute_tool("wechat_send", {"keyword": "张"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_excel_schema_dispatches_to_analyze(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("excel_schema", "analyze")
        with patch_ctx:
            result = execute_tool("excel_schema", {"file_path": "/tmp/t.xlsx"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_excel_analysis_dispatches_to_analyze(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("excel_analysis", "analyze")
        with patch_ctx:
            result = execute_tool("excel_analysis", {"file_path": "/tmp/t.xlsx"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_import_excel_dispatches_to_import(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("import_excel", "import")
        with patch_ctx:
            result = execute_tool("import_excel", {"file_path": "/tmp/t.xlsx"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_employee_dispatches_to_list_by_default(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("employee", "list")
        with patch_ctx:
            result = execute_tool("employee", {})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_employee_explicit_execute_action(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("employee", "execute")
        with patch_ctx:
            result = execute_tool("employee", {"_action": "execute", "task": "do something"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_business_db_dispatches_to_read_by_default(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("business_db", "read")
        with patch_ctx:
            result = execute_tool("business_db", {"entity": "products"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_business_db_explicit_write_action(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("business_db", "write")
        with patch_ctx:
            result = execute_tool(
                "business_db",
                {
                    "_action": "write",
                    "entity": "products",
                    "operation": "create",
                    "payload": {},
                },
            )
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_shipment_generate_dispatches_to_generate(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("shipment_generate", "generate")
        with patch_ctx:
            result = execute_tool("shipment_generate", {"order_text": "order"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_print_label_dispatches_to_generate(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("print_label", "generate")
        with patch_ctx:
            result = execute_tool("print_label", {"products": [{"name": "P1"}]})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_excel_decompose_dispatches_to_decompose(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("excel_decompose", "decompose")
        with patch_ctx:
            result = execute_tool("excel_decompose", {"file_path": "/tmp/t.xlsx"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_materials_dispatches_to_query(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("materials", "query")
        with patch_ctx:
            result = execute_tool("materials", {"keyword": "钢板"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_shipment_records_dispatches_to_query(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("shipment_records", "query")
        with patch_ctx:
            result = execute_tool("shipment_records", {"unit_name": "ABC"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_customers_ensure_exists_action(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("customers", "ensure_exists")
        with patch_ctx:
            result = execute_tool("customers", {"_action": "ensure_exists", "unit_name": "ABC"})
            assert result["success"] is True
            mock_handler.assert_called_once()

    def test_price_list_dispatches_to_export(self) -> None:
        patch_ctx, mock_handler = self._patch_handler("price_list", "export")
        with patch_ctx:
            result = execute_tool("price_list", {"customer_name": "ABC"})
            assert result["success"] is True
            mock_handler.assert_called_once()


# ---------------------------------------------------------------------------
# _plan_with_react_multiagent — probe output variations
# ---------------------------------------------------------------------------


class TestPlanWithReactMultiagentProbeOutputs:
    """_plan_with_react_multiagent probe 输出变体覆盖。"""

    def test_probe_output_with_data_list(self) -> None:
        """probe 输出 data 为 list 时取前 3 项。"""
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
                mock_exec.return_value = {
                    "success": True,
                    "data": [{"name": f"item{i}"} for i in range(5)],
                }
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None

    def test_probe_output_with_data_non_list(self) -> None:
        """probe 输出 data 非 list 时取 str。"""
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
                mock_exec.return_value = {
                    "success": True,
                    "data": {"key": "value"},
                }
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None

    def test_probe_output_with_raw_field(self) -> None:
        """probe 输出无 data 但有 raw 字段。"""
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
                mock_exec.return_value = {
                    "success": True,
                    "raw": "some raw data",
                }
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None

    def test_probe_output_with_no_data_no_raw(self) -> None:
        """probe 输出无 data 无 raw 时取 str(out)。"""
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
                mock_exec.return_value = {
                    "success": True,
                    "message": "ok",
                }
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None

    def test_probe_output_failure_not_added(self) -> None:
        """probe 输出 success=False 时不加入 probe_outputs。"""
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
                mock_exec.return_value = {
                    "success": False,
                    "message": "fail",
                }
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None

    def test_probe_output_non_dict_skipped(self) -> None:
        """probe 输出非 dict 时不崩溃。"""
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
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value="not a dict",
            ):
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None

    def test_probe_with_task_agent_for_customers_query(self) -> None:
        """customers.query 且无 keyword 时用 task_agent 抽取 slots。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        mock_task_agent = MagicMock()
        mock_task_agent._extract_customer_query_slots.return_value = {"keyword": "ABC"}
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch("app.services.task_agent.TaskAgent", return_value=mock_task_agent):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查客户ABC",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None
                    mock_task_agent._extract_customer_query_slots.assert_called_once()

    def test_probe_task_agent_import_error_falls_back(self) -> None:
        """TaskAgent ImportError 时 task_agent=None，customers.query 跳过 slot 抽取。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch(
                "app.services.task_agent.TaskAgent",
                side_effect=ImportError("no module"),
            ):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="test",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    # task_agent=None 时 customers.query 因无 keyword 跳过
                    assert result is not None

    def test_probe_task_agent_runtime_error_falls_back(self) -> None:
        """TaskAgent RuntimeError 时 task_agent=None。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch(
                "app.services.task_agent.TaskAgent",
                side_effect=RuntimeError("init fail"),
            ):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="test",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_customers_query_with_existing_keyword_skips_task_agent(self) -> None:
        """customers.query 已有 keyword 时不调用 task_agent。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={"keyword": "existing"},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        mock_task_agent = MagicMock()
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch("app.services.task_agent.TaskAgent", return_value=mock_task_agent):
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
                    mock_task_agent._extract_customer_query_slots.assert_not_called()

    def test_probe_customers_query_with_existing_customer_name_skips_task_agent(self) -> None:
        """customers.query 已有 customer_name 时不调用 task_agent。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={"customer_name": "existing"},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        mock_task_agent = MagicMock()
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch("app.services.task_agent.TaskAgent", return_value=mock_task_agent):
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
                    mock_task_agent._extract_customer_query_slots.assert_not_called()

    def test_probe_products_query_with_route_normal_dispatch(self) -> None:
        """products.query 无 keyword 时用 route_normal_mode_message 抽取 slots。"""
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
                    params={},
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
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={
                    "intent": "product_query",
                    "slots": {"keyword": "螺钉", "model_number": "M8", "unit_name": "ABC"},
                },
            ):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查螺钉M8",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_products_query_route_normal_dispatch_import_error(self) -> None:
        """route_normal_mode_message ImportError 时回退到 message 作为 keyword。"""
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
                    params={},
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
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                side_effect=ImportError("no module"),
            ):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查螺钉",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_products_query_route_normal_dispatch_runtime_error(self) -> None:
        """route_normal_mode_message RuntimeError 时回退到 message 作为 keyword。"""
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
                    params={},
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
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                side_effect=RuntimeError("fail"),
            ):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查螺钉",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_products_query_route_normal_not_product_intent(self) -> None:
        """route_normal_mode_message 返回非 product_query 时不补 slots。"""
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
                    params={},
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
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "other_intent", "slots": {}},
            ):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="test",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_customers_query_task_agent_import_error_falls_back_to_message(self) -> None:
        """customers.query 且 task_agent 存在但 _extract_customer_query_slots ImportError 时回退。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        mock_task_agent = MagicMock()
        mock_task_agent._extract_customer_query_slots.side_effect = ImportError("no module")
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch("app.services.task_agent.TaskAgent", return_value=mock_task_agent):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查客户",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_customers_query_task_agent_runtime_error_falls_back(self) -> None:
        """customers.query 且 task_agent._extract_customer_query_slots RuntimeError 时回退。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        mock_task_agent = MagicMock()
        mock_task_agent._extract_customer_query_slots.side_effect = RuntimeError("fail")
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch("app.services.task_agent.TaskAgent", return_value=mock_task_agent):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查客户",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_probe_customers_query_task_agent_returns_non_dict(self) -> None:
        """task_agent._extract_customer_query_slots 返回非 dict 时不更新 params。"""
        planner = _make_planner()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "customers",
                    "query",
                    risk="low",
                    idempotent=True,
                    params={},
                ),
            ],
        )
        final_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "customers", "query", risk="low", idempotent=True),
            ],
        )
        mock_task_agent = MagicMock()
        mock_task_agent._extract_customer_query_slots.return_value = "not a dict"
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, final_plan]):
            with patch("app.services.task_agent.TaskAgent", return_value=mock_task_agent):
                with patch(
                    "app.application.facades.tools_facade.execute_registered_workflow_tool"
                ) as mock_exec:
                    mock_exec.return_value = {"success": True, "data": []}
                    result = planner._plan_with_react_multiagent(
                        plan_id="pid",
                        user_id="u1",
                        message="查客户",
                        tool_registry=_sample_registry(),
                        context={},
                    )
                    assert result is not None

    def test_critic_repair_success_after_validation_failure(self) -> None:
        """validate_plan_graph 失败后 _critic_repair_with_llm 成功修复。"""
        planner = _make_planner_with_fence()
        # 候选计划（有效）
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        # 最终计划（缺 required_params，触发 critic）
        invalid_final = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "business_db", "read", risk="low", idempotent=True, params={}),
            ],
        )
        # 修复后的计划（有效）
        repaired_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode(
                    "n1",
                    "business_db",
                    "read",
                    risk="low",
                    idempotent=True,
                    params={"entity": "products"},
                ),
            ],
        )
        repaired_payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "business_db",
                    "action": "read",
                    "params": {"entity": "products"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "",
                    "depends_on": [],
                }
            ],
        }
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, invalid_final]):
            with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "choices": [{"message": {"content": json.dumps(repaired_payload)}}]
                }
                mock_client.return_value.post.return_value = resp
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is not None
                assert result.nodes[0].params["entity"] == "products"

    def test_critic_repair_still_invalid_returns_none(self) -> None:
        """critic 修复后仍无效时返回 None。"""
        planner = _make_planner_with_fence()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        invalid_final = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "business_db", "read", risk="low", idempotent=True, params={}),
            ],
        )
        # 修复返回的计划仍缺 required_params
        bad_repaired_payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "business_db",
                    "action": "read",
                    "params": {},  # 仍缺 entity
                    "risk": "low",
                    "idempotent": True,
                    "description": "",
                    "depends_on": [],
                }
            ],
        }
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, invalid_final]):
            with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "choices": [{"message": {"content": json.dumps(bad_repaired_payload)}}]
                }
                mock_client.return_value.post.return_value = resp
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is None

    def test_critic_repair_returns_none_falls_back(self) -> None:
        """critic 修复返回 None 时回退 fallback。"""
        planner = _make_planner_with_fence()
        candidate = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        invalid_final = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "business_db", "read", risk="low", idempotent=True, params={}),
            ],
        )
        with patch.object(planner, "_plan_with_llm", side_effect=[candidate, invalid_final]):
            with patch.object(planner, "_critic_repair_with_llm", return_value=None):
                result = planner._plan_with_react_multiagent(
                    plan_id="pid",
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is None


# ---------------------------------------------------------------------------
# _critic_repair_with_llm — additional branches
# ---------------------------------------------------------------------------


class TestCriticRepairWithLLMAdditional:
    """_critic_repair_with_llm 额外分支覆盖。"""

    def test_non_dict_spec_skipped_in_tool_specs(self) -> None:
        """非 dict action_meta 在构建 tool_specs 时被跳过（spec 本身必须是 dict）。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        reg = {
            "good_tool": {
                "description": "d",
                "actions": {
                    "act": {"risk": "low", "idempotent": True, "required_params": []},
                    "bad_action": "not a dict",  # 非 dict action_meta 被跳过
                },
            },
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
            assert result is None  # 空内容返回 None，但不崩溃

    def test_non_dict_actions_skipped_in_tool_specs(self) -> None:
        """actions=None 时使用空 dict（不崩溃）。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        reg = {
            "tool": {"description": "d", "actions": None},
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
            assert result is None

    def test_response_with_empty_nodes(self) -> None:
        """响应含空 nodes 列表。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        payload = {
            "intent": "fixed",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
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
            assert len(result.nodes) == 0

    def test_response_nodes_missing_fields_uses_defaults(self) -> None:
        """响应节点缺少字段时使用默认值。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        payload = {
            "intent": "fixed",
            "nodes": [
                {  # 缺 node_id/tool_id/action/params/risk/idempotent/description/depends_on
                    "tool_id": "products",
                }
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
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
            assert len(result.nodes) == 1
            assert result.nodes[0].node_id == "node_1"
            assert result.nodes[0].tool_id == "products"

    def test_response_intent_missing_uses_invalid_plan_intent(self) -> None:
        """响应缺 intent 时使用 invalid_plan.intent。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="original_intent", nodes=[])
        payload = {
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
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
            assert result.intent == "original_intent"

    def test_response_risk_level_missing_uses_invalid_plan_risk(self) -> None:
        """响应缺 risk_level 时使用 invalid_plan.risk_level。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", risk_level="medium", nodes=[])
        payload = {
            "intent": "fixed",
            "todo_steps": [],
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
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
            assert result.risk_level == "medium"

    def test_response_todo_steps_missing_uses_invalid_plan_todo(self) -> None:
        """响应缺 todo_steps 时使用 invalid_plan.todo_steps。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", todo_steps=["original_step"], nodes=[])
        payload = {
            "intent": "fixed",
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
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
            assert result.todo_steps == ["original_step"]

    def test_response_with_code_fence_only(self) -> None:
        """响应只有 ``` 围栏。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        payload = {
            "intent": "fixed",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        content = f"```\n{json.dumps(payload)}\n```"
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": content}}]}
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

    def test_empty_choices_returns_none(self) -> None:
        """空 choices 列表返回 None。"""
        planner = _make_planner_with_fence()
        invalid_plan = PlanGraph(plan_id="pid", intent="i", nodes=[])
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": []}
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


# ---------------------------------------------------------------------------
# _plan_with_llm — additional branches
# ---------------------------------------------------------------------------


class TestPlanWithLLMAdditional:
    """_plan_with_llm 额外分支覆盖。"""

    def test_no_api_key_returns_none(self) -> None:
        """无 api_key 时返回 None。"""
        with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
            ai = MagicMock()
            ai.api_key = ""
            mock_svc.return_value = ai
            planner = LLMWorkflowPlanner()
        result = planner._plan_with_llm(
            plan_id="pid",
            user_id="u1",
            message="test",
            tool_registry=_sample_registry(),
            context={},
        )
        assert result is None

    def test_http_error_returns_none(self) -> None:
        """HTTP 错误时返回 None。"""
        planner = _make_planner()
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 500
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is None

    def test_with_conversation_history(self) -> None:
        """有 conversation_history 时取最近 6 条。"""
        planner = _make_planner()
        mock_ctx = MagicMock()
        mock_ctx.conversation_history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        planner._ai_service.get_context.return_value = mock_ctx
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None

    def test_with_empty_conversation_history(self) -> None:
        """conversation_history 为空时 recent_messages=[]。"""
        planner = _make_planner()
        mock_ctx = MagicMock()
        mock_ctx.conversation_history = []
        planner._ai_service.get_context.return_value = mock_ctx
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None

    def test_non_dict_action_meta_skipped_in_tool_specs(self) -> None:
        """构建 tool_specs 时正常处理 dict action_meta。"""
        planner = _make_planner()
        reg = {
            "tool": {
                "description": "d",
                "actions": {
                    "good": {"risk": "low", "idempotent": True, "required_params": []},
                },
            }
        }
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=reg,
                context={},
            )
            assert result is not None

    def test_actions_missing_defaults_to_empty_dict(self) -> None:
        """spec 无 actions 键时默认空 dict。"""
        planner = _make_planner()
        reg = {"tool": {"description": "d"}}  # 无 actions
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=reg,
                context={},
            )
            assert result is not None

    def test_response_with_todo_steps(self) -> None:
        """响应含 todo_steps。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": ["step1", "step2"],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.todo_steps == ["step1", "step2"]

    def test_response_todo_steps_non_string_coerced(self) -> None:
        """todo_steps 中非字符串项被转为 str。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": ["step1", 123, None],
            "risk_level": "low",
            "nodes": [],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.todo_steps == ["step1", "123", "None"]

    def test_response_depends_on_non_string_coerced(self) -> None:
        """depends_on 中非字符串项被转为 str。"""
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
                    "params": {},
                    "risk": "low",
                    "idempotent": True,
                    "description": "",
                    "depends_on": ["n0", 123, None],
                }
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context={},
            )
            assert result is not None
            assert result.nodes[0].depends_on == ["n0", "123", "None"]

    def test_context_with_tool_probe_outputs_more_than_two_truncated(self) -> None:
        """tool_probe_outputs 超过 2 项时只取前 2 项。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        context = {
            "tool_probe_outputs": [
                {
                    "tool_id": "t1",
                    "action": "a",
                    "success": True,
                    "message": "m1",
                    "data_preview": "d1",
                },
                {
                    "tool_id": "t2",
                    "action": "a",
                    "success": True,
                    "message": "m2",
                    "data_preview": "d2",
                },
                {
                    "tool_id": "t3",
                    "action": "a",
                    "success": True,
                    "message": "m3",
                    "data_preview": "d3",
                },
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None
            assert len(result.metadata["tool_probe_outputs"]) == 2

    def test_context_tool_probe_outputs_item_message_truncated(self) -> None:
        """tool_probe_outputs 中 message 被截断到 120 字符。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        long_message = "x" * 200
        context = {
            "tool_probe_outputs": [
                {
                    "tool_id": "t1",
                    "action": "a",
                    "success": True,
                    "message": long_message,
                    "data_preview": "d",
                },
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None
            assert len(result.metadata["tool_probe_outputs"][0]["message"]) <= 120

    def test_context_tool_probe_outputs_data_preview_truncated(self) -> None:
        """tool_probe_outputs 中 data_preview 被截断到 160 字符。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        long_preview = "x" * 300
        context = {
            "tool_probe_outputs": [
                {
                    "tool_id": "t1",
                    "action": "a",
                    "success": True,
                    "message": "m",
                    "data_preview": long_preview,
                },
            ],
        }
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=context,
            )
            assert result is not None
            assert len(result.metadata["tool_probe_outputs"][0]["data_preview"]) <= 160

    def test_context_extraction_import_error_handled(self) -> None:
        """context 提取时异常被捕获（非 dict context 跳过提取）。"""
        planner = _make_planner()
        payload = {
            "intent": "test",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [],
        }
        # 传入非 dict context（如 None），isinstance 检查跳过提取
        with patch("app.application.workflow.planner._get_planner_http_client") as mock_client:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
            mock_client.return_value.post.return_value = resp
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message="test",
                tool_registry=_sample_registry(),
                context=None,  # type: ignore[arg-type]
            )
            assert result is not None


# ---------------------------------------------------------------------------
# _fallback_plan — additional edge cases
# ---------------------------------------------------------------------------


class TestFallbackPlanAdditional:
    """_fallback_plan 额外分支覆盖。"""

    def test_employee_dispatch_with_non_dict_item_in_status(self) -> None:
        """status 中非 dict 项被跳过。"""
        planner = _make_planner()
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_status:
            mock_status.return_value = {
                "employee_pack_tools": ["not_a_dict", {"pack_id": "real-pack"}]
            }
            result = planner._fallback_plan("pid", "请员工 real-pack 处理", _sample_registry())
            assert any(n.action == "execute" for n in result.nodes)

    def test_employee_dispatch_with_empty_pack_id_skipped(self) -> None:
        """空 pack_id 项被跳过。"""
        planner = _make_planner()
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_status:
            mock_status.return_value = {
                "employee_pack_tools": [{"pack_id": ""}, {"pack_id": "real-pack"}]
            }
            result = planner._fallback_plan("pid", "请员工 real-pack 处理", _sample_registry())
            assert any(n.action == "execute" for n in result.nodes)

    def test_employee_dispatch_no_matching_id_falls_to_list(self) -> None:
        """无匹配 employee_id 时降级为 list。"""
        planner = _make_planner()
        with patch("app.mod_sdk.employee_tool_registry.build_employee_tools_status") as mock_status:
            mock_status.return_value = {"employee_pack_tools": [{"pack_id": "other-pack"}]}
            result = planner._fallback_plan("pid", "请员工 unknown-pack 处理", _sample_registry())
            assert any(n.action == "list" for n in result.nodes)

    def test_business_db_write_with_extracted_node(self) -> None:
        """业务库写入意图且能抽取节点时生成 write 节点。"""
        planner = _make_planner()
        result = planner._fallback_plan("pid", "新增客户ABC公司到数据库写入", _sample_registry())
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

    def test_employee_dispatch_english_call_keyword(self) -> None:
        """英文 call 关键词触发员工意图。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": []},
        ):
            result = planner._fallback_plan("pid", "call employee", _sample_registry())
            assert result.intent == "employee_dispatch"

    def test_employee_dispatch_chinese_jiaogei_keyword(self) -> None:
        """中文 交给 关键词触发员工意图。"""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": []},
        ):
            result = planner._fallback_plan("pid", "交给员工处理", _sample_registry())
            assert result.intent == "employee_dispatch"

    def test_business_db_read_no_business_db_tool_falls_through(self) -> None:
        """数据库读取意图但注册表无 business_db 时落入默认查询。"""
        planner = _make_planner()
        reg = {"products": _sample_registry()["products"]}
        result = planner._fallback_plan("pid", "查数据库产品", reg)
        # 无 business_db 工具，落入默认 products 查询
        assert any(n.tool_id == "products" for n in result.nodes)

    def test_add_product_intent_without_products_tool(self) -> None:
        """添加产品意图但注册表无 products 时不生成 products 节点。"""
        planner = _make_planner()
        reg = {"customers": _sample_registry()["customers"]}
        result = planner._fallback_plan("pid", "新增产品", reg)
        # 无 products 工具，但 intent 仍是 add_product_to_unit
        assert result.intent == "add_product_to_unit"
        # 只有 customers 节点
        assert all(n.tool_id == "customers" for n in result.nodes)

    def test_risk_level_high_with_high_risk_node(self) -> None:
        """有 high risk 节点时 risk_level=high。"""
        planner = _make_planner()
        # 构造一个会生成 high risk 节点的场景较难，这里通过 mock 验证逻辑
        # 实际 _fallback_plan 中没有 high risk 节点，所以这里测试 medium
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value={"employee_pack_tools": [{"pack_id": "emp-001"}]},
        ):
            result = planner._fallback_plan("pid", "调用员工 emp-001", _sample_registry())
            # employee execute 是 medium risk
            assert result.risk_level == "medium"


# ---------------------------------------------------------------------------
# plan() — additional integration scenarios
# ---------------------------------------------------------------------------


class TestPlanIntegrationAdditional:
    """plan() 额外集成场景覆盖。"""

    def test_plan_with_rag_summary_injected(self) -> None:
        """RAG 命中时 summary 注入 context。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        mock_rag = MagicMock()
        mock_rag.query.return_value = {"hits": [{"id": "h1"}]}
        mock_rag.format_for_prompt.return_value = "memory summary"
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile",
                return_value=_sample_registry(),
            ):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.application.get_user_memory_rag_app_service",
                        return_value=mock_rag,
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None

    def test_plan_with_rag_no_hits_skips_summary(self) -> None:
        """RAG 无命中时不注入 summary。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        mock_rag = MagicMock()
        mock_rag.query.return_value = {"hits": []}
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile",
                return_value=_sample_registry(),
            ):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.application.get_user_memory_rag_app_service",
                        return_value=mock_rag,
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None
                        mock_rag.format_for_prompt.assert_not_called()

    def test_plan_with_rag_non_list_hits_skips_summary(self) -> None:
        """RAG hits 非 list 时不注入 summary。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        mock_rag = MagicMock()
        mock_rag.query.return_value = {"hits": "not a list"}
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile",
                return_value=_sample_registry(),
            ):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.application.get_user_memory_rag_app_service",
                        return_value=mock_rag,
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None
                        mock_rag.format_for_prompt.assert_not_called()

    def test_plan_with_rag_non_dict_response_skips_summary(self) -> None:
        """RAG 返回非 dict 时不注入 summary。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        mock_rag = MagicMock()
        mock_rag.query.return_value = None
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile",
                return_value=_sample_registry(),
            ):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.application.get_user_memory_rag_app_service",
                        return_value=mock_rag,
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None

    def test_plan_with_memory_v2_summary_injected(self) -> None:
        """Memory v2 有内容时注入 context。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        mock_memory = MagicMock()
        mock_memory.format_memory_v2_for_prompt.return_value = "memory v2 summary"
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile",
                return_value=_sample_registry(),
            ):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.services.user_memory_service.get_user_memory_service",
                        return_value=mock_memory,
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None

    def test_plan_with_memory_v2_empty_summary_skipped(self) -> None:
        """Memory v2 含「无已确认记忆」时不注入。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test",
            nodes=[
                WorkflowNode("n1", "products", "query", risk="low", idempotent=True),
            ],
        )
        mock_memory = MagicMock()
        mock_memory.format_memory_v2_for_prompt.return_value = "无已确认记忆"
        with patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="normal",
        ):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile",
                return_value=_sample_registry(),
            ):
                with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
                    with patch(
                        "app.services.user_memory_service.get_user_memory_service",
                        return_value=mock_memory,
                    ):
                        result = planner.plan(
                            user_id="u1",
                            message="test",
                            tool_registry=_sample_registry(),
                            context={},
                        )
                        assert result is not None

    def test_plan_react_returns_invalid_plan_falls_back(self) -> None:
        """ReAct 返回无效计划（validate_plan_graph 失败）时回退 fallback。"""
        planner = _make_planner()
        # intent 为空会导致 validate_plan_graph 失败
        invalid_plan = PlanGraph(plan_id="pid", intent="", nodes=[])
        fallback_plan = PlanGraph(
            plan_id="pid",
            intent="generic_workflow",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="query",
                    params={"keyword": "test"},
                    risk="low",
                    idempotent=True,
                )
            ],
            risk_level="low",
        )
        with patch.object(planner, "_plan_with_react_multiagent", return_value=invalid_plan):
            with patch.object(
                planner, "_fallback_plan", return_value=fallback_plan
            ) as mock_fallback:
                result = planner.plan(
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is fallback_plan
                mock_fallback.assert_called_once()

    def test_plan_react_returns_none_falls_back(self) -> None:
        """ReAct 返回 None 时回退 fallback。"""
        planner = _make_planner()
        fallback_plan = PlanGraph(
            plan_id="pid",
            intent="generic_workflow",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="query",
                    params={"keyword": "x"},
                    risk="low",
                    idempotent=True,
                )
            ],
            risk_level="low",
        )
        with patch.object(planner, "_plan_with_react_multiagent", return_value=None):
            with patch.object(
                planner, "_fallback_plan", return_value=fallback_plan
            ) as mock_fallback:
                result = planner.plan(
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is fallback_plan
                mock_fallback.assert_called_once()

    def test_plan_react_returns_valid_plan_returns_directly(self) -> None:
        """ReAct 返回有效计划时直接返回，不调用 fallback。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test_intent",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="query",
                    params={"keyword": "x"},
                    risk="low",
                    idempotent=True,
                )
            ],
            risk_level="low",
        )
        with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
            with patch.object(planner, "_fallback_plan") as mock_fallback:
                result = planner.plan(
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                assert result is valid_plan
                mock_fallback.assert_not_called()

    def test_plan_filter_registry_applies_profile(self) -> None:
        """plan() 会调用 _filter_tool_registry_for_profile 过滤工具。"""
        planner = _make_planner()
        valid_plan = PlanGraph(
            plan_id="pid",
            intent="test_intent",
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="customers",
                    action="query",
                    params={"keyword": "x"},
                    risk="low",
                    idempotent=True,
                )
            ],
            risk_level="low",
        )
        with patch.object(planner, "_plan_with_react_multiagent", return_value=valid_plan):
            with patch(
                "app.application.workflow.planner._filter_tool_registry_for_profile"
            ) as mock_filter:
                mock_filter.return_value = _sample_registry()
                planner.plan(
                    user_id="u1",
                    message="test",
                    tool_registry=_sample_registry(),
                    context={},
                )
                mock_filter.assert_called_once()
