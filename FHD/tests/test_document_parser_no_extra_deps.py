"""DocumentParser：不引入新依赖的表格/页眉/PPT/编码增强。"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches

from app.application.dataset_rag.document_parser import DocumentParser


class _ChunkerStub:
    def split_by_semantic(self, text: str):
        return [text]

    def split_by_fixed(self, text: str, **_kwargs):
        return [text]


def _parser(tmp_path: Path) -> DocumentParser:
    return DocumentParser(
        chunker=_ChunkerStub(),  # type: ignore[arg-type]
        allowed_roots=[tmp_path],
        default_roots=lambda: [tmp_path],
    )


def test_docx_extracts_header_and_table_markdown(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "页眉：质量周报"
    doc.add_paragraph("本周良率 98.6%")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "数值"
    table.cell(1, 0).text = "不良数"
    table.cell(1, 1).text = "12"
    doc.save(path)

    text, parser, meta = _parser(tmp_path)._extract_file_text(path)

    assert parser == "python-docx"
    assert "页眉：质量周报" in text
    assert "本周良率 98.6%" in text
    assert "| 项目 | 数值 |" in text
    assert "| 不良数 | 12 |" in text
    assert meta["table_count"] == 1
    assert meta["header_paragraph_count"] == 1


def test_pptx_extracts_slide_text_and_table(tmp_path: Path) -> None:
    path = tmp_path / "deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "生产日报"
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text = "产线"
    table.cell(0, 1).text = "产量"
    table.cell(1, 0).text = "A线"
    table.cell(1, 1).text = "1200"
    prs.save(path)

    text, parser, meta = _parser(tmp_path)._extract_file_text(path)

    assert parser == "python-pptx"
    assert "生产日报" in text
    assert "| 产线 | 产量 |" in text
    assert "| A线 | 1200 |" in text
    assert meta["slide_count"] == 1
    assert meta["table_count"] == 1


def test_text_file_falls_back_to_gb18030(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_bytes("中文字段：数量".encode("gb18030"))

    text, parser, meta = _parser(tmp_path)._extract_file_text(path)

    assert parser == "text_file"
    assert text == "中文字段：数量"
    assert meta["encoding"] == "gb18030"


def test_xlsx_merge_cells_still_extract_values(tmp_path: Path) -> None:
    path = tmp_path / "ledger.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "台账"
    ws["A1"] = "客户"
    ws["B1"] = "数量"
    ws["A2"] = "甲公司"
    ws["B2"] = 3
    wb.save(path)

    text, parser, meta = _parser(tmp_path)._extract_file_text(path)

    assert parser == "openpyxl"
    assert "[sheet 台账]" in text
    assert "客户\t数量" in text
    assert meta["sheet_count"] == 1
