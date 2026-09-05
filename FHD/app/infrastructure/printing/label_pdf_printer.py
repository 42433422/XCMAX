"""Submit generated label PDFs without sending PDF bytes as Windows RAW commands."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.infrastructure.printing.label_dispatch_guard import claim_label_dispatch
from app.utils.path_io.path_utils import get_app_data_dir


def is_label_job_location(file_path: str) -> bool:
    root = Path(get_app_data_dir()) / "label_jobs"
    candidate = Path(file_path)
    for value, base in (
        (candidate.absolute(), root.absolute()),
        (candidate.resolve(), root.resolve()),
    ):
        try:
            value.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def owned_label_pdf_path(file_path: str) -> Path | None:
    root = Path(get_app_data_dir()) / "label_jobs"
    path = Path(file_path)
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if (
        len(parts) != 4
        or not all(re.fullmatch(r"[1-9][0-9]*", p) for p in parts[:2])
        or not re.fullmatch(r"[0-9a-f]{32}", parts[2])
        or parts[3] != "labels.pdf"
    ):
        return None
    current = root
    if current.is_symlink():
        return None
    for part in parts:
        current /= part
        if current.is_symlink():
            return None
    return current if current.is_file() else None


def submit_label_pdf(utils: Any, file_path: str, printer: str | None) -> dict:
    path = owned_label_pdf_path(file_path)
    if path is None or not printer:
        return {
            "success": False,
            "submission_state": "rejected",
            "message": "标签文件无效或未选择标签打印机",
        }
    if not claim_label_dispatch(path, printer):
        return {
            "success": False,
            "submission_state": "unknown",
            "message": "标签任务未确认、已提交或缺少内部授权；未重复打印",
        }
    if sys.platform == "darwin":
        printer = utils._resolve_cups_printer_name(printer)
        if not printer:
            return {
                "success": False,
                "submission_state": "rejected",
                "message": "标签打印机不存在或不可用",
            }
        try:
            with path.open("rb") as source:
                result = utils._run_cups(
                    "lp",
                    ("-d", printer, "-o", "fit-to-page=false"),
                    timeout=30,
                    input_stream=source,
                )
        except (OSError, subprocess.SubprocessError):
            return {
                "success": False,
                "submission_state": "unknown",
                "message": "打印服务响应中断，请检查队列",
            }
        if result.returncode != 0:
            return {
                "success": False,
                "submission_state": "rejected",
                "message": "macOS 打印服务拒绝标签任务",
            }
        return {
            "success": True,
            "submission_state": "submitted",
            "message": "标签已提交到 macOS CUPS",
            "printer": printer,
            "method": "cups_pdf",
        }
    if sys.platform == "win32":
        # Adobe is an optional installed desktop application, never an assumed dependency.
        programs = [
            Path(base) / "Adobe" / "Acrobat Reader DC" / "Reader" / "AcroRd32.exe"
            for base in ("C:/Program Files", "C:/Program Files (x86)")
        ]
        reader = next((candidate for candidate in programs if candidate.is_file()), None)
        if reader is None:
            return {
                "success": False,
                "submission_state": "rejected",
                "message": "未找到 Adobe PDF 打印程序，请下载 PDF 手动打印或安装 Adobe Reader 后重试",
            }
        try:
            subprocess.run(
                [str(reader), "/t", str(path), printer], check=True, timeout=30, capture_output=True
            )
        except (OSError, subprocess.SubprocessError):
            return {
                "success": False,
                "submission_state": "unknown",
                "message": "PDF 打印程序响应中断，请检查打印队列",
            }
        # The renderer's exit status cannot prove that Windows spooler accepted a job.
        return {
            "success": False,
            "submission_state": "unknown",
            "message": "PDF 已交给打印程序，队列接收结果待确认",
        }
    return {
        "success": False,
        "submission_state": "rejected",
        "message": "当前系统未提供受支持的标签 PDF 打印接口，请下载后打印",
    }
