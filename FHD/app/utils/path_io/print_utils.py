"""Printing utilities."""

import logging
import os
import re
import subprocess
import sys as sys
import tempfile as tempfile
import time
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.printer_cups_mixin import PrinterCupsMixin
from app.utils.path_io.printer_file_mixin import PrinterFileMixin

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_CUPS_ERRORS = RECOVERABLE_ERRORS + (subprocess.SubprocessError,)
_CUPS_LP = "/usr/bin/lp"
_CUPS_LPSTAT = "/usr/bin/lpstat"
_CUPS_PRINTER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")


class PrinterUtils(PrinterCupsMixin, PrinterFileMixin):
    def __init__(self):
        self._com_initialized = False

    def _ensure_com_initialized(self):
        if pythoncom is None:
            return
        if not self._com_initialized:
            try:
                pythoncom.CoInitialize()
                self._com_initialized = True
            except RECOVERABLE_ERRORS as e:
                logger.warning("COM初始化警告: %s", e)

    def get_available_printers(self) -> list[dict[str, Any]]:
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
            except RECOVERABLE_ERRORS:
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
                        except RECOVERABLE_ERRORS:
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

    def print_file(
        self, file_path: str, printer_name: str | None = None, use_default_printer: bool = False
    ) -> dict:
        if not self._is_print_backend_available():
            return self._build_unavailable_result()
        try:
            if not printer_name:
                logger.error("未指定打印机名称，拒绝打印")
                return {"success": False, "message": "未指定打印机名称，无法打印"}
            validated_file = self._resolve_allowed_print_path(file_path)
            if validated_file is None:
                return {"success": False, "message": "文件不存在或不在允许的打印目录中"}
            file_path = validated_file
            if not os.path.exists(file_path):
                return {"success": False, "message": "文件不存在"}

            _, ext = os.path.splitext(file_path)
            ext = ext.lower()

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

                        time.sleep(0.5)
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
                                time.sleep(0.5)
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

    def get_default_printer(self) -> str | None:
        if not self._is_print_backend_available():
            logger.warning(self._build_unavailable_result()["message"])
            return None
        if win32print is None:
            return self._get_cups_default_printer()
        try:
            return cast("str | None", win32print.GetDefaultPrinter())
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
                    return str(printer["name"])

            return str(printers[0]["name"]) if printers else None

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
                    return str(printer["name"])

            return None

        except RECOVERABLE_ERRORS as e:
            logger.error("获取标签打印机失败: %s", e)
            return None
