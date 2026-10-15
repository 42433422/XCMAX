"""Office generate employees must write to the caller-requested output path."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "mods" / "_employees"


def _convert(employee: str, package: str):
    path = ROOT / employee / "backend" / "vendor" / package / "convert.py"
    spec = importlib.util.spec_from_file_location(f"_{package}_convert_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.convert_file


def _rule_spec(employee: str) -> dict:
    return json.loads((ROOT / employee / "rule_spec.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "employee,package,suffix",
    [
        ("word-generate-employee", "word_generate", ".docx"),
        ("pdf-generate-employee", "pdf_generate", ".pdf"),
    ],
)
def test_requested_output_name_is_written(tmp_path, employee, package, suffix):
    pytest.importorskip("docx" if suffix == ".docx" else "reportlab")
    src = tmp_path / "input.txt"
    src.write_text("验收文档\n客户：太阳鸟\n产品：包装盒 数量：24", encoding="utf-8")
    out = tmp_path / "outputs" / f"custom-name{suffix}"
    result = asyncio.run(
        _convert(employee, package)(
            src,
            out,
            template_path=None,
            payload={"plain_text": src.read_text(encoding="utf-8")},
            ctx={"workspace_root": str(tmp_path)},
            rule_spec=_rule_spec(employee),
        )
    )
    assert out.is_file()
    assert str(out) in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("name", ["custom-read.json", "custom-read.txt"])
def test_pdf_read_writes_requested_output_name(tmp_path, name):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    src = tmp_path / "input.pdf"
    doc = canvas.Canvas(str(src))
    doc.drawString(72, 720, "SUNBIRD packing box x24")
    doc.save()
    out = tmp_path / "outputs" / name
    asyncio.run(
        _convert("pdf-full-read-employee", "pdf_full_read")(
            src,
            out,
            payload={},
            ctx={},
            rule_spec=_rule_spec("pdf-full-read-employee"),
        )
    )
    assert out.is_file()
    assert "SUNBIRD" in out.read_text(encoding="utf-8")
