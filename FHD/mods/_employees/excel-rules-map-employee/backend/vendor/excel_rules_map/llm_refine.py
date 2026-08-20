"""LLM 精修：拿启发式推断的 rules 草案 + open_questions 让 LLM 回答，机器验证后采纳。

分工铁律：LLM 只做**提议**（语义判断：bands 多带布局、键列语义、clear_zone 边界、
结构兜底），确定性代码做**验证**（越界/自洽检查）——不通过的提议一律拒绝并留痕。
所有采纳/拒绝记录写入 ``rules.evidence.llm``，规则仍是可审查、可固化的数据。

宿主经 ``ctx["call_llm"]`` 注入异步 LLM 通道（messages → {ok, content, error}）；
不可用或 ``payload.use_llm=false`` 时本模块完全旁路，行为与纯启发式一致。
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.mod_sdk.errors import BOUNDARY_ERRORS

CallLLM = Callable[..., Awaitable[Dict[str, Any]]]

_MAX_HEADER_ROWS = 8
_MAX_COLS = 40
_MAX_BLOCK_SAMPLE = 3

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _cells_grid_text(sheet: Dict[str, Any], row_lo: int, row_hi: int, col_hi: int) -> str:
    """表头/块样本区域转紧凑文本网格（LLM 输入）。"""
    index: Dict[Tuple[int, int], Any] = {}
    for c in sheet.get("cells") or []:
        r, col = int(c.get("row") or 0), int(c.get("col") or 0)
        if row_lo <= r <= row_hi and 1 <= col <= col_hi:
            v = c.get("formula") or c.get("value")
            if v is not None and str(v).strip():
                index[(r, col)] = str(v).strip()[:24]
    lines = []
    for r in range(row_lo, row_hi + 1):
        cells = [f"c{col}={index[(r, col)]!r}" for col in range(1, col_hi + 1) if (r, col) in index]
        if cells:
            lines.append(f"r{r}: " + " ".join(cells))
    return "\n".join(lines[:60])


def build_refine_prompt(sheet: Dict[str, Any], rules: Dict[str, Any]) -> List[Dict[str, str]]:
    tm = rules["template_map"]
    block = tm["block"]
    header_grid = _cells_grid_text(
        sheet,
        1,
        min(tm["header_rows"], _MAX_HEADER_ROWS),
        min(int(sheet.get("max_column") or 0), _MAX_COLS),
    )
    tops = [b["top"] for b in tm["blocks"][:_MAX_BLOCK_SAMPLE]]
    block_grids = []
    for t in tops:
        block_grids.append(
            f"[块 top={t}]\n"
            + _cells_grid_text(
                sheet, t, t + block["rows"] - 1, min(int(sheet.get("max_column") or 0), _MAX_COLS)
            )
        )
    detection = {
        "block": block,
        "key_col": tm.get("key_col"),
        "calendar": tm.get("calendar"),
        "formula_zones": tm.get("formula_zones"),
        "clear_zone": tm.get("clear_zone"),
        "month_cells": tm.get("month_cells"),
    }
    system = (
        "你是 Excel 模板结构分析助手。启发式算法已给出结构检测结果，你需要基于表格文本样本"
        "回答遗留问题，仅输出 JSON（不要多余文字），schema："
        '{"bands": {"<带名>": {"row_offset": int, "max_entries": int}} | null,'
        ' "key_col": int | null, "clear_zone": {"col_start": int, "col_end": int} | null,'
        ' "notes": [str]}。'
        "规则：bands 描述每个人员块内不同数据带（如上午/下午/夜班）各自起始行偏移（0-based）与"
        "每带最多条目行数；看不出多带就返回 null 用默认。不确定的字段一律 null，禁止编造。"
    )
    user = (
        f"检测结果：{json.dumps(detection, ensure_ascii=False)}\n\n"
        f"待回答问题：{json.dumps(rules['evidence']['open_questions'], ensure_ascii=False)}\n\n"
        f"表头区文本：\n{header_grid}\n\n" + "\n\n".join(block_grids)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _parse_llm_json(content: str) -> Optional[Dict[str, Any]]:
    text = str(content or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _validate_bands(proposal: Any, block_rows: int) -> Tuple[Optional[Dict[str, Any]], str]:
    if not isinstance(proposal, dict) or not proposal:
        return None, "bands 提议为空或非对象"
    out: Dict[str, Any] = {}
    for name, spec in proposal.items():
        if not str(name).strip() or not isinstance(spec, dict):
            return None, f"band {name!r} 定义非法"
        try:
            row_offset = int(spec.get("row_offset"))
            max_entries = int(spec.get("max_entries"))
        except (TypeError, ValueError):
            return None, f"band {name!r} row_offset/max_entries 非整数"
        if row_offset < 0 or row_offset >= block_rows:
            return None, f"band {name!r} row_offset={row_offset} 越块（块高 {block_rows}）"
        if max_entries < 1 or row_offset + max_entries > block_rows:
            return None, f"band {name!r} row_offset+max_entries 超出块高"
        out[str(name).strip()] = {"row_offset": row_offset, "max_entries": max_entries}
    return out, ""


def _validate_key_col(
    proposal: Any, sheet: Dict[str, Any], tops: List[int], max_col: int
) -> Tuple[Optional[int], str]:
    try:
        col = int(proposal)
    except (TypeError, ValueError):
        return None, "key_col 非整数"
    if col < 1 or col > max_col:
        return None, f"key_col={col} 超出列范围"
    index = {(int(c["row"]), int(c["col"])): c for c in sheet.get("cells") or [] if c.get("row")}
    non_empty = sum(1 for t in tops if str((index.get((t, col)) or {}).get("value") or "").strip())
    if not tops or non_empty / len(tops) < 0.3:
        return None, f"key_col={col} 块首行文本覆盖率过低（{non_empty}/{len(tops)}）"
    return col, ""


def _validate_clear_zone(
    proposal: Any, formula_zones: List[Dict[str, Any]], max_col: int
) -> Tuple[Optional[Dict[str, int]], str]:
    if not isinstance(proposal, dict):
        return None, "clear_zone 非对象"
    try:
        c1, c2 = int(proposal.get("col_start")), int(proposal.get("col_end"))
    except (TypeError, ValueError):
        return None, "clear_zone 列号非整数"
    if c1 < 1 or c2 < c1 or c2 > max_col:
        return None, f"clear_zone 列范围非法：{c1}..{c2}"
    for z in formula_zones or []:
        if c1 <= int(z["col_end"]) and c2 >= int(z["col_start"]):
            return None, f"clear_zone {c1}..{c2} 与公式区 {z['col_start']}..{z['col_end']} 重叠"
    return {"col_start": c1, "col_end": c2}, ""


async def llm_refine_rules(
    rules: Dict[str, Any],
    sheet: Dict[str, Any],
    call_llm: CallLLM,
) -> Dict[str, Any]:
    """就地精修 rules（返回同一对象）；全部采纳/拒绝证据写入 evidence.llm。"""
    tm = rules["template_map"]
    block_rows = int(tm["block"]["rows"])
    tops = [int(b["top"]) for b in tm["blocks"]]
    max_col = int(sheet.get("max_column") or 0)
    evidence: Dict[str, Any] = {"used": True, "adopted": [], "rejected": [], "notes": []}
    rules["evidence"]["llm"] = evidence

    try:
        resp = await call_llm(
            build_refine_prompt(sheet, rules),
            max_tokens=1200,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        evidence["rejected"].append({"field": "*", "reason": f"LLM 调用异常：{exc}"})
        return rules
    if not resp or not resp.get("ok"):
        evidence["rejected"].append(
            {"field": "*", "reason": f"LLM 不可用：{(resp or {}).get('error') or 'no response'}"}
        )
        return rules
    proposal = _parse_llm_json(str(resp.get("content") or ""))
    if proposal is None:
        evidence["rejected"].append({"field": "*", "reason": "LLM 输出无法解析为 JSON"})
        return rules

    notes = proposal.get("notes")
    if isinstance(notes, list):
        evidence["notes"] = [str(n)[:200] for n in notes[:8]]

    resolved: List[str] = []

    if proposal.get("bands") is not None:
        bands, why = _validate_bands(proposal.get("bands"), block_rows)
        if bands is not None:
            rules["bands"] = bands
            evidence["adopted"].append({"field": "bands", "value": bands})
            resolved.append("bands")
        else:
            evidence["rejected"].append({"field": "bands", "reason": why})

    if proposal.get("key_col") is not None and tm.get("key_col") is None:
        key_col, why = _validate_key_col(proposal.get("key_col"), sheet, tops, max_col)
        if key_col is not None:
            tm["key_col"] = key_col
            index = {
                (int(c["row"]), int(c["col"])): c for c in sheet.get("cells") or [] if c.get("row")
            }
            for i, b in enumerate(tm["blocks"]):
                b["key"] = str(
                    (index.get((int(b["top"]), key_col)) or {}).get("value") or ""
                ).strip()
            evidence["adopted"].append({"field": "key_col", "value": key_col})
            resolved.append("键列")
        else:
            evidence["rejected"].append({"field": "key_col", "reason": why})

    if proposal.get("clear_zone") is not None:
        zone, why = _validate_clear_zone(
            proposal.get("clear_zone"), tm.get("formula_zones") or [], max_col
        )
        if zone is not None:
            tm["clear_zone"] = zone
            evidence["adopted"].append({"field": "clear_zone", "value": zone})
            resolved.append("clear_zone")
        else:
            evidence["rejected"].append({"field": "clear_zone", "reason": why})

    if resolved:
        remaining = []
        for q in rules["evidence"]["open_questions"]:
            if "bands" in q and "bands" in resolved:
                continue
            if "clear_zone" in q and "clear_zone" in resolved:
                continue
            if "键列" in q and "键列" in resolved:
                continue
            remaining.append(q)
        remaining.append(
            f"LLM 已提议并通过机器验证：{resolved}（详见 evidence.llm，仍建议人工抽查）"
        )
        rules["evidence"]["open_questions"] = remaining
    return rules
