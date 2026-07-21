"""Tests for app.application.tools.shipment_crud_tools.

覆盖 delete_order / update_order / list_orders 三个核心执行器。Mock service 层
（ShipmentApplicationService），不依赖真实数据库或网络。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.tools import shipment_crud_tools


class TestDeleteOrder:
    """delete_order 执行器测试套件。"""

    def test_delete_order_without_confirm_returns_needs_confirm(self):
        """未传 confirm=true 时应拒绝执行并返回 needs_confirm=True。"""
        result = shipment_crud_tools.delete_order({"order_number": "42", "confirm": False})
        assert result["success"] is False
        assert result.get("needs_confirm") is True
        assert result["order_number"] == "42"
        assert "confirm=true" in result["message"]

    def test_delete_order_missing_order_number_returns_error(self):
        """缺少 order_number 时应返回错误。"""
        result = shipment_crud_tools.delete_order({"confirm": True})
        assert result["success"] is False
        assert result["error"] == "order_number is required"

    def test_delete_order_invalid_order_number_returns_error(self):
        """非数字 order_number 应返回 invalid_order_number。"""
        result = shipment_crud_tools.delete_order({"order_number": "abc", "confirm": True})
        assert result["success"] is False
        assert result["error"] == "invalid_order_number"

    def test_delete_order_with_confirm_calls_service_delete(self):
        """传 confirm=true 时应调用 service.delete_shipment_record 并返回成功结果。

        service 返回不带 message 时，执行器应自动生成默认中文提示。
        """
        mock_svc = MagicMock()
        mock_svc.delete_shipment_record.return_value = {"success": True}
        with patch.object(shipment_crud_tools, "_get_service", return_value=mock_svc):
            result = shipment_crud_tools.delete_order({"order_number": "42", "confirm": True})

        mock_svc.delete_shipment_record.assert_called_once_with(42)
        assert result["success"] is True
        assert result["order_number"] == "42"
        assert "42 已删除" in result["message"]


class TestUpdateOrder:
    """update_order 执行器测试套件。"""

    def test_update_order_without_confirm_returns_needs_confirm(self):
        """未传 confirm=true 时应拒绝执行。"""
        result = shipment_crud_tools.update_order(
            {"order_number": "42", "fields": {"status": "pending"}, "confirm": False}
        )
        assert result["success"] is False
        assert result.get("needs_confirm") is True
        assert result["preview_fields"] == {"status": "pending"}

    def test_update_order_missing_fields_returns_error(self):
        """缺少 fields 参数应返回错误。"""
        result = shipment_crud_tools.update_order({"order_number": "42", "confirm": True})
        assert result["success"] is False
        assert result["error"] == "fields must be a non-empty dict"

    def test_update_order_invalid_status_returns_error(self):
        """非法 status 值应被白名单拦截。"""
        result = shipment_crud_tools.update_order(
            {
                "order_number": "42",
                "fields": {"status": "invalid_status"},
                "confirm": True,
            }
        )
        assert result["success"] is False
        assert result["error"] == "invalid_status"

    def test_update_order_with_confirm_calls_service_update(self):
        """传 confirm=true 时应调用 service.update_shipment_record。"""
        mock_svc = MagicMock()
        mock_svc.update_shipment_record.return_value = {"success": True, "data": {"id": 42}}
        with patch.object(shipment_crud_tools, "_get_service", return_value=mock_svc):
            result = shipment_crud_tools.update_order(
                {
                    "order_number": "42",
                    "fields": {
                        "unit_name": "新客户",
                        "status": "printed",
                        "quantity_kg": 100.5,
                    },
                    "confirm": True,
                }
            )

        mock_svc.update_shipment_record.assert_called_once_with(
            42, unit_name="新客户", status="printed", quantity_kg=100.5
        )
        assert result["success"] is True
        assert result["order_number"] == "42"


class TestListOrders:
    """list_orders 执行器测试套件。"""

    def test_list_orders_no_filters_calls_get_orders(self):
        """无过滤条件时调用 get_orders。"""
        mock_svc = MagicMock()
        mock_svc.get_orders.return_value = [{"id": 1}, {"id": 2}]
        with patch.object(shipment_crud_tools, "_get_service", return_value=mock_svc):
            result = shipment_crud_tools.list_orders({})

        mock_svc.get_orders.assert_called_once_with(limit=20)
        assert result["success"] is True
        assert result["count"] == 2
        assert result["data"] == [{"id": 1}, {"id": 2}]

    def test_list_orders_with_keyword_calls_search(self):
        """有 keyword 时调用 search_orders 并截断到 limit。"""
        mock_svc = MagicMock()
        mock_svc.search_orders.return_value = [{"id": i} for i in range(50)]
        with patch.object(shipment_crud_tools, "_get_service", return_value=mock_svc):
            result = shipment_crud_tools.list_orders({"filters": {"keyword": "abc"}, "limit": 5})

        mock_svc.search_orders.assert_called_once_with("abc")
        assert result["success"] is True
        assert result["count"] == 5  # 截断到 limit

    def test_list_orders_with_unit_name_calls_get_shipment_records(self):
        """有 unit_name 时调用 get_shipment_records。"""
        mock_svc = MagicMock()
        mock_svc.get_shipment_records.return_value = [{"id": 1, "purchase_unit": "甲公司"}]
        with patch.object(shipment_crud_tools, "_get_service", return_value=mock_svc):
            result = shipment_crud_tools.list_orders(
                {"filters": {"unit_name": "甲公司"}, "limit": 10}
            )

        mock_svc.get_shipment_records.assert_called_once_with("甲公司", limit=10)
        assert result["success"] is True
        assert result["count"] == 1

    def test_list_orders_limit_capped_at_200(self):
        """limit 上限 200，传入 500 应被夹紧。"""
        mock_svc = MagicMock()
        mock_svc.get_orders.return_value = []
        with patch.object(shipment_crud_tools, "_get_service", return_value=mock_svc):
            shipment_crud_tools.list_orders({"limit": 500})

        mock_svc.get_orders.assert_called_once_with(limit=200)
