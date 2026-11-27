"""Generated direct_python employee entrypoint."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.mod_sdk.errors import BOUNDARY_ERRORS
from app.mod_sdk.file_employee_support import FileEmployeeSupport

EMPLOYEE_ID = "excel-qc-employee"
EMPLOYEE_LABEL = "Excel 质检员"
SYSTEM_PROMPT = "你是Excel 质检员。你必须按 direct_python 方式对回填结果做独立结构对账：计划符合性、保护区完整性、expected 自洽、公式健康、rules_ref 追溯、结构漂移，写出 qc_report.json 并给出 PASS/WARN/FAIL 与问责路由。你不复用映射员/写入员代码路径，从独立输入重算不变量。禁止在证据不足时给 PASS；缺输入的检查必须标记 skipped 并说明，不得假装通过。"
RULE_SPEC = {
    "brief": "Excel质检员工：上传回填结果 .xlsx/.xlsm + payload 提供 plan.json（可选 rules.json/write_report.json/原模板），使用 direct_python 独立对账——计划符合性/保护区/expected 重算/公式 #REF! 与悬空引用/rules_ref 哈希追溯/块结构漂移，输出 outputs/qc_report.json（verdict PASS/WARN/FAIL + blame 问责路由），禁止编造检查结果。",
    "mode": "direct_python_file_transform",
    "accepted_extensions": [".xlsx", ".xlsm"],
    "default_action": "convert",
    "default_output_relpath": "outputs/qc_report.json",
    "runtime_kind": "excel_qc_report",
    "output_schema": [
        "verdict",
        "blame",
        "sections",
        "summary",
        "output_path",
    ],
    "requirements": [
        'Use direct_python only; handlers must be ["direct_python"].',
        "Input file is the filled workbook; plan via payload.plan/plan_path (required); rules via payload.rules/rules_path, template via payload.template_path, write_report via payload.write_report_path (optional).",
        "Independence: never import mapper/writer code; recompute invariants from plan + rules + output workbook directly.",
        "Sections: conformance (cell/formula/clear/retain vs plan), protection (template diff), expected (plan-recompute vs mapper claim vs file-recompute), formulas (#REF!/dangling sheet refs), traceability (rules sha256 vs plan.meta.rules_ref), structure (rules.blocks keys vs file).",
        "Missing inputs make a section skipped with reason — never fake pass.",
        "When host provides ctx.call_llm (and payload.use_llm is not false), add semantic section: LLM business-sanity review (value plausibility, dropped-record suspicion, warning triage) over deterministic results, plus human_summary in Chinese; LLM can add findings but never overturn deterministic sections; payload.llm_strict=false downgrades LLM fail to warn.",
        "Verdict: any fail -> FAIL with blame routing (writer_or_plan/mapper/pipeline/rules_stale); warn-only -> WARN; else PASS.",
        "Never claim success unless qc_report.json is actually written; employee ok means QC executed, not QC passed.",
        "Return {ok, summary, items, warnings, error, meta}.",
    ],
    "pack_id": "excel-qc-employee",
}


_file_support = FileEmployeeSupport(__file__, RULE_SPEC)
_err = _file_support._err
_pack_root = _file_support._pack_root
_workspace_root = _file_support._workspace_root
_resolve_output = _file_support._resolve_output


def _ok(
    data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    if isinstance(data, str):
        summary = data[:4000]
    else:
        try:
            summary = json.dumps(data, ensure_ascii=False)[:4000]
        except TypeError:
            summary = str(data)[:4000]
    return {
        "ok": True,
        "summary": summary,
        "items": data if isinstance(data, list) else [data],
        "warnings": list(warnings or []),
        "error": "",
        "meta": dict(meta or {}),
    }


def _resolve_input(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
    raw = str(
        payload.get("file_path") or payload.get("path") or payload.get("excel_path") or ""
    ).strip()
    if not raw:
        raise FileNotFoundError("缺少 file_path：请上传写入员产出的回填结果 .xlsx/.xlsm。")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / raw
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在：{p}")
    return p


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
    if action not in ("convert", "upload", "qc", "质检", ""):
        return _err(
            f"不支持的 action：{action}", meta={"handler": "direct_python", "action": action}
        )
    try:
        vendor_dir = _pack_root() / "vendor"
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from excel_qc.convert import convert_file

        src = _resolve_input(payload, ctx)
        out = _resolve_output(payload, ctx)
        result = convert_file(
            src, out, template_path=None, payload=payload, ctx=ctx, rule_spec=RULE_SPEC
        )
        if asyncio.iscoroutine(result):
            result = await result
        produced = Path(str((result or {}).get("output_path") or out))
        if not produced.is_file():
            return _err(
                f"质检未生成报告文件：{produced}",
                meta={"handler": "direct_python", "action": "convert"},
            )
        verdict = str(result.get("verdict") or "")
        run_warnings: List[str] = []
        if verdict == "FAIL":
            run_warnings.append(f"质检不通过：blame={result.get('blame')}（详见 qc_report.json）")
        elif verdict == "WARN":
            run_warnings.append("质检有警告（详见 qc_report.json）")
        return _ok(
            result,
            warnings=run_warnings,
            meta={
                "handler": "direct_python",
                "action": "convert",
                "runtime": "generated_python",
                "verdict": verdict,
            },
        )
    except BOUNDARY_ERRORS as exc:
        return _err(
            str(exc),
            warnings=[
                "请检查回填结果文件与 payload.plan/plan_path（必需）、rules/template（可选）是否齐备。"
            ],
            meta={"handler": "direct_python", "action": "convert", "runtime": "generated_python"},
        )
