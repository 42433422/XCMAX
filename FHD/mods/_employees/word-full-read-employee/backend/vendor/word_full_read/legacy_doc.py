"""Vendor 内嵌：旧版 .doc (OLE) → .docx，供员工包 convert 导入（无 modstore 依赖）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Tuple

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def is_ole_compound_file(path: Path) -> bool:
    try:
        with Path(path).open("rb") as fh:
            return fh.read(8) == _OLE_MAGIC
    except OSError:
        return False


def is_zip_docx(path: Path) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            return "word/document.xml" in zf.namelist()
    except Exception:
        return False


def needs_legacy_conversion(path: Path) -> bool:
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".doc":
        return True
    if suf == ".docx" and is_ole_compound_file(p) and not is_zip_docx(p):
        return True
    return False


def _soffice_bins() -> list:
    env = (os.environ.get("LIBREOFFICE_PATH") or "").strip()
    bins = []
    if env:
        bins.append(env)
    bins.extend(
        [
            "soffice",
            "libreoffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/bin/libreoffice",
            "/usr/bin/soffice",
        ]
    )
    return bins


def _convert_soffice(src: Path, work_dir: Path) -> Path | None:
    src = Path(src).resolve()
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    for bin_path in _soffice_bins():
        exe = bin_path
        if "/" not in bin_path and not Path(bin_path).is_file():
            found = shutil.which(bin_path)
            if not found:
                continue
            exe = found
        elif not Path(exe).is_file():
            continue
        try:
            subprocess.run(
                [exe, "--headless", "--nologo", "--nofirststartwizard", "--convert-to", "docx", "--outdir", str(work_dir), str(src)],
                check=True,
                capture_output=True,
                timeout=int(os.environ.get("LEGACY_DOC_CONVERT_TIMEOUT", "180")),
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
        out = work_dir / f"{src.stem}.docx"
        if out.is_file() and is_zip_docx(out):
            return out
    return None


def _convert_textutil(src: Path, dest: Path) -> bool:
    if os.uname().sysname != "Darwin":
        return False
    tu = shutil.which("textutil")
    if not tu:
        return False
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([tu, "-convert", "docx", "-output", str(dest), str(src)], check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return dest.is_file() and is_zip_docx(dest)


def ensure_docx_for_extract(src_path: Path, work_dir: Path) -> Tuple[Path, Dict[str, Any]]:
    """返回可用于 OOXML 解析的 .docx 路径及转换元数据。"""
    src_path = Path(src_path).resolve()
    work_dir = Path(work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    meta: Dict[str, Any] = {
        "original_path": str(src_path),
        "original_suffix": src_path.suffix.lower(),
        "converted": False,
        "method": None,
    }

    if src_path.suffix.lower() == ".docx" and is_zip_docx(src_path):
        meta["method"] = "native_docx"
        return src_path, meta

    if not needs_legacy_conversion(src_path):
        if src_path.suffix.lower() == ".docx":
            raise ValueError("文件扩展名为 .docx 但不是有效的 OOXML 包（可能是误命名的旧版 .doc）")
        raise ValueError(f"不支持的文件类型：{src_path.suffix or '(无后缀)'}")

    dest = work_dir / f"{src_path.stem}_legacy.docx"
    soffice_out = _convert_soffice(src_path, work_dir)
    if soffice_out and soffice_out.is_file():
        if soffice_out != dest:
            shutil.copy2(soffice_out, dest)
        meta["converted"] = True
        meta["method"] = "libreoffice"
        meta["docx_path"] = str(dest)
        return dest, meta

    if _convert_textutil(src_path, dest):
        meta["converted"] = True
        meta["method"] = "textutil"
        meta["docx_path"] = str(dest)
        return dest, meta

    raise ValueError(
        "无法解析旧版 .doc：请安装 LibreOffice（soffice --headless）或在 macOS 使用 textutil；"
        "也可在 Word 中另存为 .docx 后重试"
    )
