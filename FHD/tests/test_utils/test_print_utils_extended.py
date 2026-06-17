"""Extended tests for app.utils.print_utils — covering more branches."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.utils.print_utils import PrinterUtils


def _patch_win32_deps():
    """Context manager that patches win32print, win32api, pythoncom for macOS testing."""
    from unittest.mock import patch as _patch
    mock_win32print = MagicMock()
    mock_win32api = MagicMock()
    mock_pythoncom = MagicMock()
    return _patch.dict("sys.modules", {
        "win32print": mock_win32print,
        "win32api": mock_win32api,
        "pythoncom": mock_pythoncom,
        "win32api.stub": MagicMock(),
    })


# ========================= get_available_printers (backend available) ====


class TestGetAvailablePrintersWithBackend:
    def test_get_available_printers_success(self):
        pu = PrinterUtils()
        # EnumPrinters returns (flags, description, name, ...) tuples
        printers_data = [
            (2, "Printer1", "Printer1"),
            (2, "Printer2", "Printer2"),
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com, \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_com.CoInitialize.return_value = None
            mock_win32print.GetDefaultPrinter.return_value = "Printer1"
            mock_win32print.EnumPrinters.return_value = printers_data
            mock_win32print.PRINTER_ENUM_LOCAL = 2
            mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
            result = pu.get_available_printers()
            assert len(result) == 2
            assert result[0]["name"] == "Printer1"
            assert result[0]["is_default"] is True
            assert result[1]["is_default"] is False

    def test_get_available_printers_with_status(self):
        pu = PrinterUtils()
        printers_data = [
            ("flags", "desc", "Printer1", 0, 0, 0, 1),
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com, \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_com.CoInitialize.return_value = None
            mock_win32print.GetDefaultPrinter.return_value = "Printer1"
            mock_win32print.EnumPrinters.return_value = printers_data
            mock_win32print.PRINTER_ENUM_LOCAL = 2
            mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
            mock_win32print.PRINTER_STATUS_PAUSED = 1
            result = pu.get_available_printers()
            assert result[0]["status"] == "已暂停"

    def test_get_available_printers_short_info_with_status_fallback(self):
        pu = PrinterUtils()
        # Printer info with only 6 elements, status from index 5
        printers_data = [
            ("flags", "desc", "Printer1", 0, 0, "2"),
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com, \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_com.CoInitialize.return_value = None
            mock_win32print.GetDefaultPrinter.return_value = "Printer1"
            mock_win32print.EnumPrinters.return_value = printers_data
            mock_win32print.PRINTER_ENUM_LOCAL = 2
            mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
            mock_win32print.PRINTER_STATUS_ERROR = 2
            result = pu.get_available_printers()
            assert result[0]["status"] == "错误"

    def test_get_available_printers_short_info_status_non_int(self):
        pu = PrinterUtils()
        printers_data = [
            ("flags", "desc", "Printer1", 0, 0, "not_a_number"),
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com, \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_com.CoInitialize.return_value = None
            mock_win32print.GetDefaultPrinter.return_value = "Printer1"
            mock_win32print.EnumPrinters.return_value = printers_data
            mock_win32print.PRINTER_ENUM_LOCAL = 2
            mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
            result = pu.get_available_printers()
            assert result[0]["status"] == "就绪"

    def test_get_available_printers_no_default(self):
        pu = PrinterUtils()
        printers_data = [
            ("flags", "desc", "Printer1", 0, 0, 0, 0),
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com, \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_com.CoInitialize.return_value = None
            mock_win32print.GetDefaultPrinter.side_effect = Exception("no default")
            mock_win32print.EnumPrinters.return_value = printers_data
            mock_win32print.PRINTER_ENUM_LOCAL = 2
            mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
            result = pu.get_available_printers()
            assert len(result) == 1

    def test_get_available_printers_enum_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com, \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_com.CoInitialize.return_value = None
            mock_win32print.EnumPrinters.side_effect = RuntimeError("enum failed")
            mock_win32print.PRINTER_ENUM_LOCAL = 2
            mock_win32print.PRINTER_ENUM_CONNECTIONS = 4
            result = pu.get_available_printers()
            assert result == []


# ========================= _get_printer_status (more codes) ==============


class TestGetPrinterStatusMoreCodes:
    def test_status_paused(self):
        pu = PrinterUtils()
        with patch("app.utils.print_utils._PRINT_BACKEND_AVAILABLE", True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.PRINTER_STATUS_PAUSED = 1
            assert pu._get_printer_status(1) == "已暂停"

    def test_status_paper_jam(self):
        pu = PrinterUtils()
        with patch("app.utils.print_utils._PRINT_BACKEND_AVAILABLE", True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.PRINTER_STATUS_PAPER_JAM = 8
            assert pu._get_printer_status(8) == "卡纸"

    def test_status_paper_out(self):
        pu = PrinterUtils()
        with patch("app.utils.print_utils._PRINT_BACKEND_AVAILABLE", True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.PRINTER_STATUS_PAPER_OUT = 16
            assert pu._get_printer_status(16) == "缺纸"

    def test_status_toner_low(self):
        pu = PrinterUtils()
        with patch("app.utils.print_utils._PRINT_BACKEND_AVAILABLE", True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.PRINTER_STATUS_TONER_LOW = 262144
            assert pu._get_printer_status(262144) == "墨粉不足"

    def test_status_unknown_code_returns_ready(self):
        pu = PrinterUtils()
        with patch("app.utils.print_utils._PRINT_BACKEND_AVAILABLE", True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.PRINTER_STATUS_PAUSED = 1
            assert pu._get_printer_status(99999) == "就绪"


# ========================= monitor_print_job (backend available) =========


class TestMonitorPrintJobWithBackend:
    def test_monitor_print_job_queue_empty(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("app.utils.print_utils.time") as mock_time:
            mock_time.time.side_effect = [0, 0.5]  # start, then check
            mock_win32print.OpenPrinter.return_value = "handle"
            mock_win32print.EnumJobs.return_value = []  # empty queue
            result = pu.monitor_print_job("Printer1", timeout=10)
            assert result is True
            mock_win32print.ClosePrinter.assert_called_once_with("handle")

    def test_monitor_print_job_timeout(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("app.utils.print_utils.time") as mock_time:
            mock_time.time.side_effect = [0, 5, 61]  # start, loop, timeout
            mock_win32print.OpenPrinter.return_value = "handle"
            mock_win32print.EnumJobs.return_value = [{"JobID": 1}]
            mock_time.sleep = MagicMock()
            result = pu.monitor_print_job("Printer1", timeout=60)
            assert result is False

    def test_monitor_print_job_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("app.utils.print_utils.time") as mock_time:
            mock_win32print.OpenPrinter.side_effect = RuntimeError("open failed")
            # time.time() is called in while condition and then again after sleep
            # Provide enough values: start_time=0, then loop check > timeout
            mock_time.time.side_effect = [0, 100]  # start, then timeout
            mock_time.sleep = MagicMock()
            result = pu.monitor_print_job("Printer1", timeout=5)
            assert result is False

    def test_monitor_print_job_outer_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.time") as mock_time:
            mock_time.time.side_effect = RuntimeError("unexpected")
            result = pu.monitor_print_job("Printer1")
            assert result is False


# ========================= print_file (backend available, various exts) ==


class TestPrintFileWithBackend:
    def test_print_file_xlsx(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch.object(pu, "_print_excel", return_value={"success": True, "message": "ok"}):
            result = pu.print_file("/tmp/test.xlsx", "printer1")
            assert result["success"] is True

    def test_print_file_pdf(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch.object(pu, "_print_pdf", return_value={"success": True, "message": "ok"}):
            result = pu.print_file("/tmp/test.pdf", "printer1")
            assert result["success"] is True

    def test_print_file_other_extension(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch.object(pu, "_print_default", return_value={"success": True, "message": "ok"}):
            result = pu.print_file("/tmp/test.doc", "printer1")
            assert result["success"] is True

    def test_print_file_xls_extension(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch.object(pu, "_print_excel", return_value={"success": True}):
            result = pu.print_file("/tmp/test.xls", "printer1")
            assert result["success"] is True

    def test_print_file_use_default_printer_same(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch.object(pu, "_print_pdf", return_value={"success": True}):
            mock_win32print.GetDefaultPrinter.return_value = "printer1"
            result = pu.print_file("/tmp/test.pdf", "printer1", use_default_printer=True)
            assert result["success"] is True

    def test_print_file_use_default_printer_different(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("app.utils.print_utils.time") as mock_time, \
             patch.object(pu, "_print_pdf", return_value={"success": True}):
            mock_win32print.GetDefaultPrinter.side_effect = ["old_printer", "printer1", "old_printer"]
            mock_win32print.SetDefaultPrinter.return_value = None
            mock_time.sleep = MagicMock()
            result = pu.print_file("/tmp/test.pdf", "printer1", use_default_printer=True)
            assert result["success"] is True

    def test_print_file_use_default_printer_set_fails_retry(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("app.utils.print_utils.time") as mock_time, \
             patch.object(pu, "_print_pdf", return_value={"success": True}):
            # First check: default is different
            mock_win32print.GetDefaultPrinter.side_effect = [
                "old_printer",  # initial
                "old_printer",  # after first set (failed)
                "printer1",     # after second set (succeeded)
                "old_printer",  # restore
            ]
            mock_win32print.SetDefaultPrinter.return_value = None
            mock_time.sleep = MagicMock()
            result = pu.print_file("/tmp/test.pdf", "printer1", use_default_printer=True)
            assert result["success"] is True

    def test_print_file_use_default_printer_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch.object(pu, "_print_pdf", return_value={"success": True}):
            mock_win32print.GetDefaultPrinter.side_effect = RuntimeError("no default")
            result = pu.print_file("/tmp/test.pdf", "printer1", use_default_printer=True)
            assert result["success"] is True

    def test_print_file_restore_default_fails(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("app.utils.print_utils.time") as mock_time, \
             patch.object(pu, "_print_pdf", return_value={"success": True}):
            mock_win32print.GetDefaultPrinter.side_effect = [
                "old_printer", "printer1", RuntimeError("restore failed")
            ]
            mock_win32print.SetDefaultPrinter.return_value = None
            mock_time.sleep = MagicMock()
            result = pu.print_file("/tmp/test.pdf", "printer1", use_default_printer=True)
            assert result["success"] is True

    def test_print_file_outer_exception(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.exists", side_effect=RuntimeError("unexpected")):
            result = pu.print_file("/tmp/test.pdf", "printer1")
            assert result["success"] is False


# ========================= _print_excel ==================================


class TestPrintExcel:
    def test_print_excel_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu._print_excel("/tmp/test.xlsx", "printer1")
            assert result["success"] is False

    def test_print_excel_startfile_success(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.basename", return_value="test.xlsx"), \
             patch("os.startfile", create=True) as mock_startfile:
            mock_startfile.return_value = None
            result = pu._print_excel("/tmp/test.xlsx", "printer1")
            assert result["success"] is True
            assert "os.startfile" in result["message"]

    def test_print_excel_startfile_fails_shellexecute_success(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.basename", return_value="test.xlsx"), \
             patch("os.startfile", create=True, side_effect=OSError("not available")), \
             patch("app.utils.print_utils.win32api") as mock_win32api:
            mock_win32api.ShellExecute.return_value = 33  # > 32 means success
            result = pu._print_excel("/tmp/test.xlsx", "printer1")
            assert result["success"] is True

    def test_print_excel_all_methods_fail(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.path.basename", return_value="test.xlsx"), \
             patch("os.startfile", create=True, side_effect=OSError("not available")), \
             patch("app.utils.print_utils.win32api") as mock_win32api:
            mock_win32api.ShellExecute.return_value = 0  # failure
            # ShellExecute returns 0 → raises Exception("ShellExecute失败，错误代码: 0")
            # which is NOT in RECOVERABLE_ERRORS, so it propagates out immediately
            with pytest.raises(Exception, match="ShellExecute失败"):
                pu._print_excel("/tmp/test.xlsx", "printer1")

    def test_print_excel_outer_exception(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("os.startfile", create=True, side_effect=OSError("not available")), \
             patch("app.utils.print_utils.win32api") as mock_win32api:
            mock_win32api.ShellExecute.side_effect = RuntimeError("crash")
            # All methods fail → raises Exception
            with pytest.raises(Exception, match="所有打印方法都失败"):
                pu._print_excel("/tmp/test.xlsx", "printer1")


# ========================= _print_pdf ====================================


class TestPrintPdf:
    def test_print_pdf_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu._print_pdf("/tmp/test.pdf", "printer1")
            assert result["success"] is False

    def test_print_pdf_win32print_success(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("builtins.open", create=True) as mock_open, \
             patch("os.path.basename", return_value="test.pdf"):
            mock_win32print.OpenPrinter.return_value = "handle"
            mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"pdf_data")))
            mock_open.return_value.__exit__ = MagicMock(return_value=False)
            result = pu._print_pdf("/tmp/test.pdf", "printer1")
            assert result["success"] is True
            assert result["method"] == "win32print"

    def test_print_pdf_win32print_fails_adobe_not_found(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("os.path.basename", return_value="test.pdf"), \
             patch("os.path.exists", return_value=False):
            mock_win32print.OpenPrinter.side_effect = RuntimeError("open failed")
            # The function raises Exception("所有PDF打印方法都失败") which
            # is NOT in RECOVERABLE_ERRORS, so it propagates out
            with pytest.raises(Exception, match="所有PDF打印方法都失败"):
                pu._print_pdf("/tmp/test.pdf", "printer1")

    def test_print_pdf_outer_exception(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print, \
             patch("os.path.basename", return_value="test.pdf"), \
             patch("builtins.open", create=True, side_effect=FileNotFoundError("no file")), \
             patch("os.path.exists", return_value=False):
            mock_win32print.OpenPrinter.return_value = "handle"
            # FileNotFoundError is caught by inner RECOVERABLE_ERRORS, then Adobe not found,
            # then raises Exception("所有PDF打印方法都失败")
            with pytest.raises(Exception, match="所有PDF打印方法都失败"):
                pu._print_pdf("/tmp/test.pdf", "printer1")


# ========================= _print_default ================================


class TestPrintDefault:
    def test_print_default_unavailable(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=False):
            result = pu._print_default("/tmp/test.doc", "printer1")
            assert result["success"] is False

    def test_print_default_success(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32api") as mock_win32api, \
             patch("os.path.basename", return_value="test.doc"):
            mock_win32api.ShellExecute.return_value = 33
            result = pu._print_default("/tmp/test.doc", "printer1")
            assert result["success"] is True
            assert result["show_app"] is False

    def test_print_default_show_app(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32api") as mock_win32api, \
             patch("os.path.basename", return_value="test.doc"):
            mock_win32api.ShellExecute.return_value = 33
            result = pu._print_default("/tmp/test.doc", "printer1", show_app=True)
            assert result["success"] is True
            assert result["show_app"] is True

    def test_print_default_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32api") as mock_win32api:
            mock_win32api.ShellExecute.side_effect = RuntimeError("failed")
            result = pu._print_default("/tmp/test.doc", "printer1")
            assert result["success"] is False


# ========================= test_printer (backend available) ==============


class TestTestPrinterWithBackend:
    def test_test_printer_success(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.OpenPrinter.return_value = "handle"
            mock_win32print.GetPrinter.return_value = {"Status": 0}
            result = pu.test_printer("Printer1")
            assert result["success"] is True
            assert result["available"] is True
            mock_win32print.ClosePrinter.assert_called_once_with("handle")

    def test_test_printer_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.win32print") as mock_win32print:
            mock_win32print.OpenPrinter.side_effect = RuntimeError("no such printer")
            result = pu.test_printer("BadPrinter")
            assert result["success"] is False
            assert result["available"] is False


# ========================= _ensure_com_initialized edge cases ============


class TestEnsureComInitialized:
    def test_com_init_error(self):
        pu = PrinterUtils()
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch("app.utils.print_utils.pythoncom") as mock_com:
            mock_com.CoInitialize.side_effect = RuntimeError("COM error")
            pu._ensure_com_initialized()
            assert pu._com_initialized is False


# ========================= get_document_printer / get_label_printer keywords


class TestPrinterKeywordMatching:
    def test_document_printer_epson_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "Epson L3150", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_document_printer()
            assert result == "Epson L3150"

    def test_document_printer_canon_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "Canon PIXMA", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_document_printer()
            assert result == "Canon PIXMA"

    def test_label_printer_zebra_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "Zebra ZD420", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_label_printer()
            assert result == "Zebra ZD420"

    def test_label_printer_thermal_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "Thermal Printer X", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_label_printer()
            assert result == "Thermal Printer X"

    def test_label_printer_barcode_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "Barcode Printer", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_label_printer()
            assert result == "Barcode Printer"

    def test_document_printer_chinese_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "针式打印机", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_document_printer()
            assert result == "针式打印机"

    def test_label_printer_chinese_keyword(self):
        pu = PrinterUtils()
        printers = [
            {"name": "标签打印机", "status": "就绪", "is_default": False},
        ]
        with patch.object(pu, "_is_print_backend_available", return_value=True), \
             patch.object(pu, "get_available_printers", return_value=printers):
            result = pu.get_label_printer()
            assert result == "标签打印机"
