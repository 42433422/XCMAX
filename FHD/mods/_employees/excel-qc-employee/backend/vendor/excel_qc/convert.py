"""质检员入口：回填结果 xlsx + plan.json（+ 可选模板/rules/write_report）→ qc_report.json。

确定性六节先行（地基）；宿主提供 ``ctx.call_llm`` 时（且 ``payload.use_llm``
未显式关闭）追加 ``semantic`` 节——LLM 业务合理性审查 + ``human_summary`` 人话摘要。
``payload.llm_strict=false`` 可把 LLM 的 fail 降级为 warn。

员工执行成功（ok=true）不等于质检通过：verdict（PASS/WARN/FAIL）与问责路由
（blame）在报告与返回值里，由调用方决定闭环走向（重跑写入员 / 回炉映射员 /
规则重新 infer / 转人工）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .checks import merge_semantic_section, run_qc
from .llm_review import llm_semantic_review


def _load_json_file(path: Path, label: str) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON 解析失败：{path.name}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} 根节点必须是对象：{path.name}")
    return data


def _resolve_path(raw: Any, payload: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Path]:
    text = str(raw or "").strip()
    if not text:
        return None
    p = Path(text).expanduser()
    if not p.is_absolute():
        root = Path(str(payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd()))
        p = root / text
    return p


def _optional_json(
    inline_key: str, path_key: str, label: str, payload: Dict[str, Any], ctx: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    inline = payload.get(inline_key)
    if isinstance(inline, dict):
        return inline
    p = _resolve_path(payload.get(path_key), payload, ctx)
    if p is None:
        return None
    if not p.is_file():
        raise ValueError(f"{label} 文件不存在：{p}")
    return _load_json_file(p, label)


async def convert_file(
    src_path: Optional[Path],
    output_path: Path,
    *,
    template_path: Optional[Path] = None,
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
    rule_spec: Dict[str, Any],
) -> Dict[str, Any]:
    payload = payload or {}
    ctx = ctx or {}

    filled = src_path if isinstance(src_path, Path) else None
    if filled is None or not filled.is_file():
        raise ValueError("缺少回填结果文件：请上传写入员产出的 .xlsx/.xlsm。")
    if filled.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError(f"质检对象必须是 .xlsx/.xlsm：{filled.name}")

    plan = _optional_json("plan", "plan_path", "plan.json", payload, ctx)
    if plan is None:
        raise ValueError(
            "缺少写入计划：请在 payload.plan 内联或 payload.plan_path 指定 plan.json。"
        )

    rules = _optional_json("rules", "rules_path", "rules.json", payload, ctx)
    write_report = _optional_json(
        "write_report", "write_report_path", "write_report.json", payload, ctx
    )
    tpl = (
        template_path
        if template_path and Path(template_path).is_file()
        else _resolve_path(
            payload.get("template_path") or payload.get("template_relpath"), payload, ctx
        )
    )

    report = run_qc(
        filled,
        plan,
        template_path=tpl if tpl and tpl.is_file() else None,
        rules=rules,
        write_report=write_report,
    )

    call_llm = ctx.get("call_llm")
    if payload.get("use_llm") is False or not callable(call_llm):
        semantic = {
            "status": "skipped",
            "issues": [],
            "stats": {},
            "human_summary": "",
            "skipped_reason": "LLM 关闭或宿主未提供 call_llm，语义审查未执行",
        }
    else:
        semantic = await llm_semantic_review(
            plan,
            report["sections"],
            call_llm,
            rules=rules,
            business_context=str(payload.get("business_context") or ""),
            strict=payload.get("llm_strict", True) is not False,
        )
    report = merge_semantic_section(report, semantic)

    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / "qc_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    return {
        "output_path": str(out),
        "verdict": report["verdict"],
        "blame": report["blame"],
        "summary": report["summary"],
        "human_summary": report.get("human_summary") or "",
        "sections": {name: sec["status"] for name, sec in report["sections"].items()},
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
