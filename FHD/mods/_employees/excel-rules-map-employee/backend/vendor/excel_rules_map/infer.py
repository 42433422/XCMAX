"""模板画像推断：从读取员的 workbook.json 推断可复用规则 rules.json（提案）。

零领域知识的通用推断，覆盖「重复行块 + 日历网格 + 侧栏公式」类模板
（太阳鸟考勤表是首个校准样本，但算法不含任何考勤语义）：

- 块结构：竖向合并单元格的周期性（高度众数 + 起点等差链），跨列投票取支持列最多的
  (块高, 首块行)；如太阳鸟 A/B/C 三列 6 行合并 × 151 块。
- 键列：块首行文本「覆盖率 × 唯一率」评分最高的列（如 C 列姓名）。
- 日历锚：表头区找 1..N 横向等差数字序列（如第 3 行 col5 起步进 2 → 日×2 槽）。
- 公式区：块首行公式覆盖率高的连续列区间（如 BR..CG）。
- 公式模板：同列跨块公式按数字 token 拟合——骨架必须全等，数字恒定为常数、
  等差则参数化为 base + step × block_index（如 ROWS($1:1)→($1:7) 步进 6）。
- 月份格：表头区 1900..2100 整数 → year 格，同行右侧 1..12 → month 格。

产出的 rules.json 是**提案**：evidence 携带置信度与 open_questions，
bands / policy 等领域参数留给人或领域方补充后固化。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

RULES_VERSION = 1

_MIN_BLOCKS = 3
_MIN_CALENDAR_DAYS = 14
_FORMULA_COVERAGE_MIN = 0.6
_FIT_SAMPLE_BLOCKS = 6

_RANGE_RE = re.compile(r"^([A-Z]{1,3})(\d+):([A-Z]{1,3})(\d+)$")


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


def _vertical_merges(sheet: Dict[str, Any]) -> List[Tuple[int, int, int]]:
    """merged_ranges → [(col, top, height)]，仅单列竖向合并。"""
    out: List[Tuple[int, int, int]] = []
    for token in sheet.get("merged_ranges") or []:
        m = _RANGE_RE.match(str(token).strip())
        if not m:
            continue
        c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        if c1 == c2 and r2 > r1:
            out.append((_col_to_index(c1), r1, r2 - r1 + 1))
    return out


def _longest_arithmetic_chain(tops: List[int], step: int) -> Tuple[int, int]:
    """已排序 tops 中步长为 step 的最长链 → (链长, 链首)。"""
    tops_set = set(tops)
    best_len, best_start = 0, 0
    for t in tops:
        if t - step in tops_set:
            continue
        length = 1
        cur = t
        while cur + step in tops_set:
            cur += step
            length += 1
        if length > best_len:
            best_len, best_start = length, t
    return best_len, best_start


def _detect_blocks(
    sheet: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """块结构：(块高, 首块行) 候选按支持列数投票，平手取更大块高。"""
    merges = _vertical_merges(sheet)
    # (height, chain_start) -> {cols 支持列, chain_len 最长链}
    candidates: Dict[Tuple[int, int], Dict[str, Any]] = {}
    by_col_height: Dict[Tuple[int, int], List[int]] = {}
    for col, top, height in merges:
        by_col_height.setdefault((col, height), []).append(top)
    for (col, height), tops in by_col_height.items():
        tops = sorted(tops)
        chain_len, chain_start = _longest_arithmetic_chain(tops, height)
        if chain_len < _MIN_BLOCKS:
            continue
        key = (height, chain_start)
        slot = candidates.setdefault(key, {"cols": set(), "chain_len": 0})
        slot["cols"].add(col)
        slot["chain_len"] = max(slot["chain_len"], chain_len)
    if not candidates:
        return None, {"confidence": 0.0, "note": "未发现周期性竖向合并，无法推断行块结构"}

    def _rank(item: Tuple[Tuple[int, int], Dict[str, Any]]):
        (height, _start), meta = item
        return (len(meta["cols"]), height, meta["chain_len"])

    (height, first_top), meta = max(candidates.items(), key=_rank)
    count = meta["chain_len"]
    confidence = min(1.0, 0.5 + 0.1 * len(meta["cols"]) + min(count, 20) * 0.02)
    return (
        {"rows": height, "first_top": first_top, "count": count},
        {
            "confidence": round(confidence, 2),
            "support_cols": sorted(_index_to_col(c) for c in meta["cols"]),
        },
    )


def _cells_index(sheet: Dict[str, Any]) -> Dict[Tuple[int, int], Dict[str, Any]]:
    return {
        (int(c["row"]), int(c["col"])): c
        for c in sheet.get("cells") or []
        if isinstance(c, dict) and c.get("row") and c.get("col")
    }


def _block_tops(block: Dict[str, Any]) -> List[int]:
    return [block["first_top"] + i * block["rows"] for i in range(block["count"])]


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _detect_key_col(
    cells: Dict[Tuple[int, int], Dict[str, Any]],
    tops: List[int],
    max_col: int,
) -> Tuple[Optional[int], float]:
    """块首行「文本覆盖率 × 唯一率」最高的列为键列。"""
    best_col, best_score = None, 0.0
    for col in range(1, min(max_col, 12) + 1):
        values = [_text((cells.get((t, col)) or {}).get("value")) for t in tops]
        non_empty = [v for v in values if v]
        if not non_empty:
            continue
        coverage = len(non_empty) / len(tops)
        uniqueness = len(set(non_empty)) / len(non_empty)
        score = coverage * uniqueness
        if score > best_score:
            best_col, best_score = col, score
    if best_col is None or best_score < 0.5:
        return None, round(best_score, 2)
    return best_col, round(best_score, 2)


def _int_value(cell: Optional[Dict[str, Any]]) -> Optional[int]:
    if not cell:
        return None
    v = cell.get("value")
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        t = v.strip()
        if t.isdigit():
            return int(t)
    return None


def _detect_calendar(
    cells: Dict[Tuple[int, int], Dict[str, Any]],
    header_rows: int,
    max_col: int,
) -> Optional[Dict[str, Any]]:
    """表头区找 1..N 横向等差序列：anchor 列、每日槽数、天数。"""
    best: Optional[Dict[str, Any]] = None
    for row in range(1, header_rows + 1):
        for col in range(1, max_col + 1):
            if _int_value(cells.get((row, col))) != 1:
                continue
            for step in (1, 2, 3, 4):
                days = 1
                while True:
                    nxt = _int_value(cells.get((row, col + days * step)))
                    if nxt != days + 1:
                        break
                    days += 1
                if days >= _MIN_CALENDAR_DAYS and (best is None or days > best["day_count"]):
                    best = {
                        "anchor_col": col,
                        "slots_per_day": step,
                        "day_count": days,
                        "header_row": row,
                        "layout": "symbol_value" if step >= 2 else "value",
                    }
    return best


def _detect_month_cells(
    cells: Dict[Tuple[int, int], Dict[str, Any]],
    header_rows: int,
    max_col: int,
    calendar_row: Optional[int],
) -> List[Dict[str, str]]:
    for row in range(1, header_rows + 1):
        if calendar_row is not None and row == calendar_row:
            continue
        year_col = None
        for col in range(1, max_col + 1):
            v = _int_value(cells.get((row, col)))
            if v is not None and 1900 <= v <= 2100:
                year_col = col
                break
        if year_col is None:
            continue
        for col in range(year_col + 1, max_col + 1):
            v = _int_value(cells.get((row, col)))
            if v is not None and 1 <= v <= 12:
                return [
                    {"ref": f"{_index_to_col(year_col)}{row}", "part": "year"},
                    {"ref": f"{_index_to_col(col)}{row}", "part": "month"},
                ]
    return []


def _active_tops(
    cells: Dict[Tuple[int, int], Dict[str, Any]],
    tops: List[int],
    key_col: Optional[int],
    max_col: int,
) -> List[int]:
    """有效块（在住块）：键列非空；模板常带大量空白备用块，会稀释公式/键覆盖率。

    键列缺失时退化为「块首行存在公式或 ≥2 个非空格」。
    """
    if key_col is not None:
        active = [t for t in tops if _text((cells.get((t, key_col)) or {}).get("value"))]
        if active:
            return active
    active = []
    for t in tops:
        non_empty = 0
        has_formula = False
        for col in range(1, max_col + 1):
            cell = cells.get((t, col))
            if not cell:
                continue
            if str(cell.get("formula") or "").startswith("="):
                has_formula = True
                break
            if _text(cell.get("value")):
                non_empty += 1
        if has_formula or non_empty >= 2:
            active.append(t)
    return active or tops


def _detect_formula_zones(
    cells: Dict[Tuple[int, int], Dict[str, Any]],
    sample_tops: List[int],
    max_col: int,
) -> List[Dict[str, int]]:
    """块首行公式列 → 合并连续区间。

    真实模板常只给部分块拉了公式（如太阳鸟 80 个在住块仅前 27 块有侧栏
    SUMIF——compile 全量重写正是要补齐它），因此判定为「覆盖率 ≥60%」**或**
    「绝对样本 ≥ max(3, 20%)」，孤立手写公式（1~2 格）仍被过滤。
    """
    sample = sample_tops
    if not sample:
        return []
    abs_min = max(_MIN_BLOCKS, -(-len(sample) // 5))  # ceil(20%)
    formula_cols: List[int] = []
    for col in range(1, max_col + 1):
        hits = sum(
            1
            for t in sample
            if str((cells.get((t, col)) or {}).get("formula") or "").startswith("=")
        )
        if hits / len(sample) >= _FORMULA_COVERAGE_MIN or hits >= abs_min:
            formula_cols.append(col)
    zones: List[Dict[str, int]] = []
    for col in formula_cols:
        if zones and col == zones[-1]["col_end"] + 1:
            zones[-1]["col_end"] = col
        else:
            zones.append({"col_start": col, "col_end": col})
    return zones


_NUM_SPLIT_RE = re.compile(r"(\d+)")


def _fit_formula_templates(
    cells: Dict[Tuple[int, int], Dict[str, Any]],
    tops: List[int],
    zones: List[Dict[str, int]],
    *,
    block_rows: int,
    first_top: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """同列跨块公式拟合：骨架全等 + 数字 token 常数/等差（按块序号）。

    等差以**全局块序号**（(top-first_top)//block_rows）为自变量，
    这样即使公式只存在于部分块（如前 27 个在住块），实例化到任意块都成立。
    """
    templates: List[Dict[str, Any]] = []
    open_questions: List[str] = []
    if len(tops) < 2:
        return templates, ["块数不足 2，无法拟合公式模板"]
    for zone in zones:
        for col in range(zone["col_start"], zone["col_end"] + 1):
            letter = _index_to_col(col)
            formulas: List[str] = []
            indices: List[int] = []
            for t in tops:
                f = str((cells.get((t, col)) or {}).get("formula") or "")
                if f.startswith("="):
                    formulas.append(f)
                    indices.append((t - first_top) // block_rows)
                if len(formulas) >= _FIT_SAMPLE_BLOCKS:
                    break
            if len(formulas) < 2:
                open_questions.append(f"列 {letter} 公式样本不足，未拟合（该列将保持保护）")
                continue
            parts_list = [_NUM_SPLIT_RE.split(f) for f in formulas]
            skeletons = [parts[0::2] for parts in parts_list]
            if any(s != skeletons[0] for s in skeletons[1:]):
                open_questions.append(f"列 {letter} 公式骨架跨块不一致，未拟合（该列将保持保护）")
                continue
            nums_list = [[int(n) for n in parts[1::2]] for parts in parts_list]
            if any(len(n) != len(nums_list[0]) for n in nums_list[1:]):
                open_questions.append(f"列 {letter} 公式数字位数不一致，未拟合")
                continue
            params: List[Dict[str, Any]] = []
            fit_ok = True
            for pos in range(len(nums_list[0])):
                series = [nums[pos] for nums in nums_list]
                if all(v == series[0] for v in series):
                    params.append({"kind": "const", "value": series[0]})
                    continue
                # 以全局块序号为自变量：v = base + step * block_index
                di = indices[1] - indices[0]
                dv = series[1] - series[0]
                if di <= 0 or dv % di != 0:
                    fit_ok = False
                    break
                step = dv // di
                base = series[0] - step * indices[0]
                if step != 0 and all(
                    series[i] == base + step * indices[i] for i in range(len(series))
                ):
                    params.append({"kind": "linear", "base": base, "step": step})
                else:
                    fit_ok = False
                    break
            if not fit_ok:
                open_questions.append(f"列 {letter} 数字序列非等差，未拟合（该列将保持保护）")
                continue
            templates.append(
                {
                    "col": letter,
                    "skeleton": skeletons[0],
                    "params": params,
                    "sample": formulas[0],
                    "verified_blocks": len(formulas),
                }
            )
    return templates, open_questions


def instantiate_formula(template: Dict[str, Any], block_index: int) -> str:
    """由骨架 + 参数生成第 block_index（0-based）块的公式串。"""
    skeleton: List[str] = list(template.get("skeleton") or [])
    params: List[Dict[str, Any]] = list(template.get("params") or [])
    out: List[str] = []
    for i, seg in enumerate(skeleton):
        out.append(seg)
        if i < len(params):
            p = params[i]
            if p.get("kind") == "linear":
                out.append(str(int(p["base"]) + int(p["step"]) * block_index))
            else:
                out.append(str(int(p["value"])))
    return "".join(out)


def infer_rules(
    workbook: Dict[str, Any],
    *,
    sheet_name: Optional[str] = None,
    source_name: str = "",
) -> Dict[str, Any]:
    """workbook.json（读取员输出）→ rules.json 提案。"""
    sheets = workbook.get("sheets") or []
    if not sheets:
        raise ValueError("workbook.json 缺少 sheets，无法推断")
    sheet = None
    if sheet_name:
        sheet = next((s for s in sheets if s.get("name") == sheet_name), None)
        if sheet is None:
            raise ValueError(
                f"未找到 sheet：{sheet_name!r}；可用 {[s.get('name') for s in sheets]}"
            )
    else:
        sheet = max(sheets, key=lambda s: int(s.get("cell_count") or 0))

    confidences: Dict[str, float] = {}
    open_questions: List[str] = []

    block, block_meta = _detect_blocks(sheet)
    if block is None:
        raise ValueError(str(block_meta.get("note") or "无法推断行块结构"))
    confidences["block"] = block_meta["confidence"]

    header_rows = block["first_top"] - 1
    cells = _cells_index(sheet)
    tops = _block_tops(block)
    max_col = int(sheet.get("max_column") or 0)

    key_col, key_score = _detect_key_col(cells, tops, max_col)
    if key_col is None:
        open_questions.append(
            "未能确定键列（块首行无高区分度文本列），请人工指定 template_map.key_col"
        )

    # 模板常带空白备用块（如太阳鸟 151 块仅 27 块在住）：结构检测用全部块，
    # 键列置信/公式检测用有效块，避免空块稀释覆盖率。
    active_tops = _active_tops(cells, tops, key_col, max_col)
    if key_col is not None:
        _, key_score = (key_col, _detect_key_col(cells, active_tops, max_col)[1])
    confidences["key_col"] = key_score
    if len(active_tops) < len(tops):
        confidences["active_blocks"] = round(len(active_tops) / len(tops), 2)

    calendar = _detect_calendar(cells, header_rows, max_col)
    if calendar is None:
        open_questions.append("未发现日历数字序列；如需日历网格回填请人工补 template_map.calendar")
    else:
        confidences["calendar"] = 0.9

    month_cells = _detect_month_cells(
        cells, header_rows, max_col, calendar["header_row"] if calendar else None
    )
    if month_cells:
        confidences["month_cells"] = 0.6

    zones = _detect_formula_zones(cells, active_tops, max_col)
    templates, fit_questions = _fit_formula_templates(
        cells,
        active_tops,
        zones,
        block_rows=block["rows"],
        first_top=block["first_top"],
    )
    open_questions.extend(fit_questions)
    if zones:
        confidences["formula_zones"] = 0.85

    clear_zone = None
    if calendar and zones:
        clear_zone = {
            "col_start": calendar["anchor_col"],
            "col_end": min(z["col_start"] for z in zones) - 1,
        }
        confidences["clear_zone"] = 0.6
        open_questions.append(
            "clear_zone 由日历锚列与公式区推导，请确认是否包含侧栏非公式列（如序号/姓名列）"
        )

    blocks_out = []
    for i, top in enumerate(tops):
        key = _text((cells.get((top, key_col)) or {}).get("value")) if key_col else ""
        blocks_out.append({"index": i, "top": top, "key": key})

    open_questions.append("bands 为默认单带布局；多带（如上午/下午/夜班分行）请人工定义后固化")

    return {
        "rules_version": RULES_VERSION,
        "domain": "generic-template-grid",
        "template_map": {
            "sheet": str(sheet.get("name") or ""),
            "header_rows": header_rows,
            "block": block,
            "key_col": key_col,
            "blocks": blocks_out,
            "calendar": calendar,
            "formula_zones": zones,
            "clear_zone": clear_zone,
            "month_cells": month_cells,
            "retain_sheets": None,
        },
        "bands": {"default": {"row_offset": 0, "max_entries": block["rows"]}},
        "formula_templates": templates,
        "policy": {"value_number_format": "0.0"},
        "evidence": {
            "source": source_name,
            "inferred_at": datetime.now(UTC).isoformat(),
            "support_cols": block_meta.get("support_cols") or [],
            "confidences": confidences,
            "open_questions": open_questions,
        },
    }
