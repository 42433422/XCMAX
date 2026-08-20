"""Tests for app.utils.path_io.print_utils — coverage ramp."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from app.utils.path_io.print_utils import PrinterUtils

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
        with (
            patch("app.utils.path_io.print_utils._PRINT_BACKEND_AVAILABLE", True),
            patch("app.utils.path_io.print_utils.win32print") as mock_win32print,
        ):
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
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.pythoncom") as mock_com,
        ):
            pu._ensure_com_initialized()
            mock_com.CoInitialize.assert_called_once()
            assert pu._com_initialized is True

    def test_ensure_com_initialized_already_done(self):
        pu = PrinterUtils()
        pu._com_initialized = True
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.pythoncom") as mock_com,
        ):
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
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("os.path.exists", return_value=True),
        ):
            result = pu.print_file("/tmp/test.pdf", printer_name=None)
            assert result["success"] is False
            assert "未指定打印机名称" in result["message"]

    def test_print_file_not_exists(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("os.path.exists", return_value=False),
        ):
            result = pu.print_file("/tmp/nonexistent.pdf", "printer1")
            assert result["success"] is False
            assert "文件不存在" in result["message"]

    def test_get_document_printer_no_printers(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", return_value=[]),
        ):
            result = pu.get_document_printer()
            assert result is None

    def test_get_label_printer_no_printers(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", return_value=[]),
        ):
            result = pu.get_label_printer()
            assert result is None

    def test_get_document_printer_with_keyword_match(self):
        pu = PrinterUtils()
        printers = [
            {"name": "SomeOtherPrinter", "status": "就绪", "is_default": False},
            {"name": "HP LaserJet", "status": "就绪", "is_default": True},
        ]
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", return_value=printers),
        ):
            result = pu.get_document_printer()
            assert result == "HP LaserJet"

    def test_get_label_printer_with_keyword_match(self):
        pu = PrinterUtils()
        printers = [
            {"name": "TSC Printer", "status": "就绪", "is_default": False},
            {"name": "HP LaserJet", "status": "就绪", "is_default": True},
        ]
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", return_value=printers),
        ):
            result = pu.get_label_printer()
            assert result == "TSC Printer"

    def test_get_document_printer_fallback_first(self):
        pu = PrinterUtils()
        printers = [
            {"name": "RandomPrinter", "status": "就绪", "is_default": True},
        ]
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", return_value=printers),
        ):
            result = pu.get_document_printer()
            assert result == "RandomPrinter"

    def test_get_label_printer_without_label_keywords_returns_none(self):
        pu = PrinterUtils()
        printers = [
            {"name": "RandomPrinter1", "status": "就绪", "is_default": True},
            {"name": "RandomPrinter2", "status": "就绪", "is_default": False},
        ]
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", return_value=printers),
        ):
            result = pu.get_label_printer()
            assert result is None

    def test_get_default_printer_error(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.win32print") as mock_win32print,
        ):
            mock_win32print.GetDefaultPrinter.side_effect = RuntimeError("no printer")
            result = pu.get_default_printer()
            assert result is None

    def test_get_document_printer_error(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", side_effect=RuntimeError("err")),
        ):
            result = pu.get_document_printer()
            assert result is None

    def test_get_label_printer_error(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "get_available_printers", side_effect=RuntimeError("err")),
        ):
            result = pu.get_label_printer()
            assert result is None


class TestMacosCupsPrinterUtils:
    def test_cups_backend_requires_both_commands(self):
        with (
            patch("app.utils.path_io.print_utils.sys.platform", "darwin"),
            patch("app.utils.path_io.print_utils.os.path.isfile", return_value=True),
            patch("app.utils.path_io.print_utils.os.access", return_value=True),
            patch("app.utils.path_io.print_utils.win32print", None),
            patch("app.utils.path_io.print_utils.win32api", None),
        ):
            assert PrinterUtils._is_cups_backend_available() is True

    def test_discovers_cups_printer_and_default(self):
        pu = PrinterUtils()
        printer_result = MagicMock(
            returncode=0,
            stdout=(
                "printer Canon_TS3700_series is idle. enabled since Wed Jul 15 10:16:30 2026\n"
                "printer Zebra_Label is printing Zebra_Label-8. enabled since Wed Jul 15\n"
            ),
            stderr="",
        )
        default_result = MagicMock(
            returncode=0,
            stdout="system default destination: Canon_TS3700_series\n",
            stderr="",
        )
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.win32print", None),
            patch.object(pu, "_run_cups", side_effect=[printer_result, default_result]),
        ):
            printers = pu.get_available_printers()

        assert printers == [
            {
                "name": "Canon_TS3700_series",
                "status": "就绪",
                "is_default": True,
            },
            {
                "name": "Zebra_Label",
                "status": "打印中",
                "is_default": False,
            },
        ]

    def test_discovers_localized_macos_cups_output(self):
        pu = PrinterUtils()
        printer_result = MagicMock(
            returncode=0,
            stdout="打印机Canon_TS3700_series闲置，启用时间始于Wed Jul 15 10:16:30 2026\n",
            stderr="",
        )
        default_result = MagicMock(
            returncode=0,
            stdout="系统默认目的位置：Canon_TS3700_series\n",
            stderr="",
        )
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.win32print", None),
            patch.object(pu, "_run_cups", side_effect=[printer_result, default_result]),
        ):
            printers = pu.get_available_printers()

        assert printers == [
            {
                "name": "Canon_TS3700_series",
                "status": "就绪",
                "is_default": True,
            }
        ]

    def test_gets_cups_default_printer(self):
        pu = PrinterUtils()
        result = MagicMock(
            returncode=0,
            stdout="system default destination: Canon_TS3700_series\n",
            stderr="",
        )
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.win32print", None),
            patch.object(pu, "_run_cups", return_value=result),
        ):
            assert pu.get_default_printer() == "Canon_TS3700_series"

    def test_prints_pdf_through_lp(self):
        pu = PrinterUtils()
        result = MagicMock(
            returncode=0,
            stdout="request id is Canon_TS3700_series-6 (1 file(s))\n",
            stderr="",
        )
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.win32print", None),
            patch("app.utils.path_io.print_utils.win32api", None),
            patch("app.utils.path_io.print_utils.os.path.exists", return_value=True),
            patch.object(
                pu,
                "_resolve_cups_printer_name",
                return_value="Canon_TS3700_series",
            ),
            patch.object(pu, "_resolve_allowed_print_path", return_value="/tmp/test.pdf"),
            patch("builtins.open", mock_open(read_data=b"pdf")),
            patch.object(pu, "_run_cups", return_value=result) as run_cups,
        ):
            output = pu.print_file("/tmp/test.pdf", "Canon_TS3700_series")

        assert output["success"] is True
        assert output["method"] == "cups_lp"
        assert run_cups.call_args.args == (
            "lp",
            ("-d", "Canon_TS3700_series"),
        )
        assert run_cups.call_args.kwargs["input_stream"] is not None

    def test_cups_rejects_untrusted_printer_name_without_running_command(self):
        pu = PrinterUtils()
        with patch.object(pu, "_run_cups") as run_cups:
            output = pu._print_cups("/tmp/test.pdf", "--option-injection")

        assert output["success"] is False
        assert "名称不安全" in output["message"]
        run_cups.assert_not_called()

    def test_cups_exception_is_not_exposed_to_api_caller(self):
        pu = PrinterUtils()
        with (
            patch.object(
                pu,
                "_resolve_cups_printer_name",
                return_value="Canon_TS3700_series",
            ),
            patch.object(
                pu,
                "_resolve_allowed_print_path",
                return_value="/private/sensitive/test.pdf",
            ),
            patch("builtins.open", mock_open(read_data=b"pdf")),
            patch.object(
                pu,
                "_run_cups",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["/usr/bin/lp", "sensitive-value"],
                    timeout=30,
                ),
            ),
        ):
            output = pu._print_cups("/private/sensitive/test.pdf", "Canon_TS3700_series")

        assert output["success"] is False
        assert output["message"] == "打印失败：macOS 打印服务暂不可用"
        assert "sensitive" not in output["message"]

    def test_cups_rejects_file_outside_allowed_roots(self):
        pu = PrinterUtils()
        with (
            patch.object(
                pu,
                "_resolve_cups_printer_name",
                return_value="Canon_TS3700_series",
            ),
            patch.object(pu, "_resolve_allowed_print_path", return_value=None),
            patch("builtins.open", mock_open()) as open_file,
            patch.object(pu, "_run_cups") as run_cups,
        ):
            output = pu._print_cups("/etc/passwd", "Canon_TS3700_series")

        assert output["success"] is False
        assert "允许的打印目录" in output["message"]
        open_file.assert_not_called()
        run_cups.assert_not_called()

    def test_print_file_rejects_file_outside_allowed_roots(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch.object(pu, "_resolve_allowed_print_path", return_value=None),
            patch.object(pu, "_print_pdf") as print_pdf,
        ):
            output = pu.print_file("/etc/passwd", "printer1")

        assert output["success"] is False
        assert "允许的打印目录" in output["message"]
        print_pdf.assert_not_called()

    def test_allowed_print_path_blocks_symlink_escape(self, tmp_path):
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        secret = outside / "secret.pdf"
        secret.write_bytes(b"secret")
        link = allowed / "linked.pdf"
        link.symlink_to(secret)

        with patch.object(
            PrinterUtils,
            "_allowed_print_roots",
            return_value=(str(allowed.resolve()),),
        ):
            assert PrinterUtils._resolve_allowed_print_path(str(link)) is None

    def test_allowed_print_path_accepts_direct_child(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        document = allowed / "document.pdf"
        document.write_bytes(b"pdf")

        with patch.object(
            PrinterUtils,
            "_allowed_print_roots",
            return_value=(str(allowed.resolve()),),
        ):
            assert PrinterUtils._resolve_allowed_print_path(str(document)) == str(
                document.resolve()
            )

    def test_cups_printer_probe_reports_missing_printer(self):
        pu = PrinterUtils()
        with (
            patch.object(pu, "_is_print_backend_available", return_value=True),
            patch("app.utils.path_io.print_utils.win32print", None),
            patch.object(
                pu,
                "get_available_printers",
                return_value=[
                    {
                        "name": "Canon_TS3700_series",
                        "status": "就绪",
                        "is_default": True,
                    }
                ],
            ),
        ):
            result = pu.test_printer("Missing")

        assert result["success"] is False
        assert result["available"] is False
