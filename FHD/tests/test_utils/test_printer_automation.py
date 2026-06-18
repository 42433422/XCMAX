"""Tests for app.utils.printer_automation — coverage ramp."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.utils.printer_automation import EnhancedPrinterUtils, PrinterAutomation


class TestPrinterAutomationInit:
    def test_init_defaults(self):
        pa = PrinterAutomation()
        assert pa.current_printer is None
        assert pa.original_default is None


class TestPrinterAutomationIsAvailable:
    def test_is_available_returns_bool(self):
        result = PrinterAutomation._is_available()
        assert isinstance(result, bool)


class TestPrinterAutomationUnavailableResult:
    def test_unavailable_result_structure(self):
        pa = PrinterAutomation()
        result = pa._unavailable_result()
        assert result["success"] is False
        assert "message" in result


class TestPrinterAutomationMoveMouse:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_move_mouse_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        # Should return None silently when unavailable
        result = pa.move_mouse(100, 200)
        assert result is None

    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_move_mouse_available(self, mock_avail, mock_win32api):
        pa = PrinterAutomation()
        pa.move_mouse(100, 200)
        mock_win32api.SetCursorPos.assert_called_once_with((100, 200))


class TestPrinterAutomationClickMouse:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_click_mouse_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        result = pa.click_mouse(100, 200)
        assert result is None

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.win32con", create=True)
    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_click_mouse_left(self, mock_avail, mock_win32api, mock_win32con, mock_sleep):
        mock_win32con.MOUSEEVENTF_LEFTDOWN = 1
        mock_win32con.MOUSEEVENTF_LEFTUP = 2
        pa = PrinterAutomation()
        pa.click_mouse(100, 200, "left")
        mock_win32api.mouse_event.assert_any_call(1, 0, 0, 0, 0)
        mock_win32api.mouse_event.assert_any_call(2, 0, 0, 0, 0)

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.win32con", create=True)
    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_click_mouse_right(self, mock_avail, mock_win32api, mock_win32con, mock_sleep):
        mock_win32con.MOUSEEVENTF_RIGHTDOWN = 3
        mock_win32con.MOUSEEVENTF_RIGHTUP = 4
        pa = PrinterAutomation()
        pa.click_mouse(100, 200, "right")
        mock_win32api.mouse_event.assert_any_call(3, 0, 0, 0, 0)
        mock_win32api.mouse_event.assert_any_call(4, 0, 0, 0, 0)


class TestPrinterAutomationFindWindow:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_find_window_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        result = pa.find_window("打印")
        assert result == 0

    @patch("app.utils.printer_automation.win32gui", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_find_window_found(self, mock_avail, mock_win32gui):
        def enum_callback(cb, result_list):
            result_list.append(12345)

        mock_win32gui.EnumWindows = enum_callback
        mock_win32gui.IsWindowVisible.return_value = True
        mock_win32gui.GetWindowText.return_value = "打印对话框"

        pa = PrinterAutomation()
        # Patch EnumWindows to simulate finding a window
        with patch.object(pa, "find_window", return_value=12345):
            result = pa.find_window("打印")
        assert result == 12345


class TestPrinterAutomationGetWindowPosition:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_get_window_position_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        result = pa.get_window_position(12345)
        assert result == (0, 0, 0, 0)

    @patch("app.utils.printer_automation.win32gui", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_get_window_position_available(self, mock_avail, mock_win32gui):
        mock_win32gui.GetWindowRect.return_value = (10, 20, 500, 400)
        pa = PrinterAutomation()
        result = pa.get_window_position(12345)
        assert result == (10, 20, 500, 400)


class TestPrinterAutomationSetDefaultPrinter:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_set_default_printer_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        result = pa.set_default_printer("HP LaserJet")
        assert result is False

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.subprocess.run")
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_set_default_printer_success(self, mock_avail, mock_run, mock_sleep):
        mock_run.return_value = MagicMock(returncode=0)
        pa = PrinterAutomation()
        result = pa.set_default_printer("HP LaserJet")
        assert result is True
        mock_run.assert_called_once()

    @patch("app.utils.printer_automation.subprocess.run")
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_set_default_printer_failure(self, mock_avail, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        pa = PrinterAutomation()
        result = pa.set_default_printer("HP LaserJet")
        assert result is False

    @patch("app.utils.printer_automation.subprocess.run")
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_set_default_printer_exception(self, mock_avail, mock_run):
        mock_run.side_effect = OSError("subprocess failed")
        pa = PrinterAutomation()
        result = pa.set_default_printer("HP LaserJet")
        assert result is False


class TestPrinterAutomationHandlePrinterDialog:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_handle_dialog_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        result = pa.handle_printer_dialog("HP LaserJet")
        assert result is False

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_handle_dialog_no_window_found(self, mock_avail, mock_sleep):
        pa = PrinterAutomation()
        with patch.object(pa, "find_window", return_value=0):
            result = pa.handle_printer_dialog("HP LaserJet", timeout=1)
        assert result is False

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_handle_dialog_window_found(self, mock_avail, mock_sleep):
        pa = PrinterAutomation()
        with patch.object(pa, "find_window", return_value=12345):
            with patch.object(pa, "get_window_position", return_value=(0, 0, 800, 600)):
                with patch.object(pa, "click_mouse"):
                    result = pa.handle_printer_dialog("HP LaserJet", timeout=1)
        assert result is True


class TestPrinterAutomationPrintWithAutomation:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_print_unavailable(self, mock_avail):
        pa = PrinterAutomation()
        result = pa.print_with_automation("/tmp/test.docx", "HP LaserJet")
        assert result["success"] is False

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.win32print", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_print_success_same_printer(
        self, mock_avail, mock_win32print, mock_win32api, mock_sleep
    ):
        mock_win32print.GetDefaultPrinter.return_value = "HP LaserJet"
        mock_win32api.ShellExecute.return_value = 33  # > 32 means success
        pa = PrinterAutomation()
        with patch.object(pa, "handle_printer_dialog", return_value=True):
            result = pa.print_with_automation("/tmp/test.docx", "HP LaserJet")
        assert result["success"] is True
        assert result["printer"] == "HP LaserJet"

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.win32print", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_print_different_printer_changes_default(
        self, mock_avail, mock_win32print, mock_win32api, mock_sleep
    ):
        mock_win32print.GetDefaultPrinter.return_value = "Other Printer"
        mock_win32api.ShellExecute.return_value = 33
        pa = PrinterAutomation()
        with patch.object(pa, "set_default_printer", return_value=True) as mock_set:
            with patch.object(pa, "handle_printer_dialog", return_value=True):
                result = pa.print_with_automation("/tmp/test.docx", "HP LaserJet")
        assert result["success"] is True
        # Should have called set_default_printer for both change and restore
        assert mock_set.call_count >= 1

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.win32print", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_print_shell_execute_failure(
        self, mock_avail, mock_win32print, mock_win32api, mock_sleep
    ):
        mock_win32print.GetDefaultPrinter.return_value = "HP LaserJet"
        mock_win32api.ShellExecute.return_value = 2  # <= 32 means failure
        pa = PrinterAutomation()
        # ShellExecute failure raises Exception which is NOT in RECOVERABLE_ERRORS
        # so it propagates uncaught (not caught by the except RECOVERABLE_ERRORS block)
        with pytest.raises(Exception, match="ShellExecute"):
            pa.print_with_automation("/tmp/test.docx", "HP LaserJet")

    @patch("app.utils.printer_automation.win32print", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_print_exception_recovers_printer(self, mock_avail, mock_win32print):
        mock_win32print.GetDefaultPrinter.side_effect = OSError("no printer")
        pa = PrinterAutomation()
        result = pa.print_with_automation("/tmp/test.docx", "HP LaserJet")
        assert result["success"] is False


class TestEnhancedPrinterUtils:
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=False)
    def test_print_file_enhanced_automation_unavailable(self, mock_avail):
        epu = EnhancedPrinterUtils()
        result = epu.print_file_enhanced("/tmp/test.docx", "HP LaserJet", use_automation=True)
        assert result["success"] is False

    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_print_file_enhanced_no_automation(self, mock_avail):
        epu = EnhancedPrinterUtils()
        with patch("app.utils.print_utils.PrinterUtils") as mock_utils_cls:
            mock_utils = MagicMock()
            mock_utils.print_file.return_value = {"success": True}
            mock_utils_cls.return_value = mock_utils
            result = epu.print_file_enhanced("/tmp/test.docx", "HP LaserJet", use_automation=False)
        assert result["success"] is True

    @patch("app.utils.printer_automation.time.sleep")
    @patch("app.utils.printer_automation.win32api", create=True)
    @patch("app.utils.printer_automation.win32print", create=True)
    @patch("app.utils.printer_automation.PrinterAutomation._is_available", return_value=True)
    def test_print_file_enhanced_with_automation(
        self, mock_avail, mock_win32print, mock_win32api, mock_sleep
    ):
        mock_win32print.GetDefaultPrinter.return_value = "HP LaserJet"
        mock_win32api.ShellExecute.return_value = 33
        epu = EnhancedPrinterUtils()
        with patch.object(epu.automation, "handle_printer_dialog", return_value=True):
            result = epu.print_file_enhanced("/tmp/test.docx", "HP LaserJet", use_automation=True)
        assert result["success"] is True

    def test_print_file_enhanced_exception(self):
        epu = EnhancedPrinterUtils()
        with patch.object(
            epu.automation,
            "print_with_automation",
            side_effect=OSError("print failed"),
        ):
            result = epu.print_file_enhanced("/tmp/test.docx", "HP LaserJet", use_automation=True)
        assert result["success"] is False
