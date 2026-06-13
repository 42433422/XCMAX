"""Generated direct_python employee entrypoint."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

EMPLOYEE_ID = "ppt-full-read-employee"
EMPLOYEE_LABEL = "PPT 生成员"
SYSTEM_PROMPT = "你是PPT 生成员。你必须按 direct_python 方式处理真实文件，读取 payload 中的 file_path/path/excel_path，必要时使用打包模板，成功条件是实际写出输出文件。任何输入缺失、模板缺失、转换模块异常都要返回明确错误，禁止编造已完成。"
RULE_SPEC = {
  "brief": "制作 PPT 全量读取员工包。上传 .pptx：解析大纲与每页正文写入 outputs/presentation_full.json；内嵌图片导出到 outputs/images/ 并通过 VLM（ctx.call_llm vision）生成 .vlm.json；按提示词「为这份PPT生成每页的演讲备注」生成 notes_generated 与 outputs/speaker_notes.md。使用 direct_python，handlers 仅 direct_python，禁止编造幻灯片正文。",
  "mode": "direct_python_file_transform",
  "accepted_extensions": [
    ".pptx"
  ],
  "default_action": "convert",
  "default_output_relpath": "outputs/presentation_full.json",
  "default_meta_relpath": "outputs/presentation_meta.json",
  "default_images_dir": "outputs/images",
  "default_notes_relpath": "outputs/speaker_notes.md",
  "runtime_kind": "ppt_full_read",
  "speaker_notes_prompt": "为这份PPT生成每页的演讲备注",
  "output_schema": [
    "title",
    "slide_count",
    "outline",
    "slides",
    "images",
    "notes_generated",
    "source"
  ],
  "requirements": [
    "Use direct_python only; handlers must be [\"direct_python\"].",
    "Parse pptx with python-pptx; never use LLM for slide body text.",
    "Export embedded images to outputs/images/<category>/.",
    "When ctx.call_llm supports vision, describe each image to .vlm.json sidecar.",
    "Generate per-slide speaker notes via ctx.call_llm text with prompt: 为这份PPT生成每页的演讲备注",
    "Write presentation_full.json, presentation_meta.json, speaker_notes.md, images_index.json.",
    "Return {ok, summary, items, warnings, error, meta}."
  ],
  "pack_id": "ppt-full-read-employee"
}


def _ok(data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": True, "summary": _summary(data), "items": data if isinstance(data, list) else [data], "warnings": list(warnings or []), "error": "", "meta": dict(meta or {})}


def _err(msg: str, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"ok": False, "summary": msg[:400], "items": [], "warnings": list(warnings or []), "error": msg[:1000], "meta": dict(meta or {})}


def _summary(data: Any) -> str:
    if isinstance(data, str):
        return data[:4000]
    try:
        return json.dumps(data, ensure_ascii=False)[:4000]
    except TypeError:
        return str(data)[:4000]


def _pack_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:
    raw = payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd()
    return Path(str(raw)).expanduser()


def _resolve_input(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
    raw = str(payload.get("file_path") or payload.get("path") or payload.get("excel_path") or "").strip()
    if not raw:
        raise FileNotFoundError("缺少 file_path：请上传或指定要处理的文件。")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / raw
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在：{p}")
    return p


def _resolve_output(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
    rel = str(payload.get("output_relpath") or RULE_SPEC.get("default_output_relpath") or "outputs/employee_output.xlsx").strip()
    p = Path(rel).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_template(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Path]:
    raw = str(
        payload.get("template_relpath")
        or RULE_SPEC.get("default_template_relpath")
        or RULE_SPEC.get("template_relpath")
        or ""
    ).strip()
    if not raw:
        return None
    candidates = []
    p = Path(raw).expanduser()
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(_workspace_root(ctx, payload) / raw)
        candidates.append(_pack_root() / raw)
        candidates.append(_pack_root() / "backend" / "templates" / raw)
        if raw.startswith("backend/"):
            candidates.append(_pack_root() / raw[len("backend/"):])
    for cand in candidates:
        if cand.is_file():
            return cand
    bundled_templates = sorted((_pack_root() / "templates").rglob("*.xls*")) if (_pack_root() / "templates").is_dir() else []
    if bundled_templates:
        return bundled_templates[0]
    return None


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    ctx = dict(ctx or {})
    action = str(payload.get("action") or RULE_SPEC.get("default_action") or "convert").strip().lower()
    if action in ("help", "说明", "status"):
        return _ok({"employee": EMPLOYEE_LABEL, "rule_spec": RULE_SPEC}, meta={"handler": "direct_python", "action": "help"})
    if action not in ("convert", "upload", "转换", ""):
        return _err(f"不支持的 action：{action}", meta={"handler": "direct_python", "action": action})
    try:
        vendor_dir = _pack_root() / "vendor"
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from ppt_full_read.convert import convert_file
        src = _resolve_input(payload, ctx)
        out = _resolve_output(payload, ctx)
        template = _resolve_template(payload, ctx)
        result = convert_file(src, out, template_path=template, payload=payload, ctx=ctx, rule_spec=RULE_SPEC)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, dict):
            result.setdefault("output_path", str(out))
            result.setdefault("template_path", str(template or ""))
        else:
            result = {"output_path": str(out), "template_path": str(template or ""), "result": result}
        if not out.is_file():
            return _err(f"转换未生成输出文件：{out}", meta={"handler": "direct_python", "action": "convert"})
        normalized = _ok(result, meta={"handler": "direct_python", "action": "convert", "runtime": "generated_python"})
        return {
            "ok": normalized["ok"],
            "summary": normalized["summary"],
            "items": normalized["items"],
            "warnings": normalized["warnings"],
            "error": normalized["error"],
            "meta": normalized["meta"],
        }
    except Exception as exc:  # noqa: BLE001
        return _err(str(exc), warnings=["请检查输入文件、模板文件和题目规则是否匹配。"], meta={"handler": "direct_python", "action": "convert", "runtime": "generated_python"})
