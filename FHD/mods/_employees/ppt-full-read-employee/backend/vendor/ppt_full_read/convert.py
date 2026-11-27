from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.mod_sdk.errors import RECOVERABLE_ERRORS

_CATEGORY_DIRS = ("figures", "photos", "diagrams", "icons", "uncategorized")
_SPEAKER_NOTES_PROMPT = "为这份PPT生成每页的演讲备注"


def _classify_image(width: int, height: int, area: int) -> str:
    if width <= 0 or height <= 0:
        return "uncategorized"
    aspect = width / max(height, 1)
    if area < 8000 or max(width, height) < 48:
        return "icons"
    if 0.85 <= aspect <= 1.18 and area >= 40000:
        return "photos"
    if aspect >= 1.35 or aspect <= 0.72:
        return "diagrams"
    return "figures"


def _shape_text(shape: Any) -> str:
    if not getattr(shape, "has_text_frame", False):
        return ""
    try:
        lines = []
        for para in shape.text_frame.paragraphs:
            t = (para.text or "").strip()
            if t:
                lines.append(t)
        return "\n".join(lines)
    except RECOVERABLE_ERRORS:
        return ""


def _extract_pptx(src_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    from app.mod_sdk.host_services import read_native_document

    document_facts = read_native_document(src_path)
    prs = Presentation(str(src_path))
    title_guess = ""
    slides_out: List[Dict[str, Any]] = []
    images_raw: List[Dict[str, Any]] = []
    img_seq = 0

    for slide_idx, slide in enumerate(prs.slides, start=1):
        texts: List[str] = []
        bullets: List[str] = []
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    img = shape.image
                    blob = img.blob
                    ext = (img.ext or "png").lstrip(".")
                    w = int(getattr(shape, "width", 0) or 0)
                    h = int(getattr(shape, "height", 0) or 0)
                    area = max(1, w * h // 914400)
                    category = _classify_image(max(1, w // 914400), max(1, h // 914400), area)
                    img_seq += 1
                    images_raw.append(
                        {
                            "id": f"s{slide_idx}_img{img_seq}",
                            "slide": slide_idx,
                            "category": category,
                            "bytes": blob,
                            "ext": ext,
                        }
                    )
                except RECOVERABLE_ERRORS:
                    continue
                continue
            t = _shape_text(shape).strip()
            if t:
                texts.append(t)
        slide_title = texts[0][:120] if texts else f"第 {slide_idx} 页"
        if slide_idx == 1 and slide_title and not title_guess:
            title_guess = slide_title
        for line in texts[1:]:
            for part in line.split("\n"):
                p = part.strip()
                if p and p not in bullets:
                    bullets.append(p[:200])
        notes_existing = ""
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                notes_existing = (slide.notes_slide.notes_text_frame.text or "").strip()
        except RECOVERABLE_ERRORS:
            notes_existing = ""
        slides_out.append(
            {
                "index": slide_idx,
                "title": slide_title,
                "bullets": bullets[:12],
                "body_text": "\n".join(texts),
                "notes_existing": notes_existing,
                "notes_generated": "",
                "images": [],
            }
        )

    outline = [
        {"level": 1, "text": s["title"], "slide_index": s["index"]}
        for s in slides_out
        if s.get("title")
    ]
    payload = {
        "document_facts": document_facts,
        "title": title_guess or src_path.stem,
        "slide_count": len(slides_out),
        "outline": outline,
        "slides": slides_out,
        "source": src_path.name,
    }
    return payload, images_raw


def _write_image_files(images: List[Dict[str, Any]], images_root: Path) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for img in images:
        category = str(img.get("category") or "uncategorized")
        if category not in _CATEGORY_DIRS:
            category = "uncategorized"
        sub = images_root / category
        sub.mkdir(parents=True, exist_ok=True)
        ext = str(img.get("ext") or "png").lstrip(".")
        fname = f"{img.get('id') or 'img'}.{ext}"
        out_path = sub / fname
        out_path.write_bytes(img.get("bytes") or b"")
        catalog.append(
            {
                "id": img.get("id"),
                "slide": img.get("slide"),
                "category": category,
                "relpath": str(out_path.relative_to(images_root.parent)).replace("\\", "/"),
            }
        )
    return catalog


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
    if suffix not in {".pptx", ".ppt"}:
        raise ValueError(f"不支持的文件类型：{suffix or '(无后缀)'}，仅支持 .pptx")

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "presentation_full.json"
    if output_path.suffix.lower() == ".json":
        json_path = output_path
    meta_path = output_dir / "presentation_meta.json"
    notes_md_path = output_dir / "speaker_notes.md"
    images_root = output_dir / "images"

    warnings: List[str] = []
    try:
        presentation, images_raw = _extract_pptx(src_path)
    except RECOVERABLE_ERRORS as exc:
        raise ValueError(f"PPT 解析失败：{exc}") from exc

    catalog = _write_image_files(images_raw, images_root)
    # File access and a callable LLM do not authorize sending images or notes.
    # Preserve the source and explicitly report the unavailable enrichment.
    image_semantics = {
        "status": "blocked" if catalog else "not_applicable",
        "reason": "model_content_egress_not_authorized" if catalog else "no_embedded_images",
    }
    notes_generation = {"status": "blocked", "reason": "model_content_egress_not_authorized"}
    status = presentation["document_facts"]["status"]
    if status == "complete":
        status = "partial"
    presentation.update(
        status=status, image_semantics=image_semantics, notes_generation=notes_generation
    )
    warnings.append("未取得文档内容外发授权，未生成演讲备注；原有备注已保留。")
    if catalog:
        warnings.append("未生成图片语义描述；原始图片已保留。")

    images_index_path = output_dir / "images_index.json"
    images_index = {
        "images": catalog,
        "categories": list(_CATEGORY_DIRS),
        "vlm_count": 0,
        "image_semantics": image_semantics,
    }
    images_index_path.write_text(
        json.dumps(images_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    deck_title = str(presentation.get("title") or src_path.stem)
    notes_lines: List[str] = [f"# {deck_title}", ""]
    for slide in presentation.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        idx = int(slide.get("index") or 0)
        slide_images = [e for e in catalog if int(e.get("slide") or 0) == idx]
        slide["images"] = slide_images
        notes_lines.append(f"## 第 {idx} 页 · {slide.get('title') or ''}")
        if slide.get("notes_existing"):
            notes_lines.append(f"**已有备注：** {slide['notes_existing'][:500]}")
        notes_lines.append(
            str(slide.get("notes_generated") or slide.get("notes_existing") or "（未生成）")
        )
        notes_lines.append("")

    try:
        from modstore_server.ppt_read_shapes import enrich_presentation_v2
    except ImportError:
        # The bundled desktop must remain readable without MODstore's server
        # source tree.  Core slide extraction above is already complete; keep
        # the v2 envelope and mark advanced shape/timing enrichment unavailable.
        presentation = dict(presentation or {})
        presentation.setdefault("schema_version", 2)
        presentation.setdefault("has_timing", False)
        presentation.setdefault("animation_hints", [])
    else:
        presentation = enrich_presentation_v2(presentation, src_path)

    json_path.write_text(json.dumps(presentation, ensure_ascii=False, indent=2), encoding="utf-8")
    notes_md_path.write_text("\n".join(notes_lines), encoding="utf-8")

    meta = {
        "status": status,
        "image_semantics": image_semantics,
        "notes_generation": notes_generation,
        "title": deck_title,
        "slide_count": presentation.get("slide_count"),
        "source": src_path.name,
        "image_count": len(catalog),
        "speaker_notes_prompt": _SPEAKER_NOTES_PROMPT,
        "images_index": str(images_index_path.name),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": status,
        "image_semantics": image_semantics,
        "notes_generation": notes_generation,
        "output_path": str(json_path),
        "meta_output_path": str(meta_path),
        "notes_output_path": str(notes_md_path),
        "images_index_path": str(images_index_path),
        "slide_count": presentation.get("slide_count", 0),
        "image_count": len(catalog),
        "warnings": warnings,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
