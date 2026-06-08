"""PPT edit plan schema: structured ops for compose/enhance pipelines."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

PLAN_VERSION = "1"
VALID_MODES = frozenset({"compose", "enhance"})
VALID_OPS = frozenset(
    {
        "set_slide_text",
        "add_picture",
        "layout_pictures_row",
        "set_shape_position",
        "inject_timing",
        "group_shapes",
    }
)
VALID_TIMING_PRESETS = frozenset(
    {
        "marquee_path",
        "homework_marquee",
        "fade_in",
        "fly_from_left",
        "on_click_sequence",
    }
)

ALLOWED_OOXML_TAGS = frozenset(
    {
        "p:timing",
        "p:tnLst",
        "p:par",
        "p:cTn",
        "p:childTnLst",
        "p:seq",
        "p:stCondLst",
        "p:cond",
        "p:tgtEl",
        "p:spTgt",
        "p:endSync",
        "p:rtn",
        "p:nextCondLst",
        "p:animMotion",
        "p:cBhvr",
        "p:attrNameLst",
        "p:attrName",
        "p:grpSp",
        "p:nvGrpSpPr",
        "p:cNvPr",
        "p:cNvGrpSpPr",
        "p:nvPr",
        "p:grpSpPr",
        "p:pic",
        "p:nvPicPr",
        "p:cNvPicPr",
        "p:blipFill",
        "p:spPr",
        "a:off",
        "a:ext",
        "a:xfrm",
        "a:chOff",
        "a:chExt",
        "a:blip",
        "a:stretch",
        "a:fillRect",
        "a:prstGeom",
        "a:avLst",
        "a:picLocks",
    }
)

FORBIDDEN_OOXML_FRAGMENTS = re.compile(
    r"<script|javascript:|externalData|vbaProject|macro",
    re.I,
)


def empty_plan(*, mode: str = "compose", title: str = "演示文稿") -> Dict[str, Any]:
    return {
        "version": PLAN_VERSION,
        "mode": mode,
        "title": title,
        "slides": [],
        "ops": [],
        "meta": {},
    }


def _as_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _validate_slide_spec(raw: Any, idx: int, errors: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        errors.append(f"slides[{idx}] 必须为对象")
        return None
    bullets_in = raw.get("bullets")
    bullets: List[str] = []
    if isinstance(bullets_in, list):
        bullets = [str(b).strip()[:200] for b in bullets_in if str(b).strip()]
    images_in = raw.get("images")
    images: List[Dict[str, Any]] = []
    if isinstance(images_in, list):
        for j, img in enumerate(images_in):
            if not isinstance(img, dict):
                continue
            ref = str(img.get("image_ref") or img.get("ref") or "").strip()
            path = str(img.get("path") or img.get("file") or "").strip()
            if not ref and not path:
                errors.append(f"slides[{idx}].images[{j}] 需要 image_ref 或 path")
                continue
            images.append(
                {
                    "logical_id": str(img.get("logical_id") or f"img{j + 1}")[:40],
                    "image_ref": ref,
                    "path": path,
                }
            )
    return {
        "index": _as_int(raw.get("index"), idx + 1),
        "title": str(raw.get("title") or f"第 {idx + 1} 页")[:120],
        "bullets": bullets[:12],
        "notes": str(raw.get("notes") or raw.get("notes_generated") or "")[:8000],
        "images": images,
    }


def _validate_op(raw: Any, idx: int, errors: List[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        errors.append(f"ops[{idx}] 必须为对象")
        return None
    op = str(raw.get("op") or "").strip()
    if op not in VALID_OPS:
        errors.append(f"ops[{idx}].op 无效：{op}")
        return None
    out: Dict[str, Any] = {"op": op}
    slide = raw.get("slide")
    if slide is not None:
        out["slide"] = _as_int(slide, 1)
    if op == "set_slide_text":
        out["title"] = str(raw.get("title") or "")[:120]
        bl = raw.get("bullets")
        out["bullets"] = [str(b)[:200] for b in bl][:12] if isinstance(bl, list) else []
    elif op == "add_picture":
        out["logical_id"] = str(raw.get("logical_id") or raw.get("shape_id") or "")[:40]
        out["image_ref"] = str(raw.get("image_ref") or "").strip()
        out["path"] = str(raw.get("path") or "").strip()
        if not out["image_ref"] and not out["path"]:
            errors.append(f"ops[{idx}] add_picture 需要 image_ref 或 path")
    elif op == "layout_pictures_row":
        ids = raw.get("logical_ids") or raw.get("shape_ids")
        out["logical_ids"] = [str(x)[:40] for x in ids][:20] if isinstance(ids, list) else []
        out["y_emu"] = _as_int(raw.get("y_emu"), 2_667_000)
    elif op == "set_shape_position":
        out["logical_id"] = str(raw.get("logical_id") or "")[:40]
        for k in ("x_emu", "y_emu", "cx_emu", "cy_emu"):
            if raw.get(k) is not None:
                out[k] = _as_int(raw.get(k))
    elif op == "inject_timing":
        preset = str(raw.get("preset") or "").strip()
        fragment = str(raw.get("ooxml_fragment") or "").strip()
        if preset:
            if preset not in VALID_TIMING_PRESETS:
                errors.append(f"ops[{idx}] 未知 preset：{preset}")
            out["preset"] = preset
        elif fragment:
            frag_err = validate_ooxml_fragment(fragment)
            if frag_err:
                errors.append(f"ops[{idx}] ooxml_fragment：{frag_err}")
            out["ooxml_fragment"] = fragment
        else:
            errors.append(f"ops[{idx}] inject_timing 需要 preset 或 ooxml_fragment")
        out["click_shape_id"] = str(
            raw.get("click_shape_id") or raw.get("click_logical_id") or "play_button"
        )[:40]
        out["target_shape_id"] = str(
            raw.get("target_shape_id") or raw.get("target_logical_id") or "marquee_strip"
        )[:40]
    elif op == "group_shapes":
        ids = raw.get("logical_ids") or raw.get("shape_ids")
        out["logical_ids"] = [str(x)[:40] for x in ids][:30] if isinstance(ids, list) else []
        out["group_logical_id"] = str(raw.get("group_logical_id") or "marquee_strip")[:40]
    return out


def validate_ooxml_fragment(fragment: str) -> Optional[str]:
    text = (fragment or "").strip()
    if not text:
        return "片段为空"
    if FORBIDDEN_OOXML_FRAGMENTS.search(text):
        return "包含禁止内容"
    if "<" not in text:
        return "非 XML"
    tags = re.findall(r"</?([a-zA-Z0-9:]+)", text)
    for tag in tags:
        if tag and tag not in ALLOWED_OOXML_TAGS and not tag.startswith("a:"):
            if tag not in ("root", "xml"):
                return f"不允许的标签：{tag}"
    return None


def validate_edit_plan(raw: Any) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    if not isinstance(raw, dict):
        return empty_plan(), ["plan 根节点必须为对象"]
    mode = str(raw.get("mode") or "compose").strip().lower()
    if mode not in VALID_MODES:
        errors.append(f"mode 无效：{mode}")
        mode = "compose"
    title = str(raw.get("title") or "演示文稿")[:120]
    slides_out: List[Dict[str, Any]] = []
    slides_in = raw.get("slides")
    if isinstance(slides_in, list):
        for i, s in enumerate(slides_in[:30]):
            norm = _validate_slide_spec(s, i, errors)
            if norm:
                slides_out.append(norm)
    ops_out: List[Dict[str, Any]] = []
    ops_in = raw.get("ops")
    if isinstance(ops_in, list):
        for i, op in enumerate(ops_in[:80]):
            norm = _validate_op(op, i, errors)
            if norm:
                ops_out.append(norm)
    plan = {
        "version": str(raw.get("version") or PLAN_VERSION),
        "mode": mode,
        "title": title,
        "slides": slides_out,
        "ops": ops_out,
        "meta": raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
    }
    recipe = str(raw.get("recipe") or "").strip()
    if recipe:
        plan["recipe"] = recipe[:60]
    return plan, errors


def parse_edit_plan_json(text: str) -> Tuple[Dict[str, Any], List[str]]:
    raw = (text or "").strip()
    if not raw:
        return empty_plan(), ["plan JSON 为空"]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return empty_plan(), [f"JSON 解析失败：{exc}"]
    if (
        isinstance(data, dict)
        and "ppt_edit_plan" in data
        and isinstance(data["ppt_edit_plan"], dict)
    ):
        data = data["ppt_edit_plan"]
    return validate_edit_plan(data)


def plan_from_presentation(table: Dict[str, Any], *, mode: str = "compose") -> Dict[str, Any]:
    """Heuristic plan from presentation_full v1/v2 without LLM."""
    title = str(table.get("title") or "演示文稿")[:120]
    slides_out: List[Dict[str, Any]] = []
    slides_in = table.get("slides") if isinstance(table.get("slides"), list) else []
    for i, raw in enumerate(slides_in[:30]):
        if not isinstance(raw, dict):
            continue
        bullets = raw.get("bullets") if isinstance(raw.get("bullets"), list) else []
        images: List[Dict[str, Any]] = []
        for img in raw.get("images") or []:
            if not isinstance(img, dict):
                continue
            rel = str(img.get("relpath") or img.get("path") or "").strip()
            if rel:
                images.append(
                    {
                        "logical_id": str(
                            img.get("id") or img.get("logical_id") or f"img{len(images)+1}"
                        ),
                        "image_ref": rel,
                        "path": rel,
                    }
                )
        slides_out.append(
            {
                "index": int(raw.get("index") or i + 1),
                "title": str(raw.get("title") or f"第 {i + 1} 页")[:120],
                "bullets": [str(b)[:200] for b in bullets[:12]],
                "notes": str(raw.get("notes_generated") or raw.get("notes") or "")[:8000],
                "images": images,
            }
        )
    if not slides_out:
        slides_out = [
            {"index": 1, "title": title, "bullets": ["暂无内容"], "images": [], "notes": ""}
        ]
    ops: List[Dict[str, Any]] = []
    for s in slides_out:
        ops.append(
            {
                "op": "set_slide_text",
                "slide": s["index"],
                "title": s["title"],
                "bullets": s["bullets"],
            }
        )
    return {
        "version": PLAN_VERSION,
        "mode": mode,
        "title": title,
        "slides": slides_out,
        "ops": ops,
        "meta": {"source": "presentation_full"},
    }
