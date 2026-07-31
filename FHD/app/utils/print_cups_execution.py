import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO

from app.utils.operational_errors import RECOVERABLE_ERRORS

try:
    import pythoncom
    import win32api
    import win32print

    _PRINT_BACKEND_AVAILABLE = True
    _PRINT_BACKEND_ERROR = ""
except ImportError as _print_import_error:
    pythoncom = None
    win32api = None
    win32print = None
    _PRINT_BACKEND_AVAILABLE = False
    _PRINT_BACKEND_ERROR = str(_print_import_error)

logging.basicConfig(level=logging.INFO, encoding="utf-8")
logger = logging.getLogger(__name__)
_CUPS_ERRORS = RECOVERABLE_ERRORS + (subprocess.SubprocessError,)
_CUPS_LP = "/usr/bin/lp"
_CUPS_LPSTAT = "/usr/bin/lpstat"
_CUPS_LPOPTIONS = "/usr/bin/lpoptions"
_CUPS_IPPTOOL = "/usr/bin/ipptool"
_CUPS_PRINTER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")
_CUPS_JOB_ID_RE = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9_.-]{0,126}-\d+)\b")
_CUPS_JOB_STATE_RE = re.compile(r"job-state\s+\(enum\)\s+=\s+([^\s]+)", re.IGNORECASE)
_CUPS_JOB_REASONS_RE = re.compile(
    r"job-state-reasons\s+\([^)]*keyword[^)]*\)\s+=\s+(.+)", re.IGNORECASE
)
_CUPS_STATUS_CODE_RE = re.compile(r"status-code\s+=\s+([^\s]+)", re.IGNORECASE)
_CUPS_MONITOR_TIMEOUT_SECONDS = 12.0
_CUPS_MONITOR_INTERVAL_SECONDS = 1.0
_MAC_OSASCRIPT = "/usr/bin/osascript"
_MAC_NUMBERS = "/Applications/Numbers.app"
_NUMBERS_PDF_EXPORT_SCRIPT = """
on run argv
    set sourceFile to POSIX file (item 1 of argv)
    set outputFile to POSIX file (item 2 of argv)
    tell application "Numbers" to launch
    delay 1
    tell application "Numbers"
        set sourceDocument to open sourceFile
        export sourceDocument to outputFile as PDF
        close sourceDocument saving no
    end tell
end run
"""

from app.utils.mixin_module_sync import sync_mixin_methods


class PrintCupsExecutionMixin:
    @staticmethod
    def _allowed_print_roots() -> tuple[str, ...]:
        from app.utils.path_utils import get_app_data_dir

        app_data = os.path.realpath(get_app_data_dir())
        roots = {
            app_data,
            os.path.join(app_data, "shipment_outputs"),
            os.path.realpath(tempfile.gettempdir()),
        }
        configured = os.environ.get("XCAGI_PRINT_ALLOWED_ROOTS", "")
        for value in configured.split(os.pathsep):
            value = value.strip()
            if value:
                roots.add(os.path.realpath(value))
        return tuple(sorted(roots))

    @classmethod
    def _resolve_allowed_print_path(cls, file_path: str) -> str | None:
        requested = os.path.realpath(os.path.abspath(file_path))
        for root in cls._allowed_print_roots():
            normalized_root = os.path.realpath(root)
            try:
                with os.scandir(normalized_root) as entries:
                    for entry in entries:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        candidate = os.path.realpath(entry.path)
                        if os.path.normcase(candidate) == os.path.normcase(requested):
                            return candidate
            except OSError:
                continue
        return None

    def _print_cups(self, file_path: str, printer_name: str) -> dict:
        validated_printer = self._resolve_cups_printer_name(printer_name)
        if validated_printer is None:
            return {
                "success": False,
                "message": "打印失败：打印机不存在或名称不安全",
                "printer": printer_name,
            }
        validated_file = self._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return {
                "success": False,
                "message": "打印失败：文件不在允许的打印目录中",
                "printer": validated_printer,
            }
        try:
            jobs_before_submission = self._cups_job_ids(validated_printer)
            with open(validated_file, "rb") as source:
                result = self._run_cups(
                    "lp",
                    ("-d", validated_printer),
                    timeout=30,
                    input_stream=source,
                )
            if result.returncode != 0:
                logger.warning(
                    "CUPS rejected print job for %s: %s",
                    validated_printer,
                    result.stderr.strip() or result.stdout.strip() or "lp command failed",
                )
                return {
                    "success": False,
                    "message": "打印失败：macOS 打印服务拒绝了任务",
                    "printer": validated_printer,
                }
            job_id = self._cups_submission_job_id(
                "\n".join((str(result.stdout or ""), str(result.stderr or "")))
            )
            if not job_id:
                job_id = self._detect_submitted_cups_job_id(
                    validated_printer,
                    before=jobs_before_submission,
                )
            if not job_id:
                # CUPS accepted the document but did not return an id we can
                # inspect.  Never turn that into a completed/printed receipt.
                return {
                    "success": True,
                    "message": "打印任务已提交到 macOS CUPS，正在等待设备完成",
                    "file": os.path.basename(validated_file),
                    "printer": validated_printer,
                    "method": "cups_lp",
                    "print_completed": False,
                    "print_state": "queued",
                }

            monitor = self._monitor_cups_job(validated_printer, job_id)
            state = str(monitor.get("state") or "pending")
            if state == "completed":
                return {
                    "success": True,
                    "message": "打印任务已由 macOS CUPS 确认完成",
                    "file": os.path.basename(validated_file),
                    "printer": validated_printer,
                    "method": "cups_lp",
                    "job_id": job_id,
                    "print_completed": True,
                    "print_state": "completed",
                }
            if state == "aborted":
                reason = str(monitor.get("reason") or "").strip()
                return {
                    "success": False,
                    "message": "打印失败：macOS 打印任务已中止"
                    + (f"（{reason}）" if reason else ""),
                    "printer": validated_printer,
                    "method": "cups_lp",
                    "job_id": job_id,
                    "print_completed": False,
                    "print_state": "aborted",
                    "error_code": "CUPS_JOB_ABORTED",
                }
            return {
                "success": True,
                "message": "打印任务已提交到 macOS CUPS，正在等待设备完成",
                "file": os.path.basename(validated_file),
                "printer": validated_printer,
                "method": "cups_lp",
                "job_id": job_id,
                "print_completed": False,
                "print_state": "queued",
            }
        except _CUPS_ERRORS as exc:
            logger.error("CUPS print failed: %s", exc)
            return {
                "success": False,
                "message": "打印失败：macOS 打印服务暂不可用",
                "printer": validated_printer,
            }

    def _convert_excel_to_pdf_macos(self, file_path: str) -> tuple[str | None, str]:
        validated_file = self._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return None, "发货单文件不在允许的打印目录中"
        if not (
            os.path.isfile(_MAC_OSASCRIPT)
            and os.access(_MAC_OSASCRIPT, os.X_OK)
            and os.path.isdir(_MAC_NUMBERS)
        ):
            return None, "未安装 Apple Numbers，无法将 Excel 发货单转换为可打印格式"

        file_descriptor, pdf_path = tempfile.mkstemp(
            prefix="xcagi-shipment-print-",
            suffix=".pdf",
            dir=tempfile.gettempdir(),
        )
        os.close(file_descriptor)
        os.unlink(pdf_path)
        try:
            result = subprocess.run(
                [
                    _MAC_OSASCRIPT,
                    "-e",
                    _NUMBERS_PDF_EXPORT_SCRIPT,
                    validated_file,
                    pdf_path,
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0 or not os.path.isfile(pdf_path):
                detail = result.stderr.strip() or result.stdout.strip()
                logger.warning("Numbers PDF export failed: %s", detail or "unknown error")
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                return None, "Numbers 转换发货单失败，请检查自动化权限后重试"
            return pdf_path, ""
        except _CUPS_ERRORS as exc:
            logger.warning("Numbers PDF export unavailable: %s", exc)
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
            return None, "Numbers 转换发货单失败，请检查自动化权限后重试"

    def _print_excel_macos(self, file_path: str, printer_name: str) -> dict:
        pdf_path, error = self._convert_excel_to_pdf_macos(file_path)
        if pdf_path is None:
            return {
                "success": False,
                "message": f"打印失败：{error}",
                "printer": printer_name,
            }
        try:
            result = self._print_cups(pdf_path, printer_name)
            if result.get("success"):
                result.update(
                    {
                        "file": os.path.basename(file_path),
                        "method": "numbers_pdf_cups",
                    }
                )
            return result
        finally:
            try:
                os.unlink(pdf_path)
            except OSError:
                logger.warning("Unable to remove temporary print PDF: %s", pdf_path)

    def _monitor_cups_print_job(self, printer_name: str, timeout: int) -> bool:
        validated_printer = self._resolve_cups_printer_name(printer_name)
        if validated_printer is None:
            return False
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = self._run_cups("lpstat", ("-o", validated_printer))
                if result.returncode == 0 and not result.stdout.strip():
                    return True
            except _CUPS_ERRORS as exc:
                logger.warning("CUPS queue query failed: %s", exc)
                return False
            threading.Event().wait(1)
        return False

    def _ensure_com_initialized(self):
        if pythoncom is None:
            return
        if not self._com_initialized:
            try:
                pythoncom.CoInitialize()
                self._com_initialized = True
            except RECOVERABLE_ERRORS as e:
                logger.warning("COM初始化警告: %s", e)


sync_mixin_methods(
    PrintCupsExecutionMixin,
    target=globals(),
    source_module="app.utils.print_utils",
    method_names=(
        "_allowed_print_roots",
        "_resolve_allowed_print_path",
        "_print_cups",
        "_convert_excel_to_pdf_macos",
        "_print_excel_macos",
        "_monitor_cups_print_job",
        "_ensure_com_initialized",
    ),
)
