import logging
import os
import re
import subprocess
import sys
import tempfile
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


from app.utils.print_cups_execution import PrintCupsExecutionMixin
from app.utils.print_cups_status import PrintCupsStatusMixin
from app.utils.print_file_execution import PrintFileExecutionMixin


class PrinterUtils(PrintCupsStatusMixin, PrintCupsExecutionMixin, PrintFileExecutionMixin):
    def __init__(self):
        self._com_initialized = False

    def get_available_printers(self) -> list[dict[str, str]]:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return []
        if win32print is None:
            return self._get_cups_printers()
        try:
            self._ensure_com_initialized()
            printers = []

            try:
                default_printer = win32print.GetDefaultPrinter()
                logger.info("默认打印机: %s", default_printer)
            except Exception:
                default_printer = None
                logger.warning("无法获取默认打印机")

            all_printers = win32print.EnumPrinters(
                win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            )

            logger.info("找到 %s 个打印机", len(all_printers))

            for printer_info in all_printers:
                logger.info("打印机信息: %s", printer_info)
                logger.info("打印机信息长度: %s", len(printer_info))

                if len(printer_info) >= 3:
                    printer_name = printer_info[2]

                    status = 0
                    if len(printer_info) > 6:
                        status = printer_info[6]
                    elif len(printer_info) > 5:
                        try:
                            status = int(printer_info[5]) if printer_info[5] else 0
                        except Exception:
                            pass

                    status_text = self._get_printer_status(status)

                is_default = printer_name == default_printer

                printers.append(
                    {"name": printer_name, "status": status_text, "is_default": is_default}
                )

                logger.info("  - %s (默认: %s, 状态: %s)", printer_name, is_default, status_text)

            return printers

        except RECOVERABLE_ERRORS as e:
            logger.error("获取打印机列表失败: %s", e, exc_info=True)
            return []

    def _get_printer_status(self, status_code: int) -> str:
        if win32print is None:
            return "不可用"
        status_map = {
            win32print.PRINTER_STATUS_PAUSED: "已暂停",
            win32print.PRINTER_STATUS_ERROR: "错误",
            win32print.PRINTER_STATUS_PENDING_DELETION: "正在删除",
            win32print.PRINTER_STATUS_PAPER_JAM: "卡纸",
            win32print.PRINTER_STATUS_PAPER_OUT: "缺纸",
            win32print.PRINTER_STATUS_MANUAL_FEED: "等待手动送纸",
            win32print.PRINTER_STATUS_PRINTING: "打印中",
            win32print.PRINTER_STATUS_OUTPUT_BIN_FULL: "输出纸盒已满",
            win32print.PRINTER_STATUS_NOT_AVAILABLE: "不可用",
            win32print.PRINTER_STATUS_WAITING: "等待中",
            win32print.PRINTER_STATUS_PROCESSING: "处理中",
            win32print.PRINTER_STATUS_INITIALIZING: "初始化中",
            win32print.PRINTER_STATUS_WARMING_UP: "预热中",
            win32print.PRINTER_STATUS_TONER_LOW: "墨粉不足",
            win32print.PRINTER_STATUS_NO_TONER: "无墨粉",
            win32print.PRINTER_STATUS_PAGE_PUNT: "页面跳过",
            win32print.PRINTER_STATUS_USER_INTERVENTION: "需要用户干预",
            win32print.PRINTER_STATUS_OUT_OF_MEMORY: "内存不足",
            win32print.PRINTER_STATUS_DOOR_OPEN: "前门打开",
            win32print.PRINTER_STATUS_SERVER_UNKNOWN: "服务器未知",
            win32print.PRINTER_STATUS_POWER_SAVE: "节能模式",
        }

        return status_map.get(status_code, "就绪")

    def monitor_print_job(self, printer_name: str, timeout: int = 60) -> bool:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return False
        if win32print is None:
            return self._monitor_cups_print_job(printer_name, timeout)
        try:
            logger.info("开始监控打印机 %s 的打印任务...", printer_name)

            start_time = time.time()

            while time.time() - start_time < timeout:
                try:
                    hPrinter = win32print.OpenPrinter(printer_name)

                    try:
                        jobs = win32print.EnumJobs(hPrinter, 0, -1, 1)

                        if not jobs:
                            logger.info("打印机队列为空，打印任务已完成")
                            return True
                        else:
                            logger.info("打印机队列中有 %s 个任务，等待完成...", len(jobs))
                            for i, job in enumerate(jobs):
                                logger.info("   任务 %s: %s", i + 1, job)
                    finally:
                        win32print.ClosePrinter(hPrinter)

                except RECOVERABLE_ERRORS as e:
                    logger.warning("监控打印任务失败: %s", e)

                time.sleep(1)

            logger.warning("监控打印任务超时（%s秒）", timeout)
            return False

        except RECOVERABLE_ERRORS as e:
            logger.error("监控打印任务时发生错误: %s", e)
            return False

    def get_default_printer(self) -> str | None:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        if win32print is None:
            return self._get_cups_default_printer()
        try:
            return win32print.GetDefaultPrinter()
        except RECOVERABLE_ERRORS as e:
            logger.error("获取默认打印机失败: %s", e)
            return None

    def test_printer(self, printer_name: str) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        if win32print is None:
            printer = next(
                (item for item in self.get_available_printers() if item["name"] == printer_name),
                None,
            )
            if printer is None:
                return {
                    "success": False,
                    "available": False,
                    "printer": printer_name,
                    "message": "打印机不存在或当前不可用",
                }
            return {
                "success": True,
                "available": True,
                "printer": printer_name,
                "status": printer.get("status") or "未知",
            }
        try:
            hprinter = win32print.OpenPrinter(printer_name)

            printer_info = win32print.GetPrinter(hprinter, 2)
            status = printer_info["Status"]
            status_text = self._get_printer_status(status)

            win32print.ClosePrinter(hprinter)

            return {
                "success": True,
                "available": True,
                "printer": printer_name,
                "status": status_text,
            }

        except RECOVERABLE_ERRORS as e:
            logger.error("测试打印机失败: %s", e)
            return {
                "success": False,
                "available": False,
                "printer": printer_name,
                "message": str(e),
            }

    def get_document_printer(self) -> str | None:
        """获取发货单打印机"""
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        try:
            printers = self.get_available_printers()
            if not printers:
                return None

            keywords = [
                "joli",
                "24-pin",
                "dot matrix",
                "impact",
                "lq",
                "针式",
                "hp",
                "canon",
                "epson",
            ]

            for printer in printers:
                name_lower = printer["name"].lower()
                if any(kw in name_lower for kw in keywords):
                    return printer["name"]

            return printers[0]["name"] if printers else None

        except RECOVERABLE_ERRORS as e:
            logger.error("获取发货单打印机失败: %s", e)
            return None

    def get_label_printer(self) -> str | None:
        """获取标签打印机"""
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        try:
            printers = self.get_available_printers()
            if not printers:
                return None

            keywords = ["tsc", "ttp", "label", "标签", "thermal", "barcode", "zebra"]

            for printer in printers:
                name_lower = printer["name"].lower()
                if any(kw in name_lower for kw in keywords):
                    return printer["name"]

            return None

        except RECOVERABLE_ERRORS as e:
            logger.error("获取标签打印机失败: %s", e)
            return None
