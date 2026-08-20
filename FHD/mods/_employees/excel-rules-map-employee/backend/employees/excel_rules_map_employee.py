"""Generated direct_python employee entrypoint."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.mod_sdk.errors import BOUNDARY_ERRORS

EMPLOYEE_ID = "excel-rules-map-employee"
EMPLOYEE_LABEL = "Excel 规则映射员"
SYSTEM_PROMPT = "你是Excel 规则映射员。你必须按 direct_python 方式工作：infer 时从读取员的 workbook.json 推断模板结构规则并写出 rules.json 提案（含置信度与待确认项）；compile 时把固化规则与槽位记录编译为模板写入员的 plan.json（带 rules_ref 哈希）。禁止 LLM 编造结构或数据；推断不确定的项必须列入 open_questions 交人确认，不得假装确定。"
RULE_SPEC = {
    "brief": "Excel规则映射员工：direct_python 双动作——infer 上传模板侧 workbook.json 推断块结构/键列/日历锚/公式区/公式模板并输出 outputs/rules.json 提案（置信度+open_questions）；compile 上传 rules.json（records 走 payload）编译 outputs/plan.json（clear/cell/formula/retain 阶段+expected+rules_ref），禁止编造结构。",
    "mode": "direct_python_file_transform",
    "accepted_extensions": [".json"],
    "default_action": "convert",
    "default_output_relpath": "outputs/rules.json",
    "runtime_kind": "excel_rules_map",
    "output_schema": [
        "action",
        "output_path",
        "block",
        "key_col",
        "calendar",
        "formula_templates",
        "confidences",
        "open_questions",
        "expected",
        "rules_ref",
    ],
    "requirements": [
        'Use direct_python only; handlers must be ["direct_python"].',
        "infer: consume reader workbook.json (template side); detect row blocks via merged-range periodicity, key column, calendar anchor sequence, formula zones; fit per-column formula templates by numeric arithmetic progression across blocks.",
        "infer output rules.json is a proposal: evidence.confidences + open_questions for human confirmation; never fabricate structure.",
        "When host provides ctx.call_llm (and payload.use_llm is not false), refine the heuristic draft with LLM proposals (bands / key_col / clear_zone / open questions); every proposal must pass deterministic validation before adoption; adopted/rejected recorded in evidence.llm.",
        "compile: rules.json + records (payload.records / records_path / bundled {rules, records}) -> plan.json following excel-template-write plan_version=1 contract.",
        "solidify: bundled {source_workbook, golden_workbook|expected_records, rules} + ctx.call_llm -> LLM writes produce_records(source_workbook, rules) Python script; loop static-safety-check -> sandbox run -> records contract check -> golden diff (deterministic reverse-read of golden workbook); solidify only on full green: outputs/transform.py + solidify_report.json (iterations evidence, script sha256, rules_ref); monthly reruns then need zero LLM.",
        "compile validates day/band/entry bounds, drops out-of-roster keys with reasons, emits expected block and meta.rules_ref sha256 for QC.",
        "Never claim success unless rules.json / plan.json is actually written.",
        "Return {ok, summary, items, warnings, error, meta}.",
    ],
    "pack_id": "excel-rules-map-employee",
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
    raw = str(payload.get("file_path") or payload.get("path") or "").strip()
    if not raw:
        if payload.get("rules") is not None or payload.get("records") is not None:
            return None
        raise FileNotFoundError(
            "缺少 file_path：请上传 workbook.json（infer）或 rules.json（compile），"
            "或在 payload.rules/records 传入。"
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
        or "outputs/rules.json"
    ).strip()
    p = Path(rel).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    ctx = dict(ctx or {})
    action = str(payload.get("action") or "").strip().lower()
    if action in ("help", "说明", "status"):
        return _ok(
            {"employee": EMPLOYEE_LABEL, "rule_spec": RULE_SPEC},
            meta={"handler": "direct_python", "action": "help"},
        )
    try:
        vendor_dir = _pack_root() / "vendor"
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from excel_rules_map.convert import convert_file

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
                f"未生成输出文件：{produced}",
                meta={"handler": "direct_python", "action": action or "auto"},
            )
        run_warnings = (
            [str(w) for w in (result.get("warnings") or [])] if isinstance(result, dict) else []
        )
        normalized = _ok(
            result,
            warnings=run_warnings,
            meta={
                "handler": "direct_python",
                "action": str(result.get("action") or action or "auto"),
                "runtime": "generated_python",
            },
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
            warnings=["请检查上传的 workbook.json/rules.json 结构与 payload.action 是否匹配。"],
            meta={
                "handler": "direct_python",
                "action": action or "auto",
                "runtime": "generated_python",
            },
        )
