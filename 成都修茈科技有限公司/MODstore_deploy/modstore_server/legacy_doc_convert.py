"""平台侧：旧版 Word .doc → .docx（供 word_extract_runtime 与测试使用）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from modstore_server.legacy_doc_vendor import (
    ensure_docx_for_extract,
    is_ole_compound_file,
    is_zip_docx,
    needs_legacy_conversion,
)


def render_legacy_doc_vendor_module() -> str:
    from pathlib import Path as _P

    p = _P(__file__).resolve().parent / "legacy_doc_vendor.py"
    return p.read_text(encoding="utf-8")


__all__ = [
    "ensure_docx_for_extract",
    "is_ole_compound_file",
    "is_zip_docx",
    "needs_legacy_conversion",
    "render_legacy_doc_vendor_module",
]
