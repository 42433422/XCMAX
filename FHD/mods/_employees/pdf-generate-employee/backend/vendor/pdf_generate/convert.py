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
    try:
        import fitz

        doc = fitz.open(src_path)
        pages: List[Dict[str, Any]] = []
        all_text: List[str] = []
        for i in range(len(doc)):
            text = (doc[i].get_text("text") or "").strip()
            all_text.append(text)
            pages.append({"page": i + 1, "text": text, "char_count": len(text)})
        doc.close()
        plain = "\n\n".join(all_text)
        return {"engine": "pymupdf", "pages": pages, "plain_text": plain}
    except Exception:
        from pypdf import PdfReader

        reader = PdfReader(str(src_path))
        pages = []
        all_text = []
        for idx, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            all_text.append(text)
            pages.append({"page": idx, "text": text, "char_count": len(text)})
        return {"engine": "pypdf", "pages": pages, "plain_text": "\n\n".join(all_text)}


def _write_pdf_from_json(payload: Dict[str, Any], out_path: Path) -> None:
    import fitz

    doc = fitz.open()
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    if not pages:
        plain = str(payload.get("plain_text") or "")
        pages = [{"page": 1, "text": plain}]
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        text = str(pg.get("text") or "")
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((72, 72), text[:12000], fontsize=11)
    doc.save(out_path)
    doc.close()


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from modstore_server.office_plaintext_generate import resolve_pdf_document_spec

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
        spec, _warnings = await resolve_pdf_document_spec(src_path, payload or {}, ctx or {}, rule_spec or {})
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
            "metadata": {"source": src_path.name, "format": "pdf", "engine": extracted.get("engine")},
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