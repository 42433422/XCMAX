"""Phase 2: SmartSearchApplicationService 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.smart_search_app_service import (
    SmartSearchApplicationService,
    get_smart_search_app_service,
)


@pytest.fixture
def svc() -> SmartSearchApplicationService:
    return SmartSearchApplicationService()


class TestSmartSearchApplicationService:
    @patch("app.application.product_app_service.get_product_application_service")
    def test_search_products(self, mock_get: MagicMock, svc: SmartSearchApplicationService):
        mock_get.return_value.get_products.return_value = {"success": True, "data": [{"id": 1}]}
        out = svc.search_products("PU")
        assert out["success"] is True
        mock_get.return_value.get_products.assert_called_once_with(keyword="PU", page=1, per_page=20)

    @patch("app.application.customer_app_service.get_customer_app_service")
    def test_search_customers(self, mock_get: MagicMock, svc: SmartSearchApplicationService):
        mock_get.return_value.get_all.return_value = {"success": True, "data": []}
        out = svc.search_customers("甲")
        assert out["success"] is True

    @patch("app.application.excel_vector_app_service.get_excel_vector_search_app_service")
    def test_search_excel_vector_no_indexes(self, mock_get: MagicMock, svc: SmartSearchApplicationService):
        mock_get.return_value.list_indexes.return_value = {"indexes": []}
        out = svc.search_excel_vector("keyword")
        assert out["success"] is True
        assert out["hits"] == []
        assert out["index_id"] is None

    @patch("app.application.excel_vector_app_service.get_excel_vector_search_app_service")
    def test_search_excel_vector_query(self, mock_get: MagicMock, svc: SmartSearchApplicationService):
        mock_get.return_value.list_indexes.return_value = {"indexes": [{"index_id": "idx1"}]}
        mock_get.return_value.query.return_value = {"success": True, "hits": [{"text": "x"}]}
        out = svc.search_excel_vector("q", top_k=3)
        assert out["hits"][0]["text"] == "x"
        mock_get.return_value.query.assert_called_once_with(index_id="idx1", query_text="q", top_k=3)

    @patch("app.application.excel_vector_app_service.get_excel_vector_search_app_service")
    def test_search_excel_vector_query_failure(self, mock_get: MagicMock, svc: SmartSearchApplicationService):
        mock_get.return_value.list_indexes.return_value = {"indexes": [{"id": "idx2"}]}
        mock_get.return_value.query.side_effect = RuntimeError("vec down")
        out = svc.search_excel_vector("q")
        assert out["success"] is False
        assert out["index_id"] == "idx2"

    @patch.object(SmartSearchApplicationService, "search_products")
    @patch.object(SmartSearchApplicationService, "search_customers")
    @patch.object(SmartSearchApplicationService, "search_excel_vector")
    def test_search_scope_all(
        self,
        mock_excel: MagicMock,
        mock_cust: MagicMock,
        mock_prod: MagicMock,
        svc: SmartSearchApplicationService,
    ):
        mock_prod.return_value = {"success": True, "data": []}
        mock_cust.return_value = {"success": True, "data": []}
        mock_excel.return_value = {"success": True, "hits": []}
        out = svc.search("hello", scope="all")
        assert out["success"] is True
        assert set(out["results"].keys()) == {"products", "customers", "excel_vector"}

    @patch.object(SmartSearchApplicationService, "search_products")
    def test_search_products_scope_only(self, mock_prod: MagicMock, svc: SmartSearchApplicationService):
        mock_prod.return_value = {"success": True, "data": []}
        out = svc.search("x", scope="products")
        assert "products" in out["results"]
        assert "customers" not in out["results"]

    @patch.object(SmartSearchApplicationService, "search_products")
    def test_search_products_failure_still_returns_block(self, mock_prod: MagicMock, svc: SmartSearchApplicationService):
        mock_prod.side_effect = RuntimeError("db")
        out = svc.search("x", scope="products")
        assert out["results"]["products"]["success"] is False

    def test_get_singleton(self):
        import app.application.smart_search_app_service as mod

        mod._smart_search_app_service = None
        assert get_smart_search_app_service() is get_smart_search_app_service()
