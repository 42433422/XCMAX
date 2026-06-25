"""Branch coverage for app.application.tools.exports.

Covers handle_price_list_export branches: missing customer, product fetch error,
docx generation error, file write error, success (0/4 branches).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.tools import exports


class TestHandlePriceListExport:
    def test_missing_customer_name_returns_failure(self):
        result = exports.handle_price_list_export({})
        assert result["success"] is False
        assert "客户名称" in result["message"]

    def test_empty_customer_name_returns_failure(self):
        result = exports.handle_price_list_export({"customer_name": "   "})
        assert result["success"] is False

    def test_product_fetch_error_returns_failure(self):
        with patch(
            "app.application.get_product_app_service",
            side_effect=RuntimeError("db down"),
        ):
            result = exports.handle_price_list_export({"customer_name": "Acme"})
        assert result["success"] is False
        assert "获取产品列表失败" in result["message"]

    def test_docx_generation_error_returns_failure(self):
        mock_svc = MagicMock()
        mock_svc.get_all_products.return_value = [{"name": "P"}]
        with (
            patch(
                "app.application.get_product_app_service",
                return_value=mock_svc,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                side_effect=RuntimeError("template missing"),
            ),
        ):
            result = exports.handle_price_list_export({"customer_name": "Acme"})
        assert result["success"] is False
        assert "价格表生成失败" in result["message"]

    def test_file_write_error_returns_failure(self, tmp_path):
        mock_svc = MagicMock()
        mock_svc.get_all_products.return_value = [{"name": "P"}]
        with (
            patch(
                "app.application.get_product_app_service",
                return_value=mock_svc,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(MagicMock(), None),
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"doc-bytes",
            ),
            patch(
                "app.application.tools.exports.Path.write_bytes",
                side_effect=OSError("disk full"),
            ),
        ):
            result = exports.handle_price_list_export({"customer_name": "Acme"})
        assert result["success"] is False
        assert "写文件失败" in result["message"]

    def test_success_with_keyword_search(self, tmp_path):
        mock_svc = MagicMock()
        mock_svc.search_products.return_value = [{"name": "P"}]
        with (
            patch(
                "app.application.get_product_app_service",
                return_value=mock_svc,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(MagicMock(), None),
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"doc-bytes",
            ),
        ):
            result = exports.handle_price_list_export(
                {"customer_name": "Acme", "keyword": "widget"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["customer_name"] == "Acme"
        assert result["product_count"] == 1
        mock_svc.search_products.assert_called_once()

    def test_success_without_keyword(self, tmp_path):
        mock_svc = MagicMock()
        mock_svc.get_all_products.return_value = [{"name": "P1"}, {"name": "P2"}]
        with (
            patch(
                "app.application.get_product_app_service",
                return_value=mock_svc,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(MagicMock(), None),
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"doc-bytes",
            ),
        ):
            result = exports.handle_price_list_export(
                {"customer_name": "Acme"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["product_count"] == 2
        mock_svc.get_all_products.assert_called_once()

    def test_success_without_workspace_root_uses_tempdir(self):
        mock_svc = MagicMock()
        mock_svc.get_all_products.return_value = []
        with (
            patch(
                "app.application.get_product_app_service",
                return_value=mock_svc,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(MagicMock(), None),
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"doc-bytes",
            ),
        ):
            result = exports.handle_price_list_export({"customer_name": "Acme"})
        assert result["success"] is True

    def test_products_not_list_coerced_to_empty(self, tmp_path):
        mock_svc = MagicMock()
        mock_svc.get_all_products.return_value = None  # not a list
        with (
            patch(
                "app.application.get_product_app_service",
                return_value=mock_svc,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(MagicMock(), None),
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"doc-bytes",
            ),
        ):
            result = exports.handle_price_list_export(
                {"customer_name": "Acme"},
                workspace_root=str(tmp_path),
            )
        assert result["success"] is True
        assert result["product_count"] == 0
