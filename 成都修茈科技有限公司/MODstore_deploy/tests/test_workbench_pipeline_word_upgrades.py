"""Tests for Word full-extract 13-step pipeline upgrades."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from modstore_server.employee_brief_utils import extract_routing_brief
from modstore_server.employee_pack_export import collect_vendor_modules_from_pack
from modstore_server.word_extract_runtime import (
    is_word_full_extract,
    minimal_docx_bytes,
    word_extract_orchestration_plan,
)


def test_word_orchestration_plan_uses_clean_display_name():
    polluted = "【初始想法】\nWord docx 全量提取 JSON txt\n---\n【执行清单】\n1. parse"
    rb = extract_routing_brief({"brief": polluted}, fallback=polluted)
    plan = word_extract_orchestration_plan(rb, {"brief": polluted})
    assert plan["employee_name"] == "Word 全量提取员"
    assert "【初始想法】" not in plan["employee_name"]
    assert "direct_python" in plan["employee_brief"]


def test_minimal_docx_is_valid_zip():
    raw = minimal_docx_bytes()
    assert raw[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = zf.namelist()
        assert "word/document.xml" in names


def test_collect_vendor_modules_strips_runtime_prefix(tmp_path: Path):
    pack = tmp_path / "pack"
    vendor = pack / "backend" / "vendor" / "word_full_extract"
    vendor.mkdir(parents=True)
    (vendor / "convert.py").write_text("def convert_file(): pass\n", encoding="utf-8")
    mods = collect_vendor_modules_from_pack(pack)
    assert mods is not None
    assert "convert.py" in mods
    assert "word_full_extract/convert.py" not in mods


def test_routing_brief_still_detects_word_after_pollution():
    polluted = (
        "【初始想法】\n全量提取 Word 文档所有格式和信息，输出 JSON 和 txt\n\n---\n"
        "【澄清对话】\n助手：若无疑问，将按此方案生成"
    )
    rb = extract_routing_brief({"brief": polluted}, fallback=polluted)
    assert is_word_full_extract(rb)
