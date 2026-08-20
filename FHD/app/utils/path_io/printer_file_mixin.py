"""Format-specific print implementations for :class:`PrinterUtils`."""

from __future__ import annotations

from typing import Any, cast


def _facade() -> Any:
    from app.utils.path_io import print_utils

    return print_utils


class PrinterFileMixin:
    def _print_excel(self, file_path: str, printer_name: str) -> dict:
        printer = cast(Any, self)
        if not printer._is_print_backend_available():
            return cast(dict, printer._build_unavailable_result())
        validated_file = printer._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return {"success": False, "message": "打印失败：文件不在允许的打印目录中"}
        file_path = validated_file
        if _facade().win32api is None and (not hasattr(_facade().os, "startfile")):
            return cast(dict, printer._print_cups(file_path, printer_name))
        try:
            _facade().logger.info("开始打印Excel文件: %s", file_path)
            _facade().logger.info("使用打印机: %s", printer_name)
            try:
                _facade().logger.info("方法1: 使用os.startfile打印")
                cast("Any", _facade().os).startfile(file_path, "print")
                _facade().logger.info("os.startfile打印成功: %s", file_path)
                return {
                    "success": True,
                    "message": "打印任务已发送（os.startfile）",
                    "file": _facade().os.path.basename(file_path),
                    "printer": printer_name,
                }
            except _facade().RECOVERABLE_ERRORS as e1:
                _facade().logger.warning("方法1失败: %s", e1)
                try:
                    _facade().logger.info("方法2: 使用ShellExecute print")
                    result = _facade().win32api.ShellExecute(0, "print", file_path, None, ".", 1)
                    if result > 32:
                        _facade().logger.info("ShellExecute打印成功: %s", file_path)
                        return {
                            "success": True,
                            "message": "打印任务已发送到打印机",
                            "file": _facade().os.path.basename(file_path),
                            "printer": printer_name,
                        }
                    else:
                        raise Exception(f"ShellExecute失败，错误代码: {result}")
                except _facade().RECOVERABLE_ERRORS as e2:
                    _facade().logger.warning("方法2失败: %s", e2)
                    try:
                        _facade().logger.info("方法3: 打开文件让用户手动打印")
                        cast("Any", _facade().os).startfile(file_path)
                        _facade().logger.info("已打开文件: %s", file_path)
                        return {
                            "success": True,
                            "message": "文件已打开，请手动打印",
                            "file": _facade().os.path.basename(file_path),
                            "printer": printer_name,
                            "manual": True,
                        }
                    except _facade().RECOVERABLE_ERRORS as e3:
                        _facade().logger.error("方法3也失败: %s", e3)
                        raise Exception(f"所有打印方法都失败: {e1}; {e2}; {e3}")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("打印Excel文件失败")
            return {"success": False, "message": "打印 Excel 文件失败"}

    def _print_pdf(self, file_path: str, printer_name: str) -> dict:
        printer = cast(Any, self)
        if not printer._is_print_backend_available():
            return cast(dict, printer._build_unavailable_result())
        validated_file = printer._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return {"success": False, "message": "打印失败：文件不在允许的打印目录中"}
        file_path = validated_file
        if _facade().win32print is None:
            return cast(dict, printer._print_cups(file_path, printer_name))
        try:
            _facade().logger.info("尝试使用win32print直接打印PDF到 %s", printer_name)
            try:
                hprinter = _facade().win32print.OpenPrinter(printer_name)
                try:
                    with open(file_path, "rb") as f:
                        file_data = f.read()
                    _facade().win32print.StartDocPrinter(hprinter, 1, ("PDF Job", None, "RAW"))
                    _facade().win32print.StartPagePrinter(hprinter)
                    _facade().win32print.WritePrinter(hprinter, file_data)
                    _facade().win32print.EndPagePrinter(hprinter)
                    _facade().win32print.EndDocPrinter(hprinter)
                    _facade().logger.info("PDF文件已通过win32print发送到打印机: %s", file_path)
                    return {
                        "success": True,
                        "message": "PDF文件已发送到打印机",
                        "file": _facade().os.path.basename(file_path),
                        "printer": printer_name,
                        "method": "win32print",
                    }
                finally:
                    _facade().win32print.ClosePrinter(hprinter)
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.warning("win32print打印失败: %s", e)
            _facade().logger.info("尝试使用subprocess调用外部程序")
            try:
                adobe_paths = [
                    "C:\\Program Files (x86)\\Adobe\\Acrobat Reader DC\\Reader\\AcroRd32.exe",
                    "C:\\Program Files\\Adobe\\Acrobat Reader DC\\Reader\\AcroRd32.exe",
                ]
                for adobe_path in adobe_paths:
                    if _facade().os.path.exists(adobe_path):
                        _facade().logger.info("使用Adobe Reader: %s", adobe_path)
                        _facade().subprocess.run(
                            [adobe_path, "/t", file_path, printer_name],
                            check=True,
                            timeout=30,
                            capture_output=True,
                        )
                        _facade().logger.info("PDF文件已通过Adobe Reader发送到打印机")
                        return {
                            "success": True,
                            "message": "PDF文件已通过Adobe Reader发送到打印机",
                            "file": _facade().os.path.basename(file_path),
                            "printer": printer_name,
                            "method": "adobe_cli",
                        }
                _facade().logger.warning("未找到Adobe Reader")
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.warning("subprocess方法失败: %s", e)
            raise Exception("所有PDF打印方法都失败")
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("打印PDF文件失败")
            return {"success": False, "message": "打印 PDF 文件失败"}

    def _print_default(self, file_path: str, printer_name: str, show_app: bool = False) -> dict:
        printer = cast(Any, self)
        if not printer._is_print_backend_available():
            return cast(dict, printer._build_unavailable_result())
        validated_file = printer._resolve_allowed_print_path(file_path)
        if validated_file is None:
            return {"success": False, "message": "打印失败：文件不在允许的打印目录中"}
        file_path = validated_file
        if _facade().win32api is None:
            return cast(dict, printer._print_cups(file_path, printer_name))
        try:
            show_cmd = 1 if show_app else 0
            _facade().win32api.ShellExecute(
                0, "print", file_path, f'/d:"{printer_name}"', ".", show_cmd
            )
            app_status = "（显示应用窗口）" if show_app else "（隐藏应用窗口）"
            _facade().logger.info("文件已发送到打印机%s: %s", app_status, file_path)
            return {
                "success": True,
                "message": f"打印任务已发送到打印机{app_status}",
                "file": _facade().os.path.basename(file_path),
                "printer": printer_name,
                "show_app": show_app,
            }
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("打印文件失败")
            return {"success": False, "message": "打印文件失败"}
