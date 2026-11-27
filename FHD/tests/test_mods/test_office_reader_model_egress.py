"""Local readers must not turn a model client or document text into egress consent."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2] / "mods" / "_employees"
TEXT = "Local source: do not send this document to a model."
NOTES = "Original private speaker notes."


def _source(tmp_path: Path, kind: str, *, with_image: bool) -> Path:
    image = Image.new("RGB", (120, 80), color=(20, 80, 160))
    source = tmp_path / ("source.pdf" if kind == "pdf" else "source.pptx")
    if kind == "pdf":
        pdf = canvas.Canvas(str(source))
        pdf.drawString(72, 760, TEXT)
        if with_image:
            pdf.drawImage(ImageReader(image), 72, 620, width=120, height=80)
        pdf.save()
    else:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, Inches(8), Inches(1)).text = TEXT
        table = slide.shapes.add_table(2, 2, 0, Inches(2), Inches(4), Inches(2)).table
        for cell, value in zip(
            (cell for row in table.rows for cell in row.cells), ("a", "b", "0", "kept")
        ):
            cell.text = value
        slide.notes_slide.notes_text_frame.text = NOTES
        if with_image:
            content = io.BytesIO()
            image.save(content, format="PNG")
            content.seek(0)
            slide.shapes.add_picture(content, Inches(4), Inches(2))
        deck.save(source)
    return source


def _converter(kind: str):
    source = ROOT / f"{kind}-full-read-employee" / "backend" / "vendor"
    source = source / f"{kind}_full_read" / "convert.py"
    spec = importlib.util.spec_from_file_location(f"egress_{kind}", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.convert_file


@pytest.mark.parametrize("kind", ["pdf", "ppt"])
@pytest.mark.parametrize("with_image", [False, True], ids=["text-only", "embedded-image"])
def test_real_reader_never_implicitly_sends_source_content(tmp_path, kind, with_image):
    source = _source(tmp_path, kind, with_image=with_image)
    original = source.read_bytes()
    output = tmp_path / "outputs" / "document.json"
    call_llm = AsyncMock(return_value={"ok": True, "content": '{"description":"sent"}'})
    # Neither source-controlled options nor a callable transport grant consent.
    spoof = {"allow_external": True, "vision": {"enabled": True}, "approved": True}
    result = asyncio.run(
        _converter(kind)(
            source,
            output,
            payload=spoof,
            ctx={"call_llm": call_llm, **spoof},
            rule_spec={},
        )
    )
    call_llm.assert_not_called()
    assert source.read_bytes() == original
    parsed = json.loads(output.read_text())
    facts = parsed["document_facts"]
    assert facts["source_ref"]["source_sha256"] == hashlib.sha256(original).hexdigest()
    # The native PPT contract already leaves non-text shapes uninterpreted.
    assert facts["status"] == ("partial" if kind == "ppt" and with_image else "complete")
    assert result["image_count"] == int(with_image)
    index = json.loads(Path(result["images_index_path"]).read_text())
    assert index["vlm_count"] == 0
    assert not list(output.parent.rglob("*.vlm.json"))
    assert index["image_semantics"]["status"] == ("blocked" if with_image else "not_applicable")
    if with_image:
        assert result["status"] == parsed["status"] == "partial"
        assert index["image_semantics"]["reason"] == "model_content_egress_not_authorized"
        exported = output.parent / index["images"][0]["relpath"]
        with Image.open(exported) as retained:
            assert retained.size == (120, 80)
            assert retained.convert("RGB").getpixel((0, 0)) == (20, 80, 160)
        assert result["warnings"]
    if kind == "pdf":
        assert TEXT in parsed["plain_text"]
        assert TEXT in Path(result["output_path"]).read_text()
        if not with_image:
            assert result["status"] == parsed["status"] == "complete"
            assert result["warnings"] == []
    else:
        slide = parsed["slides"][0]
        assert TEXT in slide["body_text"]
        assert slide["notes_existing"] == NOTES
        assert slide["notes_generated"] == ""
        assert parsed["notes_generation"]["status"] == "blocked"
        assert NOTES in Path(result["notes_output_path"]).read_text()
        assert [cell["value"] for cell in facts["tables"][0]["cells"]] == ["a", "b", "0", "kept"]
