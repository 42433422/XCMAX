"""Generated direct_python employee entrypoint."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.mod_sdk.errors import BOUNDARY_ERRORS

EMPLOYEE_ID = "excel-template-write-employee"
EMPLOYEE_LABEL = "Excel 模板写入员"
SYSTEM_PROMPT = "你是Excel 模板写入员。你必须按 direct_python 方式执行 plan.json 写入计划，把值/公式回填进模板 xlsx，保留模板样式、合并单元格与既有公式，拒绝写入保护区。成功条件是实际写出回填结果文件与 write_report.json。任何计划缺失、模板缺失、sheet 不匹配都要返回明确错误，禁止编造已完成。"
RULE_SPEC = {
    "brief": "Excel模板写入员工：上传 plan.json 写入计划 + 模板 .xlsx/.xlsm，使用 direct_python 按 phases（clear_ranges/cell_writes/formula_writes/retain_sheets）回填模板，保留样式与既有公式，保护区拒写，输出 outputs/filled.xlsx 与 write_report.json，禁止 LLM 编造单元格。",
    "mode": "direct_python_file_transform",
    "accepted_extensions": [".json"],
    "default_action": "convert",
    "default_output_relpath": "outputs/filled.xlsx",
    "runtime_kind": "excel_template_write",
    "output_schema": [
        "output_path",
        "report_path",
        "cells_written",
        "formulas_written",
        "cells_cleared",
        "violations",
        "expected",
    ],
    "requirements": [
        'Use direct_python only; handlers must be ["direct_python"].',
        "Input is plan.json (or payload.plan); template resolved from payload.template_path/template_relpath, bundled templates/, or plan.template.path.",
        "Execute phases in order: clear_ranges, cell_writes, formula_writes, retain_sheets/remove_sheets.",
        "Preserve template styles, merged cells and existing formulas; never evaluate formulas.",
        "Writes hitting protected_ranges are skipped and recorded as violations; payload.strict_protected fails instead.",
        "Write outputs/filled.xlsx and write_report.json; pass plan.expected through untouched for QC.",
        "Never claim success unless the filled workbook is actually written.",
        "Return {ok, summary, items, warnings, error, meta}.",
    ],
    "pack_id": "excel-template-write-employee",
}


def _ok(
    data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {
        "ok": True,
        "summary": _summary(data),
        "items": data if isinstance(data, list) else [data],
        "warnings": list(warnings or []),
        "error": "",
        "meta": dict(meta or {}),
    }


def _err(
    msg: str, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return {
        "ok": False,
        "summary": msg[:400],
        "items": [],
        "warnings": list(warnings or []),
        "error": msg[:1000],
        "meta": dict(meta or {}),
    }


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


def _resolve_input(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Path]:
    raw = str(
        payload.get("file_path") or payload.get("path") or payload.get("plan_path") or ""
    ).strip()
    if not raw:
        if isinstance(payload.get("plan"), dict):
            return None
        raise FileNotFoundError(
            "缺少 file_path：请上传 plan.json 写入计划，或在 payload.plan 传入计划对象。"
        )
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / raw
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在：{p}")
    return p


def _resolve_output(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
    rel = str(
        payload.get("output_relpath")
        or RULE_SPEC.get("default_output_relpath")
        or "outputs/filled.xlsx"
    ).strip()
    p = Path(rel).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_template(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Path]:
    raw = str(
        payload.get("template_path")
        or payload.get("template_relpath")
        or RULE_SPEC.get("default_template_relpath")
        or RULE_SPEC.get("template_relpath")
        or ""
    ).strip()
    candidates = []
    if raw:
        p = Path(raw).expanduser()
        if p.is_absolute():
            candidates.append(p)
        else:
            candidates.append(_workspace_root(ctx, payload) / raw)
            candidates.append(_pack_root() / raw)
            candidates.append(_pack_root() / "backend" / "templates" / raw)
            if raw.startswith("backend/"):
                candidates.append(_pack_root() / raw[len("backend/") :])
    for cand in candidates:
        if cand.is_file():
            return cand
    bundled_templates = (
        sorted((_pack_root() / "templates").rglob("*.xls*"))
        if (_pack_root() / "templates").is_dir()
        else []
    )
    if bundled_templates:
        return bundled_templates[0]
    return None


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
    if action not in ("convert", "upload", "转换", "回填", ""):
        return _err(
            f"不支持的 action：{action}", meta={"handler": "direct_python", "action": action}
        )
    try:
        vendor_dir = _pack_root() / "vendor"
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from excel_template_write.convert import convert_file

        src = _resolve_input(payload, ctx)
        out = _resolve_output(payload, ctx)
        template = _resolve_template(payload, ctx)
        result = convert_file(
            src, out, template_path=template, payload=payload, ctx=ctx, rule_spec=RULE_SPEC
        )
        if asyncio.iscoroutine(result):
            result = await result
        run_warnings: List[str] = []
        if isinstance(result, dict):
            result.setdefault("output_path", str(out))
            result.setdefault("template_path", str(template or ""))
            run_warnings = [str(w) for w in (result.get("warnings") or [])]
        else:
            result = {
                "output_path": str(out),
                "template_path": str(template or ""),
                "result": result,
            }
        produced = Path(str(result.get("output_path") or out))
        if not produced.is_file():
            return _err(
                f"回填未生成输出文件：{produced}",
                meta={"handler": "direct_python", "action": "convert"},
            )
        normalized = _ok(
            result,
            warnings=run_warnings,
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
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return _err(
            str(exc),
            warnings=["请检查 plan.json 写入计划、模板文件与 sheet 名是否匹配。"],
            meta={"handler": "direct_python", "action": "convert", "runtime": "generated_python"},
        )
