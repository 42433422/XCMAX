"""Generated direct_python employee entrypoint."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict

from app.mod_sdk.errors import BOUNDARY_ERRORS
from app.mod_sdk.file_employee_support import FileEmployeeSupport

EMPLOYEE_ID = "ppt-generate-employee"
EMPLOYEE_LABEL = "PPT 生成员"
SYSTEM_PROMPT = "你是PPT 生成员。你必须按 direct_python 方式处理真实文件，读取 payload 中的 file_path/path/excel_path，必要时使用打包模板，成功条件是实际写出输出文件。任何输入缺失、模板缺失、转换模块异常都要返回明确错误，禁止编造已完成。"
RULE_SPEC = {
    "brief": "制作 PPT 生成员工包（Codex 级）。compose-first：无模板时从零合成多页 output.pptx；enhance：复制 template.pptx 后按 LLM 编排的 ppt_edit_plan 注入 OOXML 动画；输入 presentation_full v2 JSON / user_query / .txt，可选 template_file；输出 output.pptx 与 ppt_edit_plan.json；作业跑马灯用 homework_marquee 配方；direct_python。",
    "mode": "direct_python_file_transform",
    "accepted_extensions": [".json", ".txt"],
    "default_action": "convert",
    "default_output_relpath": "outputs/output.pptx",
    "runtime_kind": "ppt_generate",
    "optional_llm_polish": False,
    "output_schema": ["title", "slides", "slide_count", "stats", "metadata"],
    "requirements": [
        'handlers must include "direct_python"; may include "agent" for optional polish.',
        "Run modstore_server.ppt_generate_pipeline.run_ppt_generate: route → plan → compose/enhance → OOXML.",
        "When template_path is .pptx, copy template; else compose deck from plan slides.",
        "LLM planner outputs ppt_edit_plan.json; executor applies inject_timing presets.",
        "Never fabricate slides when input is empty; fallback to text-only only with warnings.",
        "Return {ok, summary, items, warnings, error, meta}.",
    ],
    "pack_id": "ppt-generate-employee",
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
        from ppt_generate.convert import convert_file

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
