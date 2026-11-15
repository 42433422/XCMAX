"""Generated direct_python employee entrypoint."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from app.mod_sdk.errors import BOUNDARY_ERRORS
from app.mod_sdk.file_employee_support import FileEmployeeSupport

EMPLOYEE_ID = "pdf-full-read-employee"
EMPLOYEE_LABEL = "PDF 生成员"
SYSTEM_PROMPT = "你是PDF 生成员。你必须按 direct_python 方式处理真实文件，读取 payload 中的 file_path/path/excel_path，必要时使用打包模板，成功条件是实际写出输出文件。任何输入缺失、模板缺失、转换模块异常都要返回明确错误，禁止编造已完成。"
RULE_SPEC = {
    "brief": "制作 PDF 全量读取员工包。上传 .pdf：只读原生文字层写入 outputs/document_full.txt；内嵌图片导出到 outputs/images/{figures,photos,diagrams,icons,uncategorized}/，并通过 VLM（ctx.call_llm vision）生成 .vlm.json 描述；元数据 outputs/document_meta.json。使用 direct_python，handlers 仅 direct_python。",
    "mode": "direct_python_file_transform",
    "accepted_extensions": [".pdf"],
    "default_action": "convert",
    "default_output_relpath": "outputs/document_full.txt",
    "default_meta_relpath": "outputs/document_meta.json",
    "default_images_dir": "outputs/images",
    "runtime_kind": "pdf_full_read",
    "output_schema": [
        "plain_text",
        "pages",
        "page_count",
        "char_count",
        "images",
        "image_categories",
        "source",
    ],
    "requirements": [
        'Use direct_python only; handlers must be ["direct_python"].',
        "Extract native text and embedded images with pypdf; never use LLM for body text.",
        "Export images to outputs/images/{figures,photos,diagrams,icons,uncategorized}/.",
        "When ctx.call_llm supports vision, describe each image to outputs/images/<cat>/<name>.vlm.json.",
        "Write document_full.txt, document_meta.json, images_index.json.",
        "Return {ok, summary, items, warnings, error, meta}.",
    ],
    "pack_id": "pdf-full-read-employee",
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
        from pdf_full_read.convert import convert_file

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
        if not out.is_file() and out.suffix.lower() == ".json" and isinstance(result, dict):
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
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
