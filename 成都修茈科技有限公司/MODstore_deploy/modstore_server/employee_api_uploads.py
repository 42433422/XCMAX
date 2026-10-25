"""Upload suffix and size policy for employee task execution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from modstore_server.employee_api_support import _candidate_employee_pack_ids

_EMPLOYEE_UPLOAD_MAX_DEFAULT = 100 * 1024 * 1024
_EMPLOYEE_UPLOAD_ALLOWED_SUFFIX = frozenset(
    {
        ".xlsx",
        ".xlsm",
        ".xls",
        ".csv",
        ".pdf",
        ".pptx",
        ".ppt",
        ".docx",
        ".doc",
        ".docm",
        ".dotx",
        ".dotm",
        ".rtf",
        ".json",
        ".txt",
    }
)
_READ_EMPLOYEE_SUFFIX: Dict[str, frozenset] = {
    "excel-full-read-employee": frozenset({".xlsx", ".xlsm", ".xls"}),
    "csv-full-read-employee": frozenset({".csv"}),
    "pdf-full-read-employee": frozenset({".pdf"}),
    "ppt-full-read-employee": frozenset({".pptx", ".ppt"}),
    "word-full-read-employee": frozenset({".docx", ".doc", ".docm", ".dotx", ".dotm", ".rtf"}),
    "json-report-employee": frozenset({".json"}),
}


def _suffix_allowed_for_employee(employee_id: str, suffix: str) -> bool:
    if suffix not in _EMPLOYEE_UPLOAD_ALLOWED_SUFFIX:
        return False
    from modstore_server.office_plaintext_generate import (
        GENERATE_EMPLOYEE_IDS,
        suffix_allowed_for_generate_employee,
    )

    for pid in _candidate_employee_pack_ids(employee_id):
        if pid in GENERATE_EMPLOYEE_IDS:
            return suffix_allowed_for_generate_employee(pid, suffix)
        allowed = _READ_EMPLOYEE_SUFFIX.get(pid)
        if allowed is not None:
            return suffix in allowed
    read_hint = {
        ".pptx": "ppt-full-read-employee",
        ".ppt": "ppt-full-read-employee",
        ".docx": "word-full-read-employee",
        ".doc": "word-full-read-employee",
        ".xlsx": "excel-full-read-employee",
        ".csv": "csv-full-read-employee",
        ".pdf": "pdf-full-read-employee",
    }.get(suffix)
    if read_hint:
        return False
    return True


def _employee_upload_suffix_mismatch_message(employee_id: str, suffix: str) -> str:
    """Human-readable hint when execute-file suffix does not match selected employee."""
    from modstore_server.office_plaintext_generate import GENERATE_EMPLOYEE_IDS

    ext = suffix.lstrip(".").lower() or "未知"
    read_for_suffix = {
        ".pptx": ("ppt-full-read-employee", "PPT 全量读取员"),
        ".ppt": ("ppt-full-read-employee", "PPT 全量读取员"),
        ".docx": ("word-full-read-employee", "Word 全量读取员"),
        ".doc": ("word-full-read-employee", "Word 全量读取员"),
        ".docm": ("word-full-read-employee", "Word 全量读取员"),
        ".dotx": ("word-full-read-employee", "Word 全量读取员"),
        ".dotm": ("word-full-read-employee", "Word 全量读取员"),
        ".rtf": ("word-full-read-employee", "Word 全量读取员"),
        ".xlsx": ("excel-full-read-employee", "Excel 全量读取员"),
        ".xlsm": ("excel-full-read-employee", "Excel 全量读取员"),
        ".xls": ("excel-full-read-employee", "Excel 全量读取员"),
        ".csv": ("csv-full-read-employee", "CSV 全量读取员"),
        ".pdf": ("pdf-full-read-employee", "PDF 全量读取员"),
    }
    generate_for_suffix = {
        ".pptx": ("ppt-generate-employee", "PPT 生成员"),
        ".ppt": ("ppt-generate-employee", "PPT 生成员"),
        ".docx": ("word-generate-employee", "Word 生成员"),
        ".xlsx": ("excel-generate-employee", "Excel 生成员"),
        ".csv": ("csv-generate-employee", "CSV 生成员"),
        ".pdf": ("pdf-generate-employee", "PDF 生成员"),
    }

    pack_ids = _candidate_employee_pack_ids(employee_id)
    is_generate = any(pid in GENERATE_EMPLOYEE_IDS for pid in pack_ids)

    if suffix not in _EMPLOYEE_UPLOAD_ALLOWED_SUFFIX:
        return f"不支持 .{ext} 上传；读取类支持 Office/PDF，生成员支持 .json/.txt（Word 生成员可选 .docx 模板）"

    read_hint = read_for_suffix.get(suffix)
    if read_hint and is_generate:
        rid, rlabel = read_hint
        gid, glabel = generate_for_suffix.get(suffix, ("", ""))
        gen_part = (
            f"；若要从 JSON 生成 PPT，请先由「{rlabel}」（{rid}）导出 presentation_full.json，再选「{glabel}」（{gid}）"
            if suffix in {".pptx", ".ppt"} and gid
            else f"；请改选「{rlabel}」（{rid}）全量解析该文件"
        )
        return (
            f"生成员「{employee_id}」不接受 .{ext} 原稿{gen_part}。"
            f"生成员仅支持 .json/.txt（Word 生成员可选 .docx 模板）"
        )

    if read_hint:
        rid, rlabel = read_hint
        return f"当前员工不接受 .{ext}；请改选「{rlabel}」（{rid}）"

    if suffix == ".json":
        return (
            "JSON 文件请使用 json-report-employee（量化报告）或对应格式的 *-generate-employee（生成 Office）；"
            "生成员不接受 .pptx/.docx 等原稿"
        )

    return (
        "文件类型与所选员工不匹配；生成员支持 .json/.txt（Word 生成员可选 .docx 模板），"
        "读取类支持 Office/PDF（含 .pptx/.docx/.xlsx/.pdf 等）"
    )


def _employee_upload_max_bytes() -> int:
    raw = (os.environ.get("MODSTORE_EMPLOYEE_FILE_MAX_BYTES") or "").strip()
    if not raw:
        return _EMPLOYEE_UPLOAD_MAX_DEFAULT
    try:
        return max(1, int(raw, 10))
    except ValueError:
        return _EMPLOYEE_UPLOAD_MAX_DEFAULT


def _safe_employee_upload_basename(name: str, fallback: str = "upload.xlsx") -> str:
    base = Path(name or "").name
    if not base or base in {".", ".."}:
        return fallback
    if ".." in base or "/" in base or "\\" in base:
        return fallback
    return base[:200] if len(base) > 200 else base
