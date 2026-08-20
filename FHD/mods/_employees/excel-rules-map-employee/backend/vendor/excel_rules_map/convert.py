"""规则映射员入口：action 分发（infer 推断规则 / compile 编译计划）。

- ``infer``：输入读取员的 workbook.json（模板一侧）→ 写出 outputs/rules.json 提案；
  宿主提供 ``ctx.call_llm`` 时（且 ``payload.use_llm`` 未显式关闭），用 LLM 精修
  启发式草案（bands/键列/clear_zone 等 open_questions），提议经机器验证后采纳。
- ``compile``：输入 rules.json（或组合 ``{"rules": .., "records": ..}``）→
  写出 outputs/plan.json（模板写入员契约），records 取自输入文件或 payload.records。

action 缺省时自动判定：JSON 含 sheets → infer；含 rules_version/template_map/rules → compile。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .compile_plan import compile_plan, rules_ref
from .golden import extract_records_from_workbook
from .infer import infer_rules
from .llm_refine import llm_refine_rules
from .solidify import solidify_transform


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{path.name}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} 根节点必须是对象")
    return data


def _detect_action(data: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> str:
    explicit = str(payload.get("action") or "").strip().lower()
    if explicit in ("infer", "推断", "rules"):
        return "infer"
    if explicit in ("compile", "编译", "plan"):
        return "compile"
    if explicit in ("solidify", "固化"):
        return "solidify"
    if isinstance(data, dict):
        if isinstance(data.get("source_workbook"), dict) and (
            isinstance(data.get("golden_workbook"), dict)
            or isinstance(data.get("expected_records"), list)
        ):
            return "solidify"
        if isinstance(data.get("sheets"), list):
            return "infer"
        if data.get("rules_version") or data.get("template_map") or data.get("rules"):
            return "compile"
    if payload.get("records") is not None or payload.get("rules") is not None:
        return "compile"
    raise ValueError(
        "无法判定 action：请上传 workbook.json（infer）、rules.json（compile），"
        "或组合 {source_workbook, golden_workbook, rules}（solidify）；"
        "也可在 payload.action 显式指定。"
    )


def _resolve_rules_and_records(
    data: Optional[Dict[str, Any]],
    payload: Dict[str, Any],
    ctx: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    rules: Optional[Dict[str, Any]] = None
    records: Optional[List[Dict[str, Any]]] = None

    if isinstance(data, dict):
        if isinstance(data.get("rules"), dict):
            rules = data["rules"]
            if isinstance(data.get("records"), list):
                records = data["records"]
        elif data.get("rules_version") or data.get("template_map"):
            rules = data

    if isinstance(payload.get("rules"), dict):
        rules = payload["rules"]
    if isinstance(payload.get("records"), list):
        records = payload["records"]

    records_path = str(payload.get("records_path") or "").strip()
    if records is None and records_path:
        p = Path(records_path).expanduser()
        if not p.is_absolute():
            root = Path(
                str(payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd())
            )
            p = root / records_path
        if not p.is_file():
            raise ValueError(f"records_path 文件不存在：{p}")
        loaded = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            records = loaded
        elif isinstance(loaded, dict) and isinstance(loaded.get("records"), list):
            records = loaded["records"]
        else:
            raise ValueError("records_path 内容必须是数组或含 records 数组的对象")

    if rules is None:
        raise ValueError("compile 缺少规则：请上传 rules.json 或在 payload.rules 传入。")
    if records is None:
        records = []
    return rules, records


def _pick_sheet(data: Dict[str, Any], sheet_name: Optional[str]) -> Dict[str, Any]:
    sheets = data.get("sheets") or []
    if sheet_name:
        for s in sheets:
            if s.get("name") == sheet_name:
                return s
    return max(sheets, key=lambda s: int(s.get("cell_count") or 0))


def _llm_enabled(payload: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    if payload.get("use_llm") is False:
        return False
    return callable(ctx.get("call_llm"))


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
    data: Optional[Dict[str, Any]] = None
    if isinstance(src_path, Path) and src_path.is_file():
        if src_path.suffix.lower() != ".json":
            raise ValueError(f"规则映射员只接受 .json 输入：{src_path.name}")
        data = _load_json(src_path)

    action = _detect_action(data, payload)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if action == "infer":
        if data is None:
            raise ValueError("infer 需要上传读取员的 workbook.json")
        sheet_name = str(payload.get("sheet") or "").strip() or None
        rules = infer_rules(
            data,
            sheet_name=sheet_name,
            source_name=str(data.get("source") or (src_path.name if src_path else "")),
        )
        if _llm_enabled(payload, ctx):
            rules = await llm_refine_rules(rules, _pick_sheet(data, sheet_name), ctx["call_llm"])
        out = output_dir / "rules.json"
        out.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        tm = rules["template_map"]
        evidence = rules["evidence"]
        return {
            "action": "infer",
            "output_path": str(out),
            "sheet": tm["sheet"],
            "block": tm["block"],
            "key_col": tm["key_col"],
            "calendar": tm["calendar"],
            "formula_zones": tm["formula_zones"],
            "formula_templates": len(rules["formula_templates"]),
            "confidences": evidence["confidences"],
            "open_questions": evidence["open_questions"],
            "llm": evidence.get("llm") or {"used": False},
            "output_schema": list(rule_spec.get("output_schema") or []),
        }

    if action == "solidify":
        if not callable(ctx.get("call_llm")) or payload.get("use_llm") is False:
            raise ValueError("solidify 需要宿主 LLM 服务（ctx.call_llm），且 use_llm 不能关闭。")
        if not isinstance(data, dict):
            raise ValueError(
                "solidify 需要上传组合 JSON：{source_workbook, golden_workbook|expected_records, rules?}"
            )
        source_workbook = data.get("source_workbook")
        if not isinstance(source_workbook, dict):
            raise ValueError("solidify 缺少 source_workbook（读取员读源表的 workbook.json）")
        rules = data.get("rules") if isinstance(data.get("rules"), dict) else payload.get("rules")
        if not isinstance(rules, dict):
            raise ValueError(
                "solidify 缺少 rules：请在组合 JSON 或 payload.rules 提供固化结构规则。"
            )
        expected_records = data.get("expected_records")
        if not isinstance(expected_records, list):
            golden_workbook = data.get("golden_workbook")
            if not isinstance(golden_workbook, dict):
                raise ValueError(
                    "solidify 缺少金样：请提供 golden_workbook（金样输出经读取员转 JSON）或 expected_records。"
                )
            expected_records = extract_records_from_workbook(golden_workbook, rules)

        result = await solidify_transform(
            source_workbook,
            rules,
            expected_records,
            ctx["call_llm"],
            business_context=str(payload.get("business_context") or ""),
            max_iterations=int(payload.get("max_iterations") or 4),
        )
        script_path = output_dir / "transform.py"
        report_path = output_dir / "solidify_report.json"
        if result.get("script"):
            script_path.write_text(result["script"], encoding="utf-8")
        report = {
            "ok": result["ok"],
            "script_path": str(script_path) if result.get("script") else "",
            "script_sha256": result.get("script_sha256") or "",
            "rules_ref": rules_ref(rules),
            "expected_slots": len(expected_records),
            "diff": result.get("diff"),
            "iterations": result.get("iterations") or [],
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        if not result["ok"]:
            attempts = len(report["iterations"])
            last_err = next(
                (it.get("error") for it in reversed(report["iterations"]) if it.get("error")),
                "金样对账未通过",
            )
            raise ValueError(
                f"固化失败（{attempts} 轮迭代）：{last_err}；证据见 {report_path.name}"
            )
        return {
            "action": "solidify",
            "output_path": str(script_path),
            "report_path": str(report_path),
            "script_sha256": report["script_sha256"],
            "rules_ref": report["rules_ref"],
            "iterations": len(report["iterations"]),
            "diff_stats": (result.get("diff") or {}).get("stats"),
            "records_count": len(result.get("records") or []),
            "output_schema": list(rule_spec.get("output_schema") or []),
        }

    rules, records = _resolve_rules_and_records(data, payload, ctx)
    plan = compile_plan(
        rules,
        records,
        month_label=str(payload.get("month_label") or "").strip() or None,
        clear_first=bool(payload.get("clear_first", True)),
    )
    out = output_dir / "plan.json"
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "action": "compile",
        "output_path": str(out),
        "phases": [str(p.get("phase")) for p in plan["phases"]],
        "expected": plan["expected"],
        "rules_ref": plan["meta"]["rules_ref"],
        "warnings": plan["meta"]["warnings"],
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
