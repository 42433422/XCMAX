# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def pack_has_direct_python_runtime(pack_dir: _facade().Path) -> bool:
    """Disk pack contains vendor convert and/or rule_spec for asset/direct_python employees."""
    rs = pack_dir / "rule_spec.json"
    if rs.is_file():
        try:
            data = _facade().json.loads(rs.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("runtime_kind") in (
                "word_full_extract",
                "txt_full_read",
                "txt_generate",
                "pdf_full_read",
                "pdf_generate",
                "csv_full_read",
                "csv_generate",
                "generic_excel_transform",
                "contract_doc_review",
                "doc_template_transform",
            ):
                return True
        except (OSError, _facade().json.JSONDecodeError):
            pass
    backend = pack_dir / "backend"
    if not backend.is_dir():
        return False
    for py_path in backend.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def convert_file" in text and "vendor" in py_path.as_posix().lower():
            return True
        if "def convert" in text and "_import_runtime" in text:
            return True
    return False
