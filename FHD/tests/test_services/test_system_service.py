"""测试 system_service 模块 - 系统设置服务。"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.services.system_service import SystemService, get_system_service


class TestSystemServiceInit:
    """测试 SystemService 初始化。"""

    def test_init(self):
        svc = SystemService()
        assert svc.app_name == "XCAGI"
        assert svc.app_path is not None


class TestGetStartupConfig:
    """测试 get_startup_config 方法。"""

    def test_non_windows_platform(self):
        svc = SystemService()
        with patch.object(sys, "platform", "darwin"):
            result = svc.get_startup_config()
            assert result["enabled"] is False
            assert result["platform"] == "darwin"
            assert "不支持" in result["message"]

    def test_returns_app_path(self):
        svc = SystemService()
        result = svc.get_startup_config()
        assert "app_path" in result


class TestEnableStartup:
    """测试 enable_startup 方法。"""

    def test_non_windows_platform(self):
        svc = SystemService()
        with patch.object(sys, "platform", "darwin"):
            result = svc.enable_startup()
            assert result["success"] is False
            assert "不支持" in result["message"]


class TestDisableStartup:
    """测试 disable_startup 方法。"""

    def test_non_windows_platform(self):
        svc = SystemService()
        with patch.object(sys, "platform", "darwin"):
            result = svc.disable_startup()
            assert result["success"] is False
            assert "不支持" in result["message"]


class TestGetSystemInfo:
    """测试 get_system_info 方法。"""

    def test_returns_system_info(self):
        svc = SystemService()
        result = svc.get_system_info()
        assert "platform" in result
        assert "python_version" in result
        assert "app_path" in result
        assert "working_directory" in result
        assert "executable" in result

    def test_platform_matches_sys(self):
        svc = SystemService()
        result = svc.get_system_info()
        assert result["platform"] == sys.platform


class TestGetPrinterConfig:
    """测试 get_printer_config 方法。"""

    def test_printer_import_error(self):
        svc = SystemService()
        with patch.dict("sys.modules", {"app.services.printer_service": None}):
            result = svc.get_printer_config()
            assert result["success"] is False

    def test_printer_service_error(self):
        svc = SystemService()
        mock_ps = MagicMock()
        mock_ps.list_printers.side_effect = RuntimeError("no printer")
        with patch("app.services.printer_service.PrinterService", return_value=mock_ps):
            result = svc.get_printer_config()
            assert result["success"] is False

    def test_printer_service_success(self):
        svc = SystemService()
        mock_ps = MagicMock()
        mock_ps.list_printers.return_value = ["Printer1"]
        mock_ps.get_default_printer.return_value = "Printer1"
        with patch("app.services.printer_service.PrinterService", return_value=mock_ps):
            result = svc.get_printer_config()
            assert result["success"] is True
            assert result["printers"] == ["Printer1"]
            assert result["default_printer"] == "Printer1"


class TestSetDefaultPrinter:
    """测试 set_default_printer 方法。"""

    def test_set_default_success(self):
        svc = SystemService()
        mock_ps = MagicMock()
        mock_ps.set_default_printer.return_value = True
        with patch("app.services.printer_service.PrinterService", return_value=mock_ps):
            result = svc.set_default_printer("Printer1")
            assert result["success"] is True

    def test_set_default_failure(self):
        svc = SystemService()
        mock_ps = MagicMock()
        mock_ps.set_default_printer.return_value = False
        with patch("app.services.printer_service.PrinterService", return_value=mock_ps):
            result = svc.set_default_printer("BadPrinter")
            assert result["success"] is False

    def test_set_default_import_error(self):
        svc = SystemService()
        with patch.dict("sys.modules", {"app.services.printer_service": None}):
            result = svc.set_default_printer("Printer1")
            assert result["success"] is False


class TestGetSystemService:
    """测试工厂函数。"""

    def test_returns_instance(self):
        svc = get_system_service()
        assert isinstance(svc, SystemService)
