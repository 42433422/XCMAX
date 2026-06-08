"""LLM planner for ppt_edit_plan.json."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.ppt_edit_plan import (
    empty_plan,
    parse_edit_plan_json,
    plan_from_presentation,
    validate_edit_plan,
)

PLANNER_SYSTEM = """你是 PPT 编排助手。根据用户需求输出严格 JSON（不要 markdown 代码块），格式：
{
  "version": "1",
  "mode": "compose" | "enhance",
  "title": "演示标题",
  "slides": [
    {"index": 1, "title": "页标题", "bullets": ["要点1"], "images": [{"logical_id":"img1","image_ref":"outputs/images/..."}]}
  ],
  "ops": [
    {"op": "set_slide_text", "slide": 1, "title": "...", "bullets": ["..."]},
    {"op": "inject_timing", "slide": 1, "preset": "marquee_path", "click_shape_id": "play_button", "target_shape_id": "marquee_strip"}
  ]
}
规则：
- 禁止编造不存在的 image_ref 路径；仅使用用户提供的 images_index / presentation 中的路径。
- 动画仅用 inject_timing 的 preset：marquee_path, fade_in, fly_from_left, on_click_sequence, homework_marquee。
- 作业跑马灯/单击播放/均匀排列图片 → preset 用 homework_marquee 或 marquee_path。
- slides 至少 1 页，bullets 为字符串数组。
"""


def _extract_json_object(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


async def plan_with_llm(
    *,
    user_query: str,
    mode: str,
    presentation: Optional[Dict[str, Any]] = None,
    images_index: Optional[Dict[str, Any]] = None,
    ctx: Optional[Dict[str, Any]] = None,
    max_retries: int = 2,
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    call_llm = (ctx or {}).get("call_llm")
    if not callable(call_llm):
        warnings.append("ctx.call_llm 不可用，使用启发式 plan")
        if presentation:
            return plan_from_presentation(presentation, mode=mode), warnings
        return _heuristic_compose_plan(user_query, mode=mode), warnings

    context_parts: List[str] = [f"用户需求：{user_query}", f"模式：{mode}"]
    if presentation:
        slim = {
            "title": presentation.get("title"),
            "slide_count": presentation.get("slide_count"),
            "slides": presentation.get("slides", [])[:15],
            "has_timing": presentation.get("has_timing"),
        }
        context_parts.append("presentation_full:\n" + json.dumps(slim, ensure_ascii=False)[:12000])
    if images_index:
        context_parts.append(
            "images_index:\n" + json.dumps(images_index, ensure_ascii=False)[:8000]
        )

    user_content = "\n\n".join(context_parts)
    last_errors: List[str] = []

    for attempt in range(max_retries):
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": user_content},
        ]
        if last_errors:
            messages.append(
                {
                    "role": "user",
                    "content": "上次 plan 校验失败："
                    + "; ".join(last_errors)
                    + "。请修正后仅输出 JSON。",
                }
            )
        try:
            res = await asyncio.wait_for(
                call_llm(messages, max_tokens=4000, temperature=0.2),
                timeout=120.0,
            )
        except Exception as exc:
            warnings.append(f"LLM 调用失败：{exc}")
            break
        text = ""
        if isinstance(res, dict):
            text = str(res.get("content") or res.get("text") or "")
        else:
            text = str(res or "")
        plan, errs = parse_edit_plan_json(_extract_json_object(text))
        if not errs and (plan.get("slides") or plan.get("ops")):
            plan["mode"] = mode
            plan.setdefault("meta", {})["planner"] = "llm"
            return plan, warnings
        last_errors = errs or ["slides/ops 为空"]
        warnings.append(f"plan 校验重试 {attempt + 1}：" + "; ".join(last_errors[:3]))

    if presentation:
        warnings.append("回退为 presentation_full 启发式 plan")
        return plan_from_presentation(presentation, mode=mode), warnings
    warnings.append("回退为 compose 启发式 plan")
    return _heuristic_compose_plan(user_query, mode=mode), warnings


def _heuristic_compose_plan(user_query: str, *, mode: str = "compose") -> Dict[str, Any]:
    q = (user_query or "").strip()
    slide_count = 3
    m = re.search(r"(\d+)\s*页", q)
    if m:
        slide_count = max(1, min(20, int(m.group(1))))
    elif re.search(r"五|5", q):
        slide_count = 5
    title = "演示文稿"
    if len(q) < 80:
        title = q.splitlines()[0][:60] or title
    slides = []
    for i in range(slide_count):
        slides.append(
            {
                "index": i + 1,
                "title": f"第 {i + 1} 部分",
                "bullets": ["要点 A", "要点 B", "要点 C"],
                "images": [],
                "notes": "",
            }
        )
    plan = {
        "version": "1",
        "mode": mode,
        "title": title,
        "slides": slides,
        "ops": [],
        "meta": {"source": "heuristic"},
    }
    validated, _ = validate_edit_plan(plan)
    for s in validated.get("slides", []):
        validated["ops"].append(
            {
                "op": "set_slide_text",
                "slide": s["index"],
                "title": s["title"],
                "bullets": s["bullets"],
            }
        )
    if re.search(r"跑马灯|动画|marquee", q, re.I):
        validated["ops"].append(
            {
                "op": "inject_timing",
                "slide": 1,
                "preset": "marquee_path",
                "click_shape_id": "play_button",
                "target_shape_id": "marquee_strip",
            }
        )
    return validated
