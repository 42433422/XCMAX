from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    except Exception:
        return ""


def _extract_pptx(src_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

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
                    images_raw.append({
                        "id": f"s{slide_idx}_img{img_seq}",
                        "slide": slide_idx,
                        "category": category,
                        "bytes": blob,
                        "ext": ext,
                    })
                except Exception:
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
        except Exception:
            notes_existing = ""
        slides_out.append({
            "index": slide_idx,
            "title": slide_title,
            "bullets": bullets[:12],
            "body_text": "\n".join(texts),
            "notes_existing": notes_existing,
            "notes_generated": "",
            "images": [],
        })

    outline = [{"level": 1, "text": s["title"], "slide_index": s["index"]} for s in slides_out if s.get("title")]
    payload = {
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
        catalog.append({
            "id": img.get("id"),
            "slide": img.get("slide"),
            "category": category,
            "relpath": str(out_path.relative_to(images_root.parent)).replace("\\", "/"),
        })
    return catalog


async def _vlm_describe_image(
    img_path: Path,
    ctx: Dict[str, Any],
    *,
    slide: int,
    category: str,
) -> Optional[Dict[str, Any]]:
    call_llm = ctx.get("call_llm")
    if not callable(call_llm):
        return None
    try:
        raw = img_path.read_bytes()
    except OSError:
        return None
    b64 = base64.b64encode(raw).decode("ascii")
    ext = img_path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext if ext in ("png", "gif", "webp") else "png"
    url = f"data:image/{mime};base64,{b64}"
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"这是 PPT 第 {slide} 页嵌入的图片（分类：{category}）。"
                        "请用中文简要描述图中文字与关键信息，输出 JSON："
                        '{"description":"","detected_text":"","tags":[]}'
                    ),
                },
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]
    try:
        res = await asyncio.wait_for(call_llm(messages, max_tokens=600, temperature=0.1), timeout=90.0)
    except Exception:
        return None
    if not isinstance(res, dict) or not res.get("ok"):
        return None
    content = str(res.get("content") or "").strip()
    sidecar = {"description": content[:2000], "vlm_ok": True}
    try:
        if "{" in content:
            parsed = json.loads(content[content.index("{") : content.rindex("}") + 1])
            if isinstance(parsed, dict):
                sidecar = {**sidecar, **parsed}
    except (json.JSONDecodeError, ValueError):
        pass
    return sidecar


async def _generate_speaker_note(
    slide: Dict[str, Any],
    ctx: Dict[str, Any],
    *,
    deck_title: str,
    vlm_summaries: List[str],
) -> str:
    call_llm = ctx.get("call_llm")
    if not callable(call_llm):
        return ""
    title = str(slide.get("title") or "")
    bullets = slide.get("bullets") if isinstance(slide.get("bullets"), list) else []
    bullets_txt = "\n".join(f"- {b}" for b in bullets[:10])
    notes_existing = str(slide.get("notes_existing") or "").strip()
    vlm_txt = "\n".join(vlm_summaries[:5])
    user_msg = (
        f"{_SPEAKER_NOTES_PROMPT}\n\n"
        f"演示标题：{deck_title}\n"
        f"当前页：第 {slide.get('index')} 页\n"
        f"页标题：{title}\n"
        f"正文要点：\n{bullets_txt or '(无)'}\n"
    )
    if notes_existing:
        user_msg += f"\n已有备注（可参考，勿照抄）：\n{notes_existing[:1500]}\n"
    if vlm_txt:
        user_msg += f"\n图片识别摘要：\n{vlm_txt}\n"
    user_msg += "\n请只输出本页演讲备注正文（中文，200-400字），不要 JSON，不要编造幻灯片上没有的信息。"
    messages = [
        {"role": "system", "content": "你是专业的演示文稿演讲稿撰写助手。"},
        {"role": "user", "content": user_msg},
    ]
    try:
        res = await asyncio.wait_for(call_llm(messages, max_tokens=800, temperature=0.3), timeout=120.0)
    except Exception:
        return ""
    if not isinstance(res, dict) or not res.get("ok"):
        return ""
    return str(res.get("content") or "").strip()[:4000]


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
    except Exception as exc:
        raise ValueError(f"PPT 解析失败：{exc}") from exc

    catalog = _write_image_files(images_raw, images_root)
    slide_vlm: Dict[int, List[str]] = {}
    for entry in catalog:
        rel = str(entry.get("relpath") or "")
        img_abs = images_root.parent / rel if rel else None
        if not img_abs or not img_abs.is_file():
            continue
        sidecar = await _vlm_describe_image(
            img_abs,
            ctx,
            slide=int(entry.get("slide") or 0),
            category=str(entry.get("category") or "uncategorized"),
        )
        if sidecar:
            sidecar_path = img_abs.with_suffix(img_abs.suffix + ".vlm.json")
            sidecar_path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
            entry["vlm_sidecar"] = str(sidecar_path.relative_to(output_dir)).replace("\\", "/")
            desc = str(sidecar.get("description") or sidecar.get("detected_text") or "")[:500]
            slide_no = int(entry.get("slide") or 0)
            slide_vlm.setdefault(slide_no, []).append(desc)
        else:
            warnings.append(f"图片 {entry.get('id')} 未获得 VLM 描述")

    images_index_path = output_dir / "images_index.json"
    images_index = {"images": catalog, "categories": list(_CATEGORY_DIRS), "vlm_count": sum(1 for i in catalog if i.get("vlm_sidecar"))}
    images_index_path.write_text(json.dumps(images_index, ensure_ascii=False, indent=2), encoding="utf-8")

    deck_title = str(presentation.get("title") or src_path.stem)
    notes_lines: List[str] = [f"# {deck_title}", ""]
    for slide in presentation.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        idx = int(slide.get("index") or 0)
        vlm_hints = slide_vlm.get(idx, [])
        generated = await _generate_speaker_note(slide, ctx, deck_title=deck_title, vlm_summaries=vlm_hints)
        if generated:
            slide["notes_generated"] = generated
        elif not ctx.get("call_llm"):
            warnings.append(f"第 {idx} 页：ctx.call_llm 不可用，未生成演讲备注")
        slide_images = [e for e in catalog if int(e.get("slide") or 0) == idx]
        slide["images"] = slide_images
        notes_lines.append(f"## 第 {idx} 页 · {slide.get('title') or ''}")
        if slide.get("notes_existing"):
            notes_lines.append(f"**已有备注：** {slide['notes_existing'][:500]}")
        notes_lines.append(str(slide.get("notes_generated") or slide.get("notes_existing") or "（未生成）"))
        notes_lines.append("")

    from modstore_server.ppt_read_shapes import enrich_presentation_v2

    presentation = enrich_presentation_v2(presentation, src_path)

    json_path.write_text(json.dumps(presentation, ensure_ascii=False, indent=2), encoding="utf-8")
    notes_md_path.write_text("\n".join(notes_lines), encoding="utf-8")

    meta = {
        "title": deck_title,
        "slide_count": presentation.get("slide_count"),
        "source": src_path.name,
        "image_count": len(catalog),
        "speaker_notes_prompt": _SPEAKER_NOTES_PROMPT,
        "images_index": str(images_index_path.name),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "output_path": str(json_path),
        "meta_output_path": str(meta_path),
        "notes_output_path": str(notes_md_path),
        "images_index_path": str(images_index_path),
        "slide_count": presentation.get("slide_count", 0),
        "image_count": len(catalog),
        "warnings": warnings,
        "output_schema": list(rule_spec.get("output_schema") or []),
    }