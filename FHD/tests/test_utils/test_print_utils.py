"""Tests for app.utils.print_utils — coverage ramp."""

from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import pytest

from app.utils.print_utils import PrinterUtils


# ========================= PrinterUtils ==================================


class TestPrinterUtils:
    def test_is_print_backend_available(self):
        pu = PrinterUtils()
        result = pu._is_print_backend_available()
        assert isinstance(result, bool)

    def test_build_unavailable_result(self):
        pu = PrinterUtils()
        result = pu._build_unavailable_result()
        assert result["success"] is False
        assert "message" in result

    def test_get_available_printers_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.get_available_printers()
            assert result == []

    def test_get_printer_status_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu._get_printer_status(0)
            assert result == "不可用"

    def test_get_printer_status_known_code(self):
        pu = PrinterUtils()
        with patch("app.utils.print_utils._PRINT_BACKEND_AVAILABLE", True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.PRINTER_STATUS_PAUSED = 1
            mock_win32print.PRINTER_STATUS_ERROR = 2
            mock_win32print.PRINTER_STATUS_PRINTING = 512
            result = pu._get_printer_status(0)
            assert result == "就绪"

    def test_ensure_com_initialized_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            pu._ensure_com_initialized()
            assert pu._com_initialized is False

    def test_ensure_com_initialized_success(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com:
            pu._ensure_com_initialized()
            mock_com.CoInitialize.assert_called_once()
            assert pu._com_initialized is True

    def test_ensure_com_initialized_already_done(self):
        pu = PrinterUtils()
        pu._com_initialized = True
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com:
            pu._ensure_com_initialized()
            mock_com.CoInitialize.assert_not_called()

    def test_print_file_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.print_file("/tmp/test.pdf", "printer1")
            assert result["success"] is False

    def test_monitor_print_job_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.monitor_print_job("printer1")
            assert result is False

    def test_get_default_printer_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.get_default_printer()
            assert result is None

    def test_test_printer_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.test_printer("printer1")
            assert result["success"] is False

    def test_get_document_printer_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.get_document_printer()
            assert result is None

    def test_get_label_printer_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu.get_label_printer()
            assert result is None

    def test_print_file_no_printer_name(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True):
            result = pu.print_file("/tmp/test.pdf", printer_name=None)
            assert result["success"] is False
            assert "未指定打印机名称" in result["message"]

    def test_print_file_not_exists(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=False):
            result = pu.print_file("/tmp/nonexistent.pdf", "printer1")
            assert result["success"] is False
            assert "文件不存在" in result["message"]

    def test_get_document_printer_no_printers(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=[]):
            result = pu.get_document_printer()
            assert result is None

    def test_get_label_printer_no_printers(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=[]):
            result = pu.get_label_printer()
            assert result is None

    def test_get_document_printer_with_keyword_match(self):
        pu = PrinterUtils()
        printers = [
            {"name": "SomeOtherPrinter", "status": "就绪", "is_default": False},
            {"name": "HP LaserJet", "status": "就绪", "is_default": True},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_document_printer()
            assert result == "HP LaserJet"

    def test_get_label_printer_with_keyword_match(self):
        pu = PrinterUtils()
        printers = [
            {"name": "TSC Printer", "status": "就绪", "is_default": False},
            {"name": "HP LaserJet", "status": "就绪", "is_default": True},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_label_printer()
            assert result == "TSC Printer"

    def test_get_document_printer_fallback_first(self):
        pu = PrinterUtils()
        printers = [
            {"name": "RandomPrinter", "status": "就绪", "is_default": True},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_document_printer()
            assert result == "RandomPrinter"

    def test_get_label_printer_fallback_last(self):
        pu = PrinterUtils()
        printers = [
            {"name": "RandomPrinter1", "status": "就绪", "is_default": True},
            {"name": "RandomPrinter2", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_label_printer()
            assert result == "RandomPrinter2"

    def test_get_default_printer_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.GetDefaultPrinter.side_effect = RuntimeError("no printer")
            result = pu.get_default_printer()
            assert result is None

    def test_get_document_printer_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", side_effect=RuntimeError("err")):
            result = pu.get_document_printer()
            assert result is None

    def test_get_label_printer_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", side_effect=RuntimeError("err")):
            result = pu.get_label_printer()
            assert result is None
