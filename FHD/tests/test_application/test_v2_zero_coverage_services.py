"""Tests for zero-coverage V2 event-driven app services.

All V2 services share the same structure:
  - __init__: calls get_neuro_bus(), sets _correlation_prefix
  - _create_correlation_id(): returns f"{prefix}-{timestamp}-{id}"
  - execute_command(): creates NeuroEvent, publishes to bus, returns result dict
  - Module-level singleton + getter function

We test each service's unique prefix, event type construction, and source name.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Service metadata: (module_name, class_name, prefix, source, getter_name)
# ---------------------------------------------------------------------------
V2_SERVICES = [
    ("excel_vector_app_service_v2", "ExcelVectorAppServiceV2", "ai", "excelvectorappservice_v2", "get_excel_vector_app_service_v2"),
    ("file_analysis_app_service_v2", "FileAnalysisAppServiceV2", "ai", "fileanalysisappservice_v2", "get_file_analysis_app_service_v2"),
    ("material_app_service_v2", "MaterialAppServiceV2", "material", "materialappservice_v2", "get_material_app_service_v2"),
    ("ocr_app_service_v2", "OcrAppServiceV2", "ocr", "ocrappservice_v2", "get_ocr_app_service_v2"),
    ("print_app_service_v2", "PrintAppServiceV2", "print", "printappservice_v2", "get_print_app_service_v2"),
    ("product_import_app_service_v2", "ProductImportAppServiceV2", "product", "productimportappservice_v2", "get_product_import_app_service_v2"),
    ("template_app_service_v2", "TemplateAppServiceV2", "print", "templateappservice_v2", "get_template_app_service_v2"),
    ("unit_products_import_app_service_v2", "UnitProductsImportAppServiceV2", "product", "unitproductsimportappservice_v2", "get_unit_products_import_app_service_v2"),
    ("user_app_service_v2", "UserAppServiceV2", "auth", "userappservice_v2", "get_user_app_service_v2"),
    ("user_memory_vector_app_service_v2", "UserMemoryVectorAppServiceV2", "auth", "usermemoryvectorappservice_v2", "get_user_memory_vector_app_service_v2"),
    ("user_preference_app_service_v2", "UserPreferenceAppServiceV2", "auth", "userpreferenceappservice_v2", "get_user_preference_app_service_v2"),
    ("wechat_contact_app_service_v2", "WechatContactAppServiceV2", "wechat", "wechatcontactappservice_v2", "get_wechat_contact_app_service_v2"),
    ("wechat_task_app_service_v2", "WechatTaskAppServiceV2", "wechat", "wechattaskappservice_v2", "get_wechat_task_app_service_v2"),
    ("extract_log_app_service_v2", "ExtractLogAppServiceV2", "log", "extractlogappservice_v2", "get_extract_log_app_service_v2"),
]


def _make_service(module_name: str, class_name: str):
    """Import and instantiate a V2 service with mocked bus and instrumentation."""
    mod = __import__(f"app.application.{module_name}", fromlist=[class_name])
    cls = getattr(mod, class_name)

    mock_bus = MagicMock()
    mock_bus.publish = MagicMock(return_value=True)

    with patch(f"app.application.{module_name}.get_neuro_bus", return_value=mock_bus):
        with patch(
            f"app.application.{module_name}.instrument_application_service_class",
            side_effect=lambda cls_, **kw: cls_,
        ):
            svc = cls()

    return svc, mock_bus


# ---------------------------------------------------------------------------
# Parameterised tests for all V2 services
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_name,class_name,prefix,source,getter_name",
    V2_SERVICES,
    ids=[s[1] for s in V2_SERVICES],
)
class TestV2ServiceCommon:
    """Tests that apply to every V2 event-driven service."""

    def test_create_correlation_id_prefix(self, module_name, class_name, prefix, source, getter_name):
        """_create_correlation_id starts with the service's prefix."""
        svc, _ = _make_service(module_name, class_name)
        cid = svc._create_correlation_id()
        assert cid.startswith(f"{prefix}-")

    def test_create_correlation_id_format(self, module_name, class_name, prefix, source, getter_name):
        """_create_correlation_id follows the prefix-timestamp-id format."""
        svc, _ = _make_service(module_name, class_name)
        cid = svc._create_correlation_id()
        parts = cid.split("-")
        # prefix-YYYYMMDDHHMMSS-object_id
        assert len(parts) >= 3
        assert parts[0] == prefix

    @pytest.mark.asyncio
    async def test_execute_command_success(self, module_name, class_name, prefix, source, getter_name):
        """execute_command publishes event and returns success dict."""
        svc, mock_bus = _make_service(module_name, class_name)

        mock_event = MagicMock()
        mock_event.metadata.event_id = "evt-test-001"

        with patch("app.neuro_bus.events.base.NeuroEvent", return_value=mock_event):
            result = await svc.execute_command("create", {"key": "value"})

        assert result["success"] is True
        assert result["event_id"] == "evt-test-001"
        assert "correlation_id" in result
        mock_bus.publish.assert_called_once_with(mock_event)

    @pytest.mark.asyncio
    async def test_execute_command_event_type(self, module_name, class_name, prefix, source, getter_name):
        """execute_command constructs event_type as prefix.command_type."""
        svc, mock_bus = _make_service(module_name, class_name)

        mock_event = MagicMock()
        mock_event.metadata.event_id = "evt-test-002"

        with patch("app.neuro_bus.events.base.NeuroEvent", return_value=mock_event) as mock_neuro:
            await svc.execute_command("update", {"id": 1})

            call_kwargs = mock_neuro.call_args[1] if mock_neuro.call_args[1] else mock_neuro.call_args[0] if isinstance(mock_neuro.call_args[0], dict) else {}
            # Check keyword arguments
            if mock_neuro.call_args[1]:
                assert mock_neuro.call_args[1]["event_type"] == f"{prefix}.update"
                assert mock_neuro.call_args[1]["source"] == source
            else:
                # positional args
                assert mock_neuro.call_args[0][0] == f"{prefix}.update" or "event_type" in str(mock_neuro.call_args)

    @pytest.mark.asyncio
    async def test_execute_command_error_returns_failure(self, module_name, class_name, prefix, source, getter_name):
        """execute_command catches RECOVERABLE_ERRORS and returns failure dict."""
        svc, mock_bus = _make_service(module_name, class_name)

        with patch("app.neuro_bus.events.base.NeuroEvent", side_effect=RuntimeError("bus down")):
            result = await svc.execute_command("delete", {"id": 1})

        assert result["success"] is False
        assert "bus down" in result["message"]

    @pytest.mark.asyncio
    async def test_execute_command_value_error_returns_failure(self, module_name, class_name, prefix, source, getter_name):
        """execute_command catches ValueError (also in RECOVERABLE_ERRORS)."""
        svc, mock_bus = _make_service(module_name, class_name)

        with patch("app.neuro_bus.events.base.NeuroEvent", side_effect=ValueError("bad payload")):
            result = await svc.execute_command("import", {"data": None})

        assert result["success"] is False
        assert "bad payload" in result["message"]

    def test_singleton_getter(self, module_name, class_name, prefix, source, getter_name):
        """Module-level getter returns an instance of the correct class."""
        mod = __import__(f"app.application.{module_name}", fromlist=[getter_name])
        getter = getattr(mod, getter_name)
        cls = getattr(mod, class_name)

        mock_bus = MagicMock()
        with patch(f"app.application.{module_name}.get_neuro_bus", return_value=mock_bus):
            with patch(
                f"app.application.{module_name}.instrument_application_service_class",
                side_effect=lambda cls_, **kw: cls_,
            ):
                # Reset singleton
                singleton_var = f"_{module_name.replace('_app_service_v2', '').replace('_', '')}appservice_v2_instance"
                # Use the module's global dict to reset
                if hasattr(mod, singleton_var):
                    setattr(mod, singleton_var, None)
                instance = getter()

        assert isinstance(instance, cls)
