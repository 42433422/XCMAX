"""Branch coverage for app.application.product_import_app_service.

Covers __init__ service injection, singleton, and delegation methods (0/4 branches).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestInit:
    def test_init_with_explicit_service(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        assert app_svc._product_import_service is mock_svc

    def test_init_without_service_uses_factory(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        with patch(
            "app.services.get_product_import_service",
            return_value=mock_svc,
        ):
            app_svc = ProductImportApplicationService()
        assert app_svc._product_import_service is mock_svc


class TestImportFromFile:
    def test_delegates_to_service(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        mock_svc.import_products_from_excel.return_value = {"success": True, "count": 5}
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        result = app_svc.import_from_file("/path/to/file.xlsx", "Acme")
        assert result == {"success": True, "count": 5}
        mock_svc.import_products_from_excel.assert_called_once_with("/path/to/file.xlsx", "Acme")


class TestImportFromData:
    def test_delegates_to_service(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        mock_svc.batch_add_products.return_value = {"success": True, "count": 3}
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        products = [{"name": "P1"}, {"name": "P2"}, {"name": "P3"}]
        result = app_svc.import_from_data(products, "Acme")
        assert result == {"success": True, "count": 3}
        mock_svc.batch_add_products.assert_called_once_with(products, "Acme")

    def test_delegates_with_empty_list(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        mock_svc.batch_add_products.return_value = {"success": True, "count": 0}
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        result = app_svc.import_from_data([], "Acme")
        assert result["count"] == 0


class TestValidateImportData:
    def test_delegates_to_service(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        mock_svc.validate_products.return_value = {"valid": True, "errors": []}
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        result = app_svc.validate_import_data([{"name": "P1"}])
        assert result["valid"] is True
        mock_svc.validate_products.assert_called_once_with([{"name": "P1"}])


class TestGetImportHistory:
    def test_delegates_with_defaults(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        mock_svc.get_import_history.return_value = {"items": [], "total": 0}
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        result = app_svc.get_import_history()
        mock_svc.get_import_history.assert_called_once_with(page=1, per_page=20)

    def test_delegates_with_custom_pagination(self):
        from app.application.product_import_app_service import (
            ProductImportApplicationService,
        )

        mock_svc = MagicMock()
        mock_svc.get_import_history.return_value = {"items": [], "total": 0}
        app_svc = ProductImportApplicationService(product_import_service=mock_svc)
        result = app_svc.get_import_history(page=3, per_page=50)
        mock_svc.get_import_history.assert_called_once_with(page=3, per_page=50)


class TestSingletons:
    def test_get_product_import_app_service_singleton(self):
        import app.application.product_import_app_service as mod

        mod._product_import_app_service = None
        with patch("app.services.get_product_import_service", return_value=MagicMock()):
            from app.application.product_import_app_service import (
                get_product_import_app_service,
            )

            s1 = get_product_import_app_service()
            s2 = get_product_import_app_service()
        assert s1 is s2

    def test_get_product_import_application_service_singleton(self):
        import app.application.product_import_app_service as mod

        mod._product_import_app_service = None
        with patch("app.services.get_product_import_service", return_value=MagicMock()):
            from app.application.product_import_app_service import (
                get_product_import_application_service,
            )

            s1 = get_product_import_application_service()
            s2 = get_product_import_application_service()
        assert s1 is s2

    def test_init_product_import_app_service_overrides_singleton(self):
        import app.application.product_import_app_service as mod

        mod._product_import_app_service = None
        mock_svc = MagicMock()
        from app.application.product_import_app_service import (
            init_product_import_app_service,
        )

        result = init_product_import_app_service(mock_svc)
        assert result._product_import_service is mock_svc
        assert mod._product_import_app_service is result

    def test_init_product_import_application_service_overrides_singleton(self):
        import app.application.product_import_app_service as mod

        mod._product_import_app_service = None
        mock_svc = MagicMock()
        from app.application.product_import_app_service import (
            init_product_import_application_service,
        )

        result = init_product_import_application_service(mock_svc)
        assert result._product_import_service is mock_svc
        assert mod._product_import_app_service is result
