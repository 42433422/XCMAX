"""金样反读与 records 对账：固化循环的确定性判据。

- ``extract_records_from_workbook``：把金样（人工做好的正确输出，经读取员转
  workbook.json）按 rules 的 calendar/bands/blocks **逆映射**回期望 records——
  与 ``compile_plan`` 的正向映射对称，纯确定性。
- ``diff_records``：LLM 固化脚本产出的 records 与金样期望 records 按
  (key, day, band) 对齐逐条比对（符号精确、数值容差），产出可喂回 LLM 的
  结构化差异样本。

金样是「规则可固化」的最终裁判：LLM 写的转换脚本只有在金样对账全绿后才允许固化。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_NUM_TOL = 1e-6
_MAX_DIFF_SAMPLES = 12


def _cells_index(sheet: Dict[str, Any]) -> Dict[Tuple[int, int], Any]:
    out: Dict[Tuple[int, int], Any] = {}
    for c in sheet.get("cells") or []:
        if isinstance(c, dict) and c.get("row") and c.get("col"):
            out[(int(c["row"]), int(c["col"]))] = c.get("value")
    return out


def _norm_symbol(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def extract_records_from_workbook(
    workbook: Dict[str, Any],
    rules: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """金样 workbook.json + rules → 期望 records（compile 正向映射的逆）。"""
    tm = rules.get("template_map") or {}
    calendar = tm.get("calendar")
    if not isinstance(calendar, dict):
        raise ValueError("rules.template_map.calendar 缺失，无法反读金样")
    bands = rules.get("bands")
    if not isinstance(bands, dict) or not bands:
        raise ValueError("rules.bands 缺失，无法反读金样")
    sheet_name = str(tm.get("sheet") or "")
    sheet = next((s for s in (workbook.get("sheets") or []) if s.get("name") == sheet_name), None)
    if sheet is None:
        raise ValueError(f"金样中找不到 sheet：{sheet_name!r}")
    cells = _cells_index(sheet)

    anchor = int(calendar["anchor_col"])
    slots = int(calendar.get("slots_per_day") or 1)
    day_count = int(calendar.get("day_count") or 0)
    layout = str(calendar.get("layout") or ("symbol_value" if slots >= 2 else "value"))

    records: List[Dict[str, Any]] = []
    for block in tm.get("blocks") or []:
        key = str(block.get("key") or "").strip()
        if not key:
            continue
        top = int(block["top"])
        for day in range(1, day_count + 1):
            symbol_col = anchor + (day - 1) * slots
            for band_name, band in bands.items():
                row_offset = int(band.get("row_offset") or 0)
                max_entries = int(band.get("max_entries") or 1)
                entries: List[Dict[str, Any]] = []
                for eidx in range(max_entries):
                    row = top + row_offset + eidx
                    if layout == "symbol_value":
                        symbol = _norm_symbol(cells.get((row, symbol_col)))
                        value = cells.get((row, symbol_col + 1))
                        if not symbol and value is None:
                            continue
                        entries.append(
                            {
                                "symbol": symbol,
                                "value": _as_number(value) if value is not None else None,
                            }
                        )
                    else:
                        value = cells.get((row, symbol_col))
                        if value is None:
                            continue
                        entries.append({"symbol": "", "value": _as_number(value)})
                if entries:
                    records.append(
                        {"key": key, "day": day, "band": str(band_name), "entries": entries}
                    )
    return records


def _slot_map(records: List[Dict[str, Any]]) -> Dict[Tuple[str, int, str], List[Dict[str, Any]]]:
    out: Dict[Tuple[str, int, str], List[Dict[str, Any]]] = {}
    for r in records or []:
        if not isinstance(r, dict):
            continue
        try:
            slot = (
                str(r.get("key") or "").strip(),
                int(r.get("day")),
                str(r.get("band") or "").strip(),
            )
        except (TypeError, ValueError):
            continue
        entries = [e for e in (r.get("entries") or []) if isinstance(e, dict)]
        out.setdefault(slot, []).extend(entries)
    return out


def _entries_equal(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> bool:
    if len(a) != len(b):
        return False
    for ea, eb in zip(a, b):
        if _norm_symbol(ea.get("symbol")) != _norm_symbol(eb.get("symbol")):
            return False
        va, vb = _as_number(ea.get("value")), _as_number(eb.get("value"))
        if va is None and vb is None:
            continue
        if va is None or vb is None:
            return False
        if abs(va - vb) > _NUM_TOL:
            return False
    return True


def diff_records(
    produced: List[Dict[str, Any]],
    expected: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """脚本产出 vs 金样期望：{"ok", "stats", "samples"}；samples 直接可喂回 LLM。"""
    got = _slot_map(produced)
    want = _slot_map(expected)
    matched = 0
    mismatched: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    extra: List[Dict[str, Any]] = []

    for slot, want_entries in want.items():
        got_entries = got.get(slot)
        if got_entries is None:
            missing.append({"slot": list(slot), "expected": want_entries})
        elif _entries_equal(got_entries, want_entries):
            matched += 1
        else:
            mismatched.append(
                {"slot": list(slot), "expected": want_entries, "produced": got_entries}
            )
    for slot, got_entries in got.items():
        if slot not in want:
            extra.append({"slot": list(slot), "produced": got_entries})

    ok = not mismatched and not missing and not extra
    return {
        "ok": ok,
        "stats": {
            "expected_slots": len(want),
            "produced_slots": len(got),
            "matched": matched,
            "mismatched": len(mismatched),
            "missing": len(missing),
            "extra": len(extra),
        },
        "samples": {
            "mismatched": mismatched[:_MAX_DIFF_SAMPLES],
            "missing": missing[:_MAX_DIFF_SAMPLES],
            "extra": extra[:_MAX_DIFF_SAMPLES],
        },
    }
