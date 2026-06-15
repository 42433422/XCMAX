from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.office_plaintext_generate import resolve_word_document_spec


def _style_for_paragraph(doc: Any, p: Dict[str, Any]) -> Optional[str]:
    if p.get("is_heading") and p.get("heading_level"):
        lvl = int(p["heading_level"])
        name = f"Heading {min(max(lvl, 1), 9)}"
        try:
            _ = doc.styles[name]
            return name
        except KeyError:
            return None
    style = str(p.get("style") or "").strip()
    if style:
        try:
            _ = doc.styles[style]
            return style
        except KeyError:
            pass
    return None


def _apply_run_format(run: Any, run_data: Dict[str, Any]) -> None:
    style = run_data.get("style") or {}
    if not isinstance(style, dict):
        return
    if style.get("bold"):
        run.bold = True
    if style.get("italic"):
        run.italic = True
    if style.get("underline"):
        run.underline = True
    fn = style.get("font_names") or {}
    if isinstance(fn, dict):
        for key in ("eastAsia", "ascii", "hAnsi"):
            if fn.get(key):
                try:
                    run.font.name = fn[key]
                    break
                except Exception:
                    pass
    half = style.get("font_size_half_pt")
    if half is not None:
        try:
            from docx.shared import Pt
            run.font.size = Pt(int(half) / 2)
        except Exception:
            pass


def _add_paragraph(doc: Any, p: Dict[str, Any]) -> None:
    text = str(p.get("text") or "").strip()
    runs = p.get("runs") or []
    style_name = _style_for_paragraph(doc, p)
    para = doc.add_paragraph(style=style_name) if style_name else doc.add_paragraph()
    list_type = p.get("list_type")
    if list_type in ("numbered", "bullet"):
        try:
            para.style = "List Number" if list_type == "numbered" else "List Bullet"
        except KeyError:
            pass
    if runs:
        for rd in runs:
            if not isinstance(rd, dict):
                continue
            rt = str(rd.get("text") or "")
            if not rt:
                continue
            run = para.add_run(rt)
            _apply_run_format(run, rd)
    elif text:
        para.add_run(text)


def _add_table(doc: Any, tbl: Dict[str, Any]) -> None:
    rows = tbl.get("rows") or []
    if not rows:
        return
    nrows = len(rows)
    ncols = max(len(r) for r in rows)
    if ncols < 1:
        return
    table = doc.add_table(rows=nrows, cols=ncols)
    for ri, row in enumerate(rows):
        for ci in range(ncols):
            val = row[ci] if ci < len(row) else ""
            table.rows[ri].cells[ci].text = str(val or "")


def _build_from_blocks(doc: Any, spec: Dict[str, Any]) -> None:
    blocks = spec.get("blocks") or []
    if blocks:
        for blk in blocks:
            if not isinstance(blk, dict):
                continue
            btype = blk.get("type")
            if btype == "paragraph":
                paras = spec.get("paragraphs") or []
                idx = blk.get("index")
                p = next((x for x in paras if x.get("index") == idx), None)
                if p:
                    _add_paragraph(doc, p)
                elif blk.get("text"):
                    _add_paragraph(doc, blk)
            elif btype == "table":
                tables = spec.get("tables") or []
                ti = blk.get("index")
                t = next((x for x in tables if x.get("index") == ti), None)
                if t:
                    _add_table(doc, t)
        return
    for p in spec.get("paragraphs") or []:
        if isinstance(p, dict):
            _add_paragraph(doc, p)
    for t in spec.get("tables") or []:
        if isinstance(t, dict):
            _add_table(doc, t)


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    suffix = src_path.suffix.lower()
    if suffix not in (".json", ".txt"):
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，支持 .json / .txt")

    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx 未安装，无法生成 Word") from exc

    spec, _warnings = await resolve_word_document_spec(src_path, payload or {}, ctx or {}, rule_spec or {})
    if not (spec.get("paragraphs") or spec.get("blocks") or spec.get("plain_text")):
        raise ValueError("缺少 paragraphs/blocks/plain_text，无法生成 docx")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    docx_path = output_path
    if output_path.suffix.lower() != ".docx":
        docx_path = output_dir / "generated_document.docx"
    rel = str(rule_spec.get("default_output_relpath") or "")
    if rel.endswith(".docx"):
        docx_path = output_dir / Path(rel).name

    tpl = template_path
    if tpl is None or not tpl.is_file():
        tpl_rel = str(rule_spec.get("default_template_relpath") or "")
        if tpl_rel:
            cand = src_path.parent.parent / tpl_rel
            if cand.is_file():
                tpl = cand
        inputs_tpl = src_path.parent / "template.docx"
        if inputs_tpl.is_file():
            tpl = inputs_tpl

    if tpl and tpl.is_file():
        doc = Document(str(tpl))
        body = doc.element.body
        for child in list(body):
            if child.tag.endswith("}sectPr"):
                continue
            body.remove(child)
    else:
        doc = Document()

    _build_from_blocks(doc, spec)
    if not doc.paragraphs and spec.get("plain_text"):
        doc.add_paragraph(str(spec.get("plain_text") or ""))

    doc.save(str(docx_path))

    para_count = len(spec.get("paragraphs") or [])
    table_count = len(spec.get("tables") or [])
    return {
        "output_path": str(docx_path),
        "template_path": str(tpl or ""),
        "paragraph_count": para_count,
        "table_count": table_count,
        "output_schema": list(rule_spec.get("output_schema") or []),
        "source_json": src_path.name,
    }