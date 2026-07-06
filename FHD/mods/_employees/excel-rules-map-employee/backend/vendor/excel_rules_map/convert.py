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

from .compile_plan import compile_plan
from .infer import infer_rules
from .llm_refine import llm_refine_rules


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
    if isinstance(data, dict):
        if isinstance(data.get("sheets"), list):
            return "infer"
        if data.get("rules_version") or data.get("template_map") or data.get("rules"):
            return "compile"
    if payload.get("records") is not None or payload.get("rules") is not None:
        return "compile"
    raise ValueError(
        "无法判定 action：请上传 workbook.json（infer）或 rules.json（compile），"
        "或在 payload.action 显式指定 infer/compile。"
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
            root = Path(str(payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd()))
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
            rules = await llm_refine_rules(
                rules, _pick_sheet(data, sheet_name), ctx["call_llm"]
            )
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

    rules, records = _resolve_rules_and_records(data, payload, ctx)
    plan = compile_plan(
        rules,
        records,
        month_label=str(payload.get("month_label") or "").strip() or None,
        clear_first=bool(payload.get("clear_first", True)),
    )
    out = output_dir / "plan.json"
    out.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return {
        "action": "compile",
        "output_path": str(out),
        "phases": [str(p.get("phase")) for p in plan["phases"]],
        "expected": plan["expected"],
        "rules_ref": plan["meta"]["rules_ref"],
        "warnings": plan["meta"]["warnings"],
        "output_schema": list(rule_spec.get("output_schema") or []),
    }
