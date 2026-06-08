"""PPT 全量读取与 PPT 生成员工：检测、规则、兜底 convert 与包体验证。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

PPT_DOC_KEYWORDS = (
    ".pptx",
    ".ppt",
    "pptx",
    "ppt",
    "powerpoint",
    "演示文稿",
    "幻灯片",
    "presentation",
)
PPT_READ_ACTION_KEYWORDS = (
    "读取",
    "读出",
    "全量",
    "读入",
    "read",
    "load",
    "提取",
    "解析",
    "演讲",
    "备注",
    "备注稿",
    "大纲",
    "vlm",
    "识图",
)
PPT_GENERATE_ACTION_KEYWORDS = (
    "生成",
    "写入",
    "写 ppt",
    "写ppt",
    "输出",
    "改写",
    "write",
    "generate",
    "json",
    "结构化",
    "中介",
    "制作",
)
PPT_READ_EXCLUDE = (
    "生成 ppt",
    "写 ppt",
    "写ppt",
    "json 中介生成",
    "写出 output.pptx",
)
PPT_GENERATE_EXCLUDE = (
    "仅读取",
    "只读",
    "原样",
    "不要生成",
    "read only",
    "全量读取",
    "演讲备注生成",
)

PPT_READ_OUTPUT_FIELDS = (
    "title",
    "slide_count",
    "outline",
    "slides",
    "images",
    "notes_generated",
    "source",
)
PPT_GENERATE_OUTPUT_FIELDS = (
    "title",
    "slides",
    "slide_count",
    "stats",
    "metadata",
)

IMAGE_CATEGORY_DIRS = ("figures", "photos", "diagrams", "icons", "uncategorized")

SPEAKER_NOTES_PROMPT = "为这份PPT生成每页的演讲备注"


def _brief_lower(brief: str) -> str:
    return (brief or "").lower()


def _has_ppt_doc_signal(bl: str) -> bool:
    return any(k in bl for k in PPT_DOC_KEYWORDS)


def is_ppt_generate(brief: str) -> bool:
    """上传 JSON（presentation_full 同 schema）→ 写出 output.pptx。"""
    bl = _brief_lower(brief)
    if not _has_ppt_doc_signal(bl):
        return False
    if any(k in bl for k in PPT_GENERATE_EXCLUDE) and not any(
        k in bl for k in PPT_GENERATE_ACTION_KEYWORDS
    ):
        return False
    if any(k in bl for k in PPT_READ_EXCLUDE):
        return False
    return any(k in bl for k in PPT_GENERATE_ACTION_KEYWORDS)


def is_ppt_full_read(brief: str) -> bool:
    """PPT 全量读取：大纲、每页正文、图片 VLM、演讲备注。"""
    if is_ppt_generate(brief):
        return False
    bl = _brief_lower(brief)
    if not _has_ppt_doc_signal(bl):
        return False
    return any(k in bl for k in PPT_READ_ACTION_KEYWORDS)


def ppt_read_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / PPT 全量读取",
        "goal": (brief or "").strip().splitlines()[0][:200] or "上传 PPT，全量解析并生成演讲备注",
        "input": "用户上传的 .pptx 文件",
        "output": "outputs/presentation_full.json + speaker_notes.md + outputs/images/",
        "output_schema": {
            "fields": list(PPT_READ_OUTPUT_FIELDS),
            "json_file": "outputs/presentation_full.json",
            "meta_file": "outputs/presentation_meta.json",
            "notes_file": "outputs/speaker_notes.md",
            "images_index": "outputs/images_index.json",
            "images_dir": "outputs/images/",
        },
        "constraints": [
            "幻灯片正文必须来自 python-pptx 真实解析，禁止 LLM 编造正文",
            "图片须导出并由 VLM（可用时）生成 sidecar",
            f"演讲备注由 LLM 基于真实页内容生成，提示词：{SPEAKER_NOTES_PROMPT}",
            "handlers 必须为 direct_python",
        ],
        "suggested_capabilities": ["ppt.parse", "ppt.notes_generate", "vision.vlm"],
        "suggested_handlers": ["direct_python"],
    }


def ppt_generate_structured_spec(brief: str) -> Dict[str, Any]:
    return {
        "domain": "文档处理 / PPT 生成",
        "goal": (brief or "").strip().splitlines()[0][:200] or "LLM 编排 + OOXML 写出 output.pptx",
        "input": "presentation_full v2 JSON / user_query / .txt；可选 template .pptx（execute-file template_file）",
        "output": "outputs/output.pptx + outputs/ppt_edit_plan.json",
        "output_schema": {
            "fields": list(PPT_GENERATE_OUTPUT_FIELDS),
            "pptx_file": "outputs/output.pptx",
            "plan_file": "outputs/ppt_edit_plan.json",
        },
        "constraints": [
            "compose-first：无模板时从零合成多页 pptx",
            "enhance：复制 template 后按 ppt_edit_plan 注入动画（OOXML）",
            "禁止仅输出纯文字幻灯片冒充带动效/带图作业",
            "作业跑马灯可走 homework_marquee 确定性配方",
        ],
        "suggested_capabilities": ["ppt.write", "ppt.ooxml", "data.json_read", "llm.plan"],
        "suggested_handlers": ["direct_python", "agent"],
    }


def build_ppt_read_rule_spec(brief: str) -> Dict[str, Any]:
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".pptx"],
        "default_action": "convert",
        "default_output_relpath": "outputs/presentation_full.json",
        "default_meta_relpath": "outputs/presentation_meta.json",
        "default_images_dir": "outputs/images",
        "default_notes_relpath": "outputs/speaker_notes.md",
        "runtime_kind": "ppt_full_read",
        "speaker_notes_prompt": SPEAKER_NOTES_PROMPT,
        "output_schema": list(PPT_READ_OUTPUT_FIELDS),
        "requirements": [
            'Use direct_python only; handlers must be ["direct_python"].',
            "Parse pptx with python-pptx; never use LLM for slide body text.",
            "Export embedded images to outputs/images/<category>/.",
            "When ctx.call_llm supports vision, describe each image to .vlm.json sidecar.",
            f"Generate per-slide speaker notes via ctx.call_llm text with prompt: {SPEAKER_NOTES_PROMPT}",
            "Write presentation_full.json, presentation_meta.json, speaker_notes.md, images_index.json.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def build_ppt_generate_rule_spec(brief: str) -> Dict[str, Any]:
    bl = _brief_lower(brief)
    wants_polish = any(k in bl for k in ("润色", "改写", "polish", "rewrite"))
    return {
        "brief": brief,
        "mode": "direct_python_file_transform",
        "accepted_extensions": [".json", ".txt"],
        "default_action": "convert",
        "default_output_relpath": "outputs/output.pptx",
        "runtime_kind": "ppt_generate",
        "optional_llm_polish": wants_polish,
        "output_schema": list(PPT_GENERATE_OUTPUT_FIELDS),
        "requirements": [
            'handlers must include "direct_python"; may include "agent" for optional polish.',
            "Run modstore_server.ppt_generate_pipeline.run_ppt_generate: route → plan → compose/enhance → OOXML.",
            "When template_path is .pptx, copy template; else compose deck from plan slides.",
            "LLM planner outputs ppt_edit_plan.json; executor applies inject_timing presets.",
            "Never fabricate slides when input is empty; fallback to text-only only with warnings.",
            "Return {ok, summary, items, warnings, error, meta}.",
        ],
    }


def render_ppt_read_convert_module() -> str:
    return r"""from __future__ import annotations

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
"""


def render_ppt_generate_convert_module() -> str:
    return r"""from __future__ import annotations

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
"""


def validate_ppt_read_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_ppt_backend(
        pack_dir,
        runtime_kind="ppt_full_read",
        required_tokens=("presentation_full", "speaker_notes", ".pptx"),
    )


def validate_ppt_generate_backend(pack_dir: Path) -> Tuple[List[str], List[str]]:
    return _validate_ppt_backend(
        pack_dir,
        runtime_kind="ppt_generate",
        required_tokens=("output.pptx", "presentation"),
    )


def _validate_ppt_backend(
    pack_dir: Path,
    *,
    runtime_kind: str,
    required_tokens: tuple[str, ...],
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    backend = pack_dir / "backend"
    if not backend.is_dir():
        errors.append("缺少 backend 目录")
        return errors, warnings

    py_blob = ""
    has_convert = False
    for py_path in backend.rglob("*.py"):
        try:
            text = py_path.read_text(encoding="utf-8", errors="ignore")
            py_blob += text.lower()
            if "def convert_file" in text and "vendor" in str(py_path).lower():
                has_convert = True
        except OSError:
            pass

    mf_path = pack_dir / "manifest.json"
    handlers: List[str] = []
    if mf_path.is_file():
        try:
            from modstore_server.employee_asset_pipeline import manifest_actions_handlers

            mf = json.loads(mf_path.read_text(encoding="utf-8"))
            handlers = manifest_actions_handlers(mf)
        except (json.JSONDecodeError, OSError):
            warnings.append("manifest.json 无法解析")

    if handlers and "direct_python" not in handlers:
        errors.append(f"{runtime_kind} 员工 handlers 必须包含 direct_python")
    if not has_convert:
        errors.append("backend/vendor 中缺少 convert_file 实现")
    if "pptx" not in py_blob and "presentation" not in py_blob:
        warnings.append("未发现 PPT 解析相关代码")
    for tok in required_tokens:
        if tok.lower() not in py_blob:
            warnings.append(f"convert 模块可能未覆盖：{tok}")

    return errors, warnings


def minimal_pptx_fixture_bytes() -> bytes:
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "PPT 冒烟测试"
        body = slide.placeholders[1]
        body.text_frame.text = "要点一\n要点二"
        import io

        bio = io.BytesIO()
        prs.save(bio)
        return bio.getvalue()
    except Exception:
        return b""


def ppt_read_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "PPT 全量读取员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python：读取 inputs/ 中 .pptx，解析每页正文与大纲，"
        "导出图片并 VLM 描述，按「为这份PPT生成每页的演讲备注」生成 notes_generated，"
        "写入 outputs/presentation_full.json 与 speaker_notes.md。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n"
            "员工必须使用 direct_python：正文仅来自 pptx 解析；图片走 VLM；演讲备注基于真实内容生成。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": "只能读 inputs/、写 outputs/；VLM/备注通过 ctx.call_llm。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{merged or clean}\n\nSkill：上传 pptx → JSON 中介 + 演讲备注 + 图片 VLM。",
        "acceptance": [
            "handlers 为 direct_python",
            "presentation_full.json 含 slides/outline",
            "speaker_notes.md 含每页备注",
        ],
    }


def ppt_generate_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from modstore_server.employee_brief_utils import compact_routing_brief

    checklist = payload.get("execution_checklist")
    checklist_text = (
        "\n".join(f"- {x}" for x in checklist if isinstance(x, str))
        if isinstance(checklist, list)
        else ""
    )
    clean = compact_routing_brief(brief, max_len=400) or (brief or "").strip()
    merged = "\n".join(x for x in [clean, checklist_text] if x).strip()
    short = "PPT 生成员"
    script_brief = (
        f"{merged or clean}\n\n"
        "请生成 Python：读取 inputs/ .json（presentation_full schema）→ 写出 outputs/output.pptx。"
    )
    return {
        "employee_name": short,
        "employee_brief": (
            f"{merged or clean}\n\n" "JSON 为中介；direct_python 写 pptx；禁止无输入编造幻灯片。"
        ),
        "script_workflow_name": f"{short} 脚本工作流",
        "script_brief": script_brief,
        "script_runtime_notes": "direct_python 读 JSON 写 pptx。",
        "workflow_name": str(payload.get("employee_workflow_name") or short).strip() or short,
        "workflow_brief": f"{merged or clean}\n\nSkill：JSON → output.pptx。",
        "acceptance": [
            "输出 output.pptx",
            "handlers 含 direct_python",
        ],
    }


def resolve_ppt_orchestration_plan(brief: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if is_ppt_generate(brief):
        return ppt_generate_orchestration_plan(brief, payload)
    return ppt_read_orchestration_plan(brief, payload)
