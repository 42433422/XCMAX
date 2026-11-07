"""Reject uploads whose bytes or declared MIME type disagree with the file suffix."""

from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

from app.application.elt.errors import EltError

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ENCRYPTED_OOXML_MARKER = "EncryptedPackage".encode("utf-16-le")
_GENERIC_MIME = {"", "application/octet-stream", "binary/octet-stream"}
_ZIP_MIME = {"application/zip", "application/x-zip-compressed"}
_OOXML_PART = {
    ".xlsx": "xl/workbook.xml",
    ".xlsm": "xl/workbook.xml",
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
}
_LABEL = {
    ".xlsx": "Excel 工作簿",
    ".xlsm": "Excel 工作簿",
    ".csv": "CSV 表格",
    ".docx": "Word 文档",
    ".doc": "Word 文档",
    ".pptx": "PPT 演示文稿",
    ".ppt": "PPT 演示文稿",
    ".pdf": "PDF 文档",
    ".png": "PNG 图片",
    ".jpg": "JPEG 图片",
    ".jpeg": "JPEG 图片",
}
_MIME = {
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        *_ZIP_MIME,
    },
    ".xlsm": {
        "application/vnd.ms-excel.sheet.macroenabled.12",
        "application/vnd.ms-excel",
        *_ZIP_MIME,
    },
    ".csv": {
        "text/csv",
        "text/plain",
        "application/csv",
        "text/x-csv",
        "text/comma-separated-values",
        "application/vnd.ms-excel",
    },
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        *_ZIP_MIME,
    },
    ".doc": {"application/msword"},
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
        *_ZIP_MIME,
    },
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg", "image/pjpeg"},
    ".jpeg": {"image/jpeg", "image/pjpeg"},
}
_IMAGE_MAGIC = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
_BINARY_MAGIC = (b"PK\x03\x04", _OLE_MAGIC, b"%PDF-", b"\x89PNG", b"\xff\xd8\xff")
# Bounds decompression work for archive members before any parser touches them.
_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def _mismatch(suffix: str, detail: str) -> EltError:
    return EltError(
        "ELT_FILE_FORMAT_MISMATCH",
        f"文件内容与扩展名 {suffix} 不符：{detail}，请上传真实的{_LABEL[suffix]}",
    )


def _corrupted(detail: str) -> EltError:
    return EltError("ELT_FILE_CORRUPTED", f"文件已损坏或无法解压：{detail}，请重新导出后上传")


def check_declared_mime(suffix: str, content_type: str | None) -> None:
    declared = str(content_type or "").split(";", 1)[0].strip().lower()
    if declared in _GENERIC_MIME or declared in _MIME[suffix]:
        return
    raise EltError(
        "ELT_FILE_MIME_MISMATCH",
        f"文件类型声明 {declared} 与扩展名 {suffix} 不符，请上传真实的{_LABEL[suffix]}",
    )


ENCRYPTED_OFFICE_MESSAGE = "文件已加密（受密码保护），请先在 Office 中取消打开密码后再上传"


def is_encrypted_office(body: bytes) -> bool:
    """Password-protected .xlsx/.docx/.pptx are OLE containers holding an EncryptedPackage."""
    return body.startswith(_OLE_MAGIC) and _ENCRYPTED_OOXML_MARKER in body


def _check_ooxml(path: Path, suffix: str, head: bytes) -> None:
    if head.startswith(_OLE_MAGIC):
        if is_encrypted_office(path.read_bytes()):
            raise EltError("ELT_FILE_ENCRYPTED", ENCRYPTED_OFFICE_MESSAGE)
        raise _mismatch(suffix, "实际是旧版二进制 Office 格式，请另存为新版格式")
    if not head.startswith(b"PK\x03\x04"):
        raise _mismatch(suffix, "不是有效的 Office Open XML 文件")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if sum(item.file_size for item in members) > _MAX_UNCOMPRESSED_BYTES:
                raise _corrupted("解压后体积异常")
            if any(item.flag_bits & 0x1 for item in members):
                raise EltError(
                    "ELT_FILE_ENCRYPTED", "压缩包内容已加密，无法读取，请取消密码后再上传"
                )
            if _OOXML_PART[suffix] not in {item.filename for item in members}:
                raise _mismatch(suffix, f"缺少 {_OOXML_PART[suffix]}")
            broken = archive.testzip()
    except (
        zipfile.BadZipFile,
        zlib.error,
        EOFError,
        OSError,
        ValueError,
        NotImplementedError,
    ) as exc:
        raise _corrupted("压缩结构不完整") from exc
    if broken is not None:
        raise _corrupted(f"内部文件 {broken} 校验失败")


def check_stored_content(path: Path, suffix: str) -> None:
    with path.open("rb") as handle:
        head = handle.read(64 * 1024)
    if suffix in _OOXML_PART:
        _check_ooxml(path, suffix, head)
    elif suffix in {".doc", ".ppt"}:
        if not head.startswith(_OLE_MAGIC):
            raise _mismatch(suffix, "不是旧版 Office 二进制文件")
    elif suffix == ".pdf":
        if b"%PDF-" not in head[:1024]:
            raise _mismatch(suffix, "缺少 PDF 文件头")
    elif suffix in _IMAGE_MAGIC:
        if not head.startswith(_IMAGE_MAGIC[suffix]):
            raise _mismatch(suffix, "图片文件头不匹配")
    elif suffix == ".csv":
        if b"\x00" in head or head.startswith(_BINARY_MAGIC):
            raise _mismatch(suffix, "包含二进制内容，不是文本表格")
