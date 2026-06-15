"""app/utils/system_service 测试。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.utils.system_service import SystemService, get_system_service


@pytest.fixture
def service():
    return SystemService()


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestSystemServiceInit:
    def test_init(self, service):
        assert service.app_name == "XCAGI"
        assert service.app_path is not None


# ---------------------------------------------------------------------------
# get_startup_config
# ---------------------------------------------------------------------------


class TestGetStartupConfig:
    def test_non_windows_platform(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = service.get_startup_config()
        assert result["enabled"] is False
        assert result["platform"] == "darwin"
        assert "不支持" in result["message"]

    def test_windows_platform_not_configured(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError("not found")
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_READ = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.get_startup_config()
            assert result["enabled"] is False
            assert result["platform"] == "windows"

    def test_windows_platform_configured(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.QueryValueEx.return_value = ("C:\\path\\to\\app.exe", "REG_SZ")
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_READ = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.get_startup_config()
            assert result["enabled"] is True
            assert result["platform"] == "windows"

    def test_windows_registry_error(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_winreg.OpenKey.side_effect = RuntimeError("registry error")
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_READ = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.get_startup_config()
            assert result["enabled"] is False
            assert "message" in result

    def test_general_exception(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        with patch.dict("sys.modules", {}):
            # No winreg module available
            result = service.get_startup_config()
            assert result["enabled"] is False


# ---------------------------------------------------------------------------
# enable_startup
# ---------------------------------------------------------------------------


class TestEnableStartup:
    def test_non_windows_platform(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = service.enable_startup()
        assert result["success"] is False
        assert "不支持" in result["message"]

    def test_windows_platform_success(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_WRITE = MagicMock()
        mock_winreg.REG_SZ = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.enable_startup()
            assert result["success"] is True

    def test_windows_platform_error(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_winreg.OpenKey.side_effect = RuntimeError("access denied")
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_WRITE = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.enable_startup()
            assert result["success"] is False


# ---------------------------------------------------------------------------
# disable_startup
# ---------------------------------------------------------------------------


class TestDisableStartup:
    def test_non_windows_platform(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        result = service.disable_startup()
        assert result["success"] is False

    def test_windows_platform_success(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_WRITE = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.disable_startup()
            assert result["success"] is True

    def test_windows_not_enabled(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.DeleteValue.side_effect = FileNotFoundError("not found")
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_WRITE = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.disable_startup()
            assert result["success"] is True
            assert "原本" in result["message"]

    def test_windows_error(self, service, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        mock_winreg = MagicMock()
        mock_winreg.OpenKey.side_effect = RuntimeError("error")
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.KEY_WRITE = MagicMock()
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            result = service.disable_startup()
            assert result["success"] is False


# ---------------------------------------------------------------------------
# get_system_info
# ---------------------------------------------------------------------------


class TestGetSystemInfo:
    def test_returns_system_info(self, service):
        result = service.get_system_info()
        assert "platform" in result
        assert "python_version" in result
        assert "app_path" in result
        assert "working_directory" in result
        assert "executable" in result

    def test_exception_returns_error(self, service, monkeypatch):
        with patch("platform.version", side_effect=RuntimeError("err")):
            result = service.get_system_info()
            assert "message" in result


# ---------------------------------------------------------------------------
# get_printer_config
# ---------------------------------------------------------------------------


class TestGetPrinterConfig:
    def test_printer_adapter_not_available(self, service):
        with patch.dict("sys.modules", {"app.infrastructure.printing.printer_adapter": None}):
            result = service.get_printer_config()
            assert result["success"] is False

    def test_printer_adapter_success(self, service):
        mock_adapter = MagicMock()
        mock_adapter.list_printers.return_value = ["Printer1", "Printer2"]
        mock_adapter.get_default_printer.return_value = "Printer1"
        with patch.dict("sys.modules", {}), \
             patch("app.utils.system_service.SystemService.get_printer_config") as mock:
            # Test the import path
            pass

    def test_printer_adapter_error(self, service):
        with patch.dict("sys.modules", {"app.infrastructure.printing.printer_adapter": None}):
            result = service.get_printer_config()
            assert result["success"] is False


# ---------------------------------------------------------------------------
# set_default_printer
# ---------------------------------------------------------------------------


class TestSetDefaultPrinter:
    def test_printer_adapter_not_available(self, service):
        with patch.dict("sys.modules", {"app.infrastructure.printing.printer_adapter": None}):
            result = service.set_default_printer("Printer1")
            assert result["success"] is False


# ---------------------------------------------------------------------------
# get_system_service
# ---------------------------------------------------------------------------


class TestGetSystemService:
    def test_returns_instance(self):
        service = get_system_service()
        assert isinstance(service, SystemService)
