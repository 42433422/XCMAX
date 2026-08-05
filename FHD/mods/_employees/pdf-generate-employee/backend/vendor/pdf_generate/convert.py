from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _blocks_from_text(plain: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for para in plain.split("\n\n"):
        t = para.strip()
        if t:
            blocks.append({"type": "paragraph", "text": t})
    if not blocks and plain.strip():
        blocks.append({"type": "paragraph", "text": plain.strip()})
    return blocks


def _extract_pdf(src_path: Path) -> Dict[str, Any]:
    from pypdf import PdfReader

    reader = PdfReader(str(src_path))
    pages: List[Dict[str, Any]] = []
    all_text: List[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        all_text.append(text)
        pages.append({"page": idx, "text": text, "char_count": len(text)})
    return {"engine": "pypdf", "pages": pages, "plain_text": "\n\n".join(all_text)}


def _write_pdf_from_json(payload: Dict[str, Any], out_path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    font_name = "STSong-Light"
    try:
        pdfmetrics.getFont(font_name)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    if not pages:
        plain = str(payload.get("plain_text") or "")
        pages = [{"page": 1, "text": plain}]

    pdf = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    rendered_page = False
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        if rendered_page:
            pdf.showPage()
        rendered_page = True
        text = str(pg.get("text") or "")
        text_object = pdf.beginText(54, height - 54)
        text_object.setFont(font_name, 11)
        text_object.setLeading(17)
        raw_lines = text.splitlines() or [""]
        for raw_line in raw_lines:
            chunks = [raw_line[i : i + 48] for i in range(0, len(raw_line), 48)] or [""]
            for line in chunks:
                if text_object.getY() < 54:
                    pdf.drawText(text_object)
                    pdf.showPage()
                    text_object = pdf.beginText(54, height - 54)
                    text_object.setFont(font_name, 11)
                    text_object.setLeading(17)
                text_object.textLine(line)
        pdf.drawText(text_object)
    if not rendered_page:
        pdf.drawString(54, height - 54, "")
    pdf.save()


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from app.application.office_plaintext_generate import resolve_pdf_document_spec

    suffix = src_path.suffix.lower()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "document_parsed.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    pdf_path = output_dir / "generated_document.pdf"
    if str(rule_spec.get("default_pdf_output_relpath") or "").endswith(".pdf"):
        pdf_path = output_dir / Path(str(rule_spec.get("default_pdf_output_relpath"))).name

    if suffix in (".json", ".txt"):
        spec, _warnings = await resolve_pdf_document_spec(
            src_path, payload or {}, ctx or {}, rule_spec or {}
        )
        plain = str(spec.get("plain_text") or "")
        pages = spec.get("pages") if isinstance(spec.get("pages"), list) else []
        blocks = _blocks_from_text(plain)
        payload_data: Dict[str, Any] = {
            "metadata": {"source": src_path.name, "format": "pdf", "engine": "plaintext"},
            "pages": pages,
            "blocks": blocks,
            "plain_text": plain,
            "stats": {
                "page_count": len(pages),
                "block_count": len(blocks),
                "char_count": len(plain),
            },
        }
    elif suffix == ".pdf":
        extracted = _extract_pdf(src_path)
        plain = str(extracted.get("plain_text") or "")
        pages = extracted.get("pages") if isinstance(extracted.get("pages"), list) else []
        blocks = _blocks_from_text(plain)
        payload_data = {
            "metadata": {
                "source": src_path.name,
                "format": "pdf",
                "engine": extracted.get("engine"),
            },
            "pages": pages,
            "blocks": blocks,
            "plain_text": plain,
            "stats": {
                "page_count": len(pages),
                "block_count": len(blocks),
                "char_count": len(plain),
            },
        }
    else:
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，支持 .pdf / .json / .txt")

    json_path.write_text(json.dumps(payload_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_pdf_from_json(payload_data, pdf_path)

    stats = payload_data.get("stats") or {}
    return {
        "output_path": str(json_path),
        "pdf_output_path": str(pdf_path),
        "page_count": stats.get("page_count", 0),
        "block_count": stats.get("block_count", 0),
        "char_count": stats.get("char_count", 0),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
