"""Generated direct_python employee entrypoint."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict

from app.mod_sdk.errors import BOUNDARY_ERRORS
from app.mod_sdk.file_employee_support import FileEmployeeSupport

EMPLOYEE_ID = "ppt-full-read-employee"
EMPLOYEE_LABEL = "PPT 生成员"
SYSTEM_PROMPT = "你是PPT 生成员。你必须按 direct_python 方式处理真实文件，读取 payload 中的 file_path/path/excel_path，必要时使用打包模板，成功条件是实际写出输出文件。任何输入缺失、模板缺失、转换模块异常都要返回明确错误，禁止编造已完成。"
RULE_SPEC = {
    "brief": "PPT 全量读取：大纲、原生正文、表格和已有备注写入 outputs/presentation_full.json，内嵌图片本地导出至 outputs/images/，已有备注写入 outputs/speaker_notes.md。读取不隐式调用模型；缺少逐文件内容外发授权时图片语义与备注生成标记 blocked。",
    "mode": "direct_python_file_transform",
    "accepted_extensions": [".pptx"],
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
        "source",
        "status",
        "image_semantics",
        "notes_generation",
    ],
    "requirements": [
        'Use direct_python only; handlers must be ["direct_python"].',
        "Parse pptx with python-pptx; never use LLM for slide body text.",
        "Export embedded images to outputs/images/<category>/.",
        "Preserve extracted images locally; no implicit VLM call without verified document-content egress authorization.",
        "Preserve original speaker notes; leave notes_generated empty and report blocked without verified document-content egress authorization.",
        "Write presentation_full.json, presentation_meta.json, speaker_notes.md, images_index.json.",
        "Return {ok, summary, items, warnings, error, meta}.",
    ],
    "pack_id": "ppt-full-read-employee",
}


_file_support = FileEmployeeSupport(__file__, RULE_SPEC)
_ok = _file_support._ok
_err = _file_support._err
_summary = _file_support._summary
_pack_root = _file_support._pack_root
_workspace_root = _file_support._workspace_root
_resolve_input = _file_support._resolve_input
_resolve_output = _file_support._resolve_output
_resolve_template = _file_support._resolve_template


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    ctx = dict(ctx or {})
    action = (
        str(payload.get("action") or RULE_SPEC.get("default_action") or "convert").strip().lower()
    )
    if action in ("help", "说明", "status"):
        return _ok(
            {"employee": EMPLOYEE_LABEL, "rule_spec": RULE_SPEC},
            meta={"handler": "direct_python", "action": "help"},
        )
    if action not in ("convert", "upload", "转换", ""):
        return _err(
            f"不支持的 action：{action}", meta={"handler": "direct_python", "action": action}
        )
    try:
        vendor_dir = _pack_root() / "vendor"
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from ppt_full_read.convert import convert_file

        src = _resolve_input(payload, ctx)
        out = _resolve_output(payload, ctx)
        template = _resolve_template(payload, ctx)
        result = convert_file(
            src, out, template_path=template, payload=payload, ctx=ctx, rule_spec=RULE_SPEC
        )
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, dict):
            result.setdefault("output_path", str(out))
            result.setdefault("template_path", str(template or ""))
        else:
            result = {
                "output_path": str(out),
                "template_path": str(template or ""),
                "result": result,
            }
        if not out.is_file():
            return _err(
                f"转换未生成输出文件：{out}", meta={"handler": "direct_python", "action": "convert"}
            )
        normalized = _ok(
            result,
            meta={"handler": "direct_python", "action": "convert", "runtime": "generated_python"},
        )
        return {
            "ok": normalized["ok"],
            "summary": normalized["summary"],
            "items": normalized["items"],
            "warnings": normalized["warnings"],
            "error": normalized["error"],
            "meta": normalized["meta"],
        }
    except BOUNDARY_ERRORS as exc:
        return _err(
            str(exc),
            warnings=["请检查输入文件、模板文件和题目规则是否匹配。"],
            meta={"handler": "direct_python", "action": "convert", "runtime": "generated_python"},
        )
