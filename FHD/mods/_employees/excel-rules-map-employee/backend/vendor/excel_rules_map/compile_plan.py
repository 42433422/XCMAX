"""计划编译器：固化规则 rules.json + 槽位记录 records → 写入计划 plan.json。

规则映射员只决定「哪里写、怎么写」；「写什么值」由上游（领域算子/人）以
records 形式给出，本模块保持零领域知识：

- 日历型记录：``{"key": "张三", "day": 5, "band": "morning",
  "entries": [{"symbol": "√", "value": 2.0}]}``
  → 槽列 = anchor + (day-1)×slots_per_day；行 = 块首行 + band.row_offset + entry 序号；
  layout=symbol_value 时写 (符号格, 数值格) 两格，value 布局只写数值格。
- 直写型记录：``{"key": "张三", "cells": [{"col": "BQ"|col_index,
  "row_offset": 0, "value": x, "number_format": "0.0"}]}`` → 块内任意格。

编译产物遵守模板写入员 plan_version=1 契约（phases / protected_ranges /
expected），并带 ``meta.rules_ref``（规则内容 sha256）供质检员追溯对账。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .infer import instantiate_formula

PLAN_VERSION = 1

_COL_RE = re.compile(r"^[A-Z]{1,3}$")
_REF_RE = re.compile(r"^([A-Z]{1,3})(\d+)$")


class CompileError(ValueError):
    """规则或记录不满足编译条件（fail-fast）。"""


def _col_to_index(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _index_to_col(idx: int) -> str:
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def rules_ref(rules: Dict[str, Any]) -> Dict[str, str]:
    canonical = json.dumps(rules, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "domain": str(rules.get("domain") or ""),
    }


def _norm_key(value: Any) -> str:
    return str(value or "").strip()


def _require(rules: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if int(rules.get("rules_version") or 0) != 1:
        raise CompileError(f"不支持的 rules_version：{rules.get('rules_version')!r}（当前支持 1）")
    tm = rules.get("template_map")
    if not isinstance(tm, dict):
        raise CompileError("rules.template_map 缺失")
    block = tm.get("block")
    if not isinstance(block, dict) or not block.get("rows") or not block.get("first_top"):
        raise CompileError("rules.template_map.block 缺失或不完整（需要 rows/first_top/count）")
    if not isinstance(tm.get("blocks"), list) or not tm["blocks"]:
        raise CompileError("rules.template_map.blocks 缺失（键 → 块首行映射）")
    if not str(tm.get("sheet") or "").strip():
        raise CompileError("rules.template_map.sheet 缺失")
    return tm, block


def _resolve_col(spec: Dict[str, Any]) -> int:
    raw = spec.get("col")
    if isinstance(raw, int) and raw >= 1:
        return raw
    text = str(raw or "").strip().upper()
    if _COL_RE.match(text):
        return _col_to_index(text)
    raise CompileError(f"直写记录 col 非法：{raw!r}（需要列字母或 ≥1 的列号）")


def _month_writes(
    tm: Dict[str, Any], sheet: str, month_label: Optional[str]
) -> List[Dict[str, Any]]:
    cells = tm.get("month_cells") or []
    if not month_label or not cells:
        return []
    try:
        year_str, month_str = str(month_label).split("-", 1)
        year, month = int(year_str), int(month_str)
    except ValueError as exc:
        raise CompileError(f"month_label 需为 YYYY-MM：{month_label!r}") from exc
    out: List[Dict[str, Any]] = []
    for item in cells:
        part = str(item.get("part") or "")
        ref = str(item.get("ref") or "").strip().upper()
        m = _REF_RE.match(ref)
        if not m or part not in ("year", "month"):
            continue
        out.append(
            {
                "sheet": sheet,
                "row": int(m.group(2)),
                "col": _col_to_index(m.group(1)),
                "value": year if part == "year" else month,
            }
        )
    return out


def compile_plan(
    rules: Dict[str, Any],
    records: List[Dict[str, Any]],
    *,
    month_label: Optional[str] = None,
    clear_first: bool = True,
) -> Dict[str, Any]:
    tm, block = _require(rules)
    sheet = str(tm["sheet"])
    block_rows = int(block["rows"])
    calendar = tm.get("calendar") if isinstance(tm.get("calendar"), dict) else None
    bands: Dict[str, Any] = rules.get("bands") if isinstance(rules.get("bands"), dict) else {}
    if not bands:
        bands = {"default": {"row_offset": 0, "max_entries": block_rows}}
    policy = rules.get("policy") if isinstance(rules.get("policy"), dict) else {}
    value_number_format = str(policy.get("value_number_format") or "") or None

    key_to_block: Dict[str, Dict[str, Any]] = {}
    for b in tm["blocks"]:
        key = _norm_key(b.get("key"))
        if key:
            key_to_block.setdefault(key, b)

    zones = [z for z in (tm.get("formula_zones") or []) if isinstance(z, dict)]
    formula_zone_min = min((int(z["col_start"]) for z in zones), default=0)
    templates = [t for t in (rules.get("formula_templates") or []) if isinstance(t, dict)]
    template_cols = {
        _col_to_index(str(t.get("col") or "").strip().upper())
        for t in templates
        if _COL_RE.match(str(t.get("col") or "").strip().upper())
    }

    cell_writes: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    warnings: List[str] = []
    per_key_numeric_sum: Dict[str, float] = {}
    keys_seen: set[str] = set()

    cell_writes.extend(_month_writes(tm, sheet, month_label))

    for idx, record in enumerate(records or []):
        if not isinstance(record, dict):
            dropped.append({"index": idx, "reason": "记录必须是对象"})
            continue
        key = _norm_key(record.get("key"))
        blk = key_to_block.get(key)
        if blk is None:
            dropped.append({"index": idx, "key": key, "reason": "键不在模板块清单中"})
            continue
        keys_seen.add(key)
        top = int(blk["top"])

        if isinstance(record.get("cells"), list):
            for cidx, spec in enumerate(record["cells"]):
                if not isinstance(spec, dict):
                    dropped.append({"index": idx, "key": key, "reason": f"cells[{cidx}] 非对象"})
                    continue
                col = _resolve_col(spec)
                row_offset = int(spec.get("row_offset") or 0)
                if row_offset < 0 or row_offset >= block_rows:
                    dropped.append(
                        {
                            "index": idx,
                            "key": key,
                            "reason": f"cells[{cidx}] row_offset 越块：{row_offset}",
                        }
                    )
                    continue
                write: Dict[str, Any] = {
                    "sheet": sheet,
                    "row": top + row_offset,
                    "col": col,
                    "value": spec.get("value"),
                }
                if spec.get("number_format"):
                    write["number_format"] = str(spec["number_format"])
                if spec.get("value_type"):
                    write["value_type"] = str(spec["value_type"])
                cell_writes.append(write)
                if isinstance(spec.get("value"), (int, float)) and not isinstance(
                    spec.get("value"), bool
                ):
                    per_key_numeric_sum[key] = round(
                        per_key_numeric_sum.get(key, 0.0) + float(spec["value"]), 4
                    )
            continue

        day = record.get("day")
        if day is None:
            dropped.append({"index": idx, "key": key, "reason": "记录缺少 day 或 cells"})
            continue
        if calendar is None:
            raise CompileError(
                "记录含 day 但 rules.template_map.calendar 为空：请先补日历定义或改用 cells 直写"
            )
        try:
            day = int(day)
        except (TypeError, ValueError):
            dropped.append(
                {"index": idx, "key": key, "reason": f"day 非整数：{record.get('day')!r}"}
            )
            continue
        day_count = int(calendar.get("day_count") or 0)
        if day < 1 or day > day_count:
            dropped.append(
                {"index": idx, "key": key, "reason": f"day 越界：{day}（1..{day_count}）"}
            )
            continue

        band_name = _norm_key(record.get("band")) or "default"
        band = bands.get(band_name)
        if not isinstance(band, dict):
            dropped.append(
                {
                    "index": idx,
                    "key": key,
                    "reason": f"band 未定义：{band_name!r}（可用 {sorted(bands)}）",
                }
            )
            continue
        row_offset = int(band.get("row_offset") or 0)
        max_entries = int(band.get("max_entries") or 1)

        anchor = int(calendar["anchor_col"])
        slots = int(calendar.get("slots_per_day") or 1)
        layout = str(calendar.get("layout") or ("symbol_value" if slots >= 2 else "value"))
        symbol_col = anchor + (day - 1) * slots
        if (
            formula_zone_min
            and symbol_col + (1 if layout == "symbol_value" else 0) >= formula_zone_min
        ):
            dropped.append(
                {
                    "index": idx,
                    "key": key,
                    "reason": f"day={day} 槽列进入公式区（col≥{formula_zone_min}）",
                }
            )
            continue

        entries = record.get("entries")
        if not isinstance(entries, list) or not entries:
            dropped.append({"index": idx, "key": key, "reason": "entries 缺失或为空"})
            continue
        if len(entries) > max_entries:
            warnings.append(
                f"记录#{idx} key={key} day={day} band={band_name} entries={len(entries)} 超上限 {max_entries}，截断"
            )
            entries = entries[:max_entries]
        for eidx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            row = top + row_offset + eidx
            if row >= top + block_rows:
                dropped.append(
                    {
                        "index": idx,
                        "key": key,
                        "reason": f"entries[{eidx}] 行越块（band={band_name}）",
                    }
                )
                break
            value = entry.get("value")
            if layout == "symbol_value":
                cell_writes.append(
                    {"sheet": sheet, "row": row, "col": symbol_col, "value": entry.get("symbol")}
                )
                value_write: Dict[str, Any] = {
                    "sheet": sheet,
                    "row": row,
                    "col": symbol_col + 1,
                    "value": value,
                }
                if value_number_format and isinstance(value, (int, float)):
                    value_write["number_format"] = value_number_format
                cell_writes.append(value_write)
            else:
                value_write = {"sheet": sheet, "row": row, "col": symbol_col, "value": value}
                if value_number_format and isinstance(value, (int, float)):
                    value_write["number_format"] = value_number_format
                cell_writes.append(value_write)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                per_key_numeric_sum[key] = round(
                    per_key_numeric_sum.get(key, 0.0) + float(value), 4
                )

    # 公式只写「有键」的块（空白备用块不写，行为与模板保持一致）
    keyed_blocks = [b for b in tm["blocks"] if _norm_key(b.get("key"))]
    formula_writes: List[Dict[str, Any]] = []
    for tpl in templates:
        col_text = str(tpl.get("col") or "").strip().upper()
        if not _COL_RE.match(col_text):
            raise CompileError(f"formula_templates.col 非法：{tpl.get('col')!r}")
        for b in keyed_blocks:
            formula = instantiate_formula(tpl, int(b.get("index") or 0))
            if not formula.startswith("="):
                raise CompileError(f"公式模板实例化结果非法（列 {col_text} 块 {b.get('index')}）")
            formula_writes.append(
                {"sheet": sheet, "ref": f"{col_text}{int(b['top'])}", "formula": formula}
            )

    protected_cols = [(z["col_start"], z["col_end"]) for z in zones]
    protected_ranges: List[str] = []
    for col_start, col_end in protected_cols:
        cols = [c for c in range(int(col_start), int(col_end) + 1) if c not in template_cols]
        run_start: Optional[int] = None
        prev = None
        for c in cols + [None]:
            if c is not None and prev is not None and c == prev + 1:
                prev = c
                continue
            if run_start is not None and prev is not None:
                protected_ranges.append(f"{sheet}!{_index_to_col(run_start)}:{_index_to_col(prev)}")
            run_start, prev = c, c

    phases: List[Dict[str, Any]] = []
    clear_zone = tm.get("clear_zone") if isinstance(tm.get("clear_zone"), dict) else None
    if clear_first and clear_zone:
        first_top = int(block["first_top"])
        last_bottom = int(block["first_top"]) + int(block["count"]) * block_rows - 1
        c1 = _index_to_col(int(clear_zone["col_start"]))
        c2 = _index_to_col(int(clear_zone["col_end"]))
        phases.append(
            {"phase": "clear_ranges", "ranges": [f"{sheet}!{c1}{first_top}:{c2}{last_bottom}"]}
        )
    if cell_writes:
        phases.append({"phase": "cell_writes", "writes": cell_writes})
    if formula_writes:
        phases.append({"phase": "formula_writes", "writes": formula_writes})
    retain = tm.get("retain_sheets")
    if isinstance(retain, list) and retain:
        phases.append({"phase": "retain_sheets", "names": [str(n) for n in retain]})
    if not phases:
        raise CompileError("编译结果为空计划：无 clear/cell/formula/retain 任一阶段")

    keys_unmatched = sorted(
        {
            _norm_key(r.get("key"))
            for r in (records or [])
            if isinstance(r, dict) and _norm_key(r.get("key")) not in key_to_block
        }
        - {""}
    )
    blocks_without_records = sorted(k for k in key_to_block.keys() if k not in keys_seen)

    return {
        "plan_version": PLAN_VERSION,
        "template": {"sheet_names": [sheet]},
        "protected_ranges": protected_ranges,
        "phases": phases,
        "expected": {
            "records_in": len(records or []),
            "records_dropped": dropped,
            "keys_matched": len(keys_seen),
            "keys_unmatched_source": keys_unmatched,
            "blocks_without_records": blocks_without_records,
            "cells_planned": len(cell_writes),
            "formulas_planned": len(formula_writes),
            "per_key_numeric_sum": per_key_numeric_sum,
        },
        "meta": {
            "rules_ref": rules_ref(rules),
            "compiler": "excel-rules-map-employee",
            "warnings": warnings,
        },
    }
