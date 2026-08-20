# mypy: disable-error-code="import-untyped"
"""Release-level checks for the PDF employee runtime shipped in desktop builds."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

pytestmark = pytest.mark.release_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, relative_path: str) -> ModuleType:
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pdf_generate_employee_writes_and_reads_real_pdf(tmp_path: Path) -> None:
    module = _load_module(
        "release_pdf_generate_convert",
        "mods/_employees/pdf-generate-employee/backend/vendor/pdf_generate/convert.py",
    )
    output = tmp_path / "generated.pdf"

    module._write_pdf_from_json(
        {"pages": [{"page": 1, "text": "稳定版 PDF 生成验证\nsecond line"}]},
        output,
    )

    assert output.stat().st_size > 512
    assert len(PdfReader(str(output)).pages) == 1
    extracted = module._extract_pdf(output)
    assert extracted["engine"] == "pypdf"
    assert len(extracted["pages"]) == 1


def test_pdf_full_read_employee_extracts_text_and_embedded_images(tmp_path: Path) -> None:
    module = _load_module(
        "release_pdf_full_read_convert",
        "mods/_employees/pdf-full-read-employee/backend/vendor/pdf_full_read/convert.py",
    )
    source = tmp_path / "source.pdf"
    image = Image.new("RGB", (120, 80), color=(20, 80, 160))
    pdf = canvas.Canvas(str(source))
    pdf.drawString(72, 760, "XCAGI PDF extraction probe")
    pdf.drawImage(ImageReader(image), 72, 620, width=120, height=80)
    pdf.save()

    plain, pages, images = module._extract_with_pypdf(source)

    assert "XCAGI PDF extraction probe" in plain
    assert len(pages) == 1
    assert pages[0]["has_text"] is True
    assert len(images) == 1
    assert images[0]["width"] == 120
    assert images[0]["height"] == 80
    assert images[0]["bytes"].startswith(b"\x89PNG")
