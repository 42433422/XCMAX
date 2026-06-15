from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.ppt_generate_pipeline import run_ppt_generate


async def convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    return await run_ppt_generate(
        src_path,
        output_path,
        template_path=template_path,
        payload=payload or {},
        ctx=ctx or {},
        rule_spec=rule_spec or {},
    )


async def _legacy_convert_file(
    src_path: Path,
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    from modstore_server.office_plaintext_generate import resolve_presentation_spec

    table, _warnings = await resolve_presentation_spec(src_path, payload or {}, ctx or {}, rule_spec or {})
    slides = table.get("slides") if isinstance(table.get("slides"), list) else []
    if not slides:
        raise ValueError("JSON 中 slides 为空，无法生成 PPT")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = output_dir / "output.pptx"
    if output_path.suffix.lower() == ".pptx":
        pptx_path = output_path
    elif str(rule_spec.get("default_output_relpath") or "").endswith(".pptx"):
        pptx_path = output_dir / Path(str(rule_spec.get("default_output_relpath"))).name

    blob: bytes
    try:
        from modstore_server.pptx_export import build_pptx_from_presentation_json

        blob = build_pptx_from_presentation_json(table)
    except ImportError:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.util import Inches, Pt

        prs = Presentation()
        for raw in slides:
            if not isinstance(raw, dict):
                continue
            layout = prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0]
            slide = prs.slides.add_slide(layout)
            title = str(raw.get("title") or "")
            if slide.shapes.title:
                slide.shapes.title.text = title[:120]
            body = slide.placeholders[1] if len(slide.placeholders) > 1 else None
            if body and body.has_text_frame:
                tf = body.text_frame
                tf.clear()
                bullets = raw.get("bullets") if isinstance(raw.get("bullets"), list) else []
                for i, b in enumerate(bullets[:8]):
                    p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    p.text = str(b)[:180]
            notes = str(raw.get("notes_generated") or raw.get("notes") or "").strip()
            if notes:
                try:
                    slide.notes_slide.notes_text_frame.text = notes[:8000]
                except Exception:
                    pass
        import io

        bio = io.BytesIO()
        prs.save(bio)
        blob = bio.getvalue()

    pptx_path.write_bytes(blob)

    return {
        "output_path": str(pptx_path),
        "slide_count": len(slides),
        "title": str(table.get("title") or ""),
        "output_schema": list(rule_spec.get("output_schema") or []),
    }