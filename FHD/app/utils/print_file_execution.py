import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
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


class PrintFileExecutionMixin:
    def print_file(
        self, file_path: str, printer_name: str | None = None, use_default_printer: bool = False
    ) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        try:
            if not os.path.exists(file_path):
                return {"success": False, "message": f"文件不存在: {file_path}"}

            _, ext = os.path.splitext(file_path)
            ext = ext.lower()

            if not printer_name:
                logger.error("未指定打印机名称，拒绝打印")
                return {"success": False, "message": "未指定打印机名称，无法打印"}

            logger.info("准备打印文件: %s", file_path)
            logger.info("使用打印机: %s", printer_name)

            original_default_printer = None

            if use_default_printer and win32print is not None:
                try:
                    original_default_printer = win32print.GetDefaultPrinter()
                    logger.info("当前默认打印机: %s", original_default_printer)
                    logger.info("目标打印机: %s", printer_name)

                    if original_default_printer != printer_name:
                        logger.info("正在修改默认打印机...")
                        try:
                            win32print.SetDefaultPrinter(printer_name)
                            logger.info("SetDefaultPrinter 调用完成")
                        except RECOVERABLE_ERRORS as e:
                            logger.error("SetDefaultPrinter 调用失败: %s", e)
                            import traceback

                            logger.error(traceback.format_exc())

                        threading.Event().wait(0.5)
                        try:
                            new_default = win32print.GetDefaultPrinter()
                            logger.info("验证 - 当前默认打印机: %s", new_default)
                        except RECOVERABLE_ERRORS as e:
                            logger.error("GetDefaultPrinter 调用失败: %s", e)
                            new_default = original_default_printer

                        if new_default == printer_name:
                            logger.info("默认打印机修改成功: %s", new_default)
                        else:
                            logger.error(
                                "默认打印机修改失败！当前: %s, 目标: %s", new_default, printer_name
                            )
                            try:
                                win32print.SetDefaultPrinter(printer_name)
                                threading.Event().wait(0.5)
                                new_default = win32print.GetDefaultPrinter()
                                logger.info("第二次修改后默认打印机: %s", new_default)
                            except RECOVERABLE_ERRORS as e:
                                logger.error("第二次修改失败: %s", e)
                    else:
                        logger.info("当前默认打印机已经是目标打印机，无需修改")
                except RECOVERABLE_ERRORS as e:
                    logger.error("修改默认打印机失败: %s", e)
                    import traceback

                    logger.error(traceback.format_exc())
            else:
                logger.info("已明确指定打印机，不使用系统默认打印机")

            print_result = None
            try:
                if ext in [".xlsx", ".xls"]:
                    print_result = self._print_excel(file_path, printer_name)
                elif ext == ".pdf":
                    print_result = self._print_pdf(file_path, printer_name)
                else:
                    print_result = self._print_default(file_path, printer_name)

                if print_result.get("success", False):
                    logger.info("打印命令已发送，继续执行后续操作")
            finally:
                if use_default_printer and original_default_printer and win32print is not None:
                    try:
                        if original_default_printer != printer_name:
                            logger.info("恢复默认打印机为: %s", original_default_printer)
                            win32print.SetDefaultPrinter(original_default_printer)
                            logger.info("默认打印机恢复成功")
                    except RECOVERABLE_ERRORS as e:
                        logger.warning("恢复默认打印机失败: %s", e)

            return print_result

        except RECOVERABLE_ERRORS as e:
            logger.error("打印文件失败: %s", e)
            return {"success": False, "message": f"打印失败: {str(e)}"}

    def _print_excel(self, file_path: str, printer_name: str) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32api is None and not hasattr(os, "startfile"):
            return self._print_excel_macos(file_path, printer_name)
        try:
            logger.info("开始打印Excel文件: %s", file_path)
            logger.info("使用打印机: %s", printer_name)

            try:
                logger.info("方法1: 使用os.startfile打印")
                os.startfile(file_path, "print")
                logger.info("os.startfile打印成功: %s", file_path)
                return {
                    "success": True,
                    "message": "打印任务已发送（os.startfile）",
                    "file": os.path.basename(file_path),
                    "printer": printer_name,
                }
            except RECOVERABLE_ERRORS as e1:
                logger.warning("方法1失败: %s", e1)

                try:
                    logger.info("方法2: 使用ShellExecute print")
                    result = win32api.ShellExecute(0, "print", file_path, None, ".", 1)

                    if result > 32:
                        logger.info("ShellExecute打印成功: %s", file_path)
                        return {
                            "success": True,
                            "message": "打印任务已发送到打印机",
                            "file": os.path.basename(file_path),
                            "printer": printer_name,
                        }
                    else:
                        raise Exception(f"ShellExecute失败，错误代码: {result}")

                except RECOVERABLE_ERRORS as e2:
                    logger.warning("方法2失败: %s", e2)

                    try:
                        logger.info("方法3: 打开文件让用户手动打印")
                        os.startfile(file_path)
                        logger.info("已打开文件: %s", file_path)
                        return {
                            "success": True,
                            "message": "文件已打开，请手动打印",
                            "file": os.path.basename(file_path),
                            "printer": printer_name,
                            "manual": True,
                        }
                    except RECOVERABLE_ERRORS as e3:
                        logger.error("方法3也失败: %s", e3)
                        raise Exception(f"所有打印方法都失败: {e1}; {e2}; {e3}")

        except RECOVERABLE_ERRORS as e:
            logger.error("打印Excel文件失败: %s", e)
            return {"success": False, "message": f"打印失败: {str(e)}"}

    def _print_pdf(self, file_path: str, printer_name: str) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32print is None:
            return self._print_cups(file_path, printer_name)
        try:
            logger.info("尝试使用win32print直接打印PDF到 %s", printer_name)

            try:
                hprinter = win32print.OpenPrinter(printer_name)

                try:
                    with open(file_path, "rb") as f:
                        file_data = f.read()

                    win32print.StartDocPrinter(hprinter, 1, ("PDF Job", None, "RAW"))
                    win32print.StartPagePrinter(hprinter)
                    win32print.WritePrinter(hprinter, file_data)
                    win32print.EndPagePrinter(hprinter)
                    win32print.EndDocPrinter(hprinter)

                    logger.info("PDF文件已通过win32print发送到打印机: %s", file_path)
                    return {
                        "success": True,
                        "message": "PDF文件已发送到打印机",
                        "file": os.path.basename(file_path),
                        "printer": printer_name,
                        "method": "win32print",
                    }
                finally:
                    win32print.ClosePrinter(hprinter)

            except RECOVERABLE_ERRORS as e:
                logger.warning("win32print打印失败: %s", e)

            logger.info("尝试使用subprocess调用外部程序")
            try:
                import subprocess

                adobe_paths = [
                    r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                    r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
                ]

                for adobe_path in adobe_paths:
                    if os.path.exists(adobe_path):
                        logger.info("使用Adobe Reader: %s", adobe_path)

                        subprocess.run(
                            [adobe_path, "/t", file_path, printer_name],
                            check=True,
                            timeout=30,
                            capture_output=True,
                        )

                        logger.info("PDF文件已通过Adobe Reader发送到打印机")
                        return {
                            "success": True,
                            "message": "PDF文件已通过Adobe Reader发送到打印机",
                            "file": os.path.basename(file_path),
                            "printer": printer_name,
                            "method": "adobe_cli",
                        }

                logger.warning("未找到Adobe Reader")

            except RECOVERABLE_ERRORS as e:
                logger.warning("subprocess方法失败: %s", e)

            raise Exception("所有PDF打印方法都失败")

        except RECOVERABLE_ERRORS as e:
            logger.error("打印PDF文件失败: %s", e)
            return {"success": False, "message": f"打印PDF失败: {str(e)}"}

    def _print_default(self, file_path: str, printer_name: str, show_app: bool = False) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32api is None:
            return self._print_cups(file_path, printer_name)
        try:
            show_cmd = 1 if show_app else 0

            win32api.ShellExecute(0, "print", file_path, f'/d:"{printer_name}"', ".", show_cmd)

            app_status = "（显示应用窗口）" if show_app else "（隐藏应用窗口）"
            logger.info("文件已发送到打印机%s: %s", app_status, file_path)
            return {
                "success": True,
                "message": f"打印任务已发送到打印机{app_status}",
                "file": os.path.basename(file_path),
                "printer": printer_name,
                "show_app": show_app,
            }

        except RECOVERABLE_ERRORS as e:
            logger.error("打印文件失败: %s", e)
            return {"success": False, "message": f"打印失败: {str(e)}"}


sync_mixin_methods(
    PrintFileExecutionMixin,
    target=globals(),
    source_module="app.utils.print_utils",
    method_names=(
        "print_file",
        "_print_excel",
        "_print_pdf",
        "_print_default",
    ),
)
