"""Verify proposed document cuts after model grouping; resplit sticky multi-doc ranges.

General heuristics only (no workbook-title hardcodes):
- repeated titled document blocks inside one cut
- multi-order ledger runs (date-like + order-like adjacent columns)
- outbound same-sheet formula references leaving the cut
- circular self-referential formulas (same fail-closed as export)

On stickiness with clear boundaries, autonomy prefers heuristic resplit;
otherwise flag needs_reidentify / fail-closed with a clear Chinese reason.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from openpyxl.utils.cell import (
    column_index_from_string,
    coordinate_from_string,
    get_column_letter,
)

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range

# General title / period-block cues (language-agnostic keywords + Chinese ledger labels).
_TITLE_HINT = re.compile(
    r"(购货明细|回款明细|出货明细|送货单|退货单|出货单|报价单|对账单|明细表|"
    r"invoice|statement|receipt)",
    re.IGNORECASE,
)
_DATEISH = re.compile(
    r"(20\d{2}|19\d{2}).{0,6}(\d{1,2}).{0,6}(\d{1,2})|"
    r"(\d{1,2})\s*月|"
    r"起|至|截止",
)
_ORDER_HEADER = re.compile(
    r"^(订单号|单号|报价单号|出货单号|order\s*number|order\s*no\.?|po\s*#?)$",
    re.IGNORECASE,
)
# Excel serial dates roughly 1990-01-01 .. 2100-01-01
_EXCEL_DATE_LO, _EXCEL_DATE_HI = 32874, 73050
_MIN_ORDER_RUNS_FOR_STICKY = 2
_MIN_TITLE_BLOCKS_FOR_STICKY = 2


def _range_to_a1(c1: int, r1: int, c2: int, r2: int) -> str:
    return f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{r2}"


def _cells_in_fragments(review: dict, fragments: list[dict]) -> list[dict]:
    out: list[dict] = []
    rects = []
    for part in fragments:
        try:
            rects.append((part["sheet"], bounded_range(part["range"])))
        except (TypeError, ValueError, KeyError):
            continue
    for cell in review.get("cells") or []:
        sheet = cell.get("sheet")
        try:
            col_letter, row = coordinate_from_string(cell["cell"])
            col = column_index_from_string(col_letter)
        except (TypeError, ValueError, KeyError):
            continue
        for sheet_name, (c1, r1, c2, r2) in rects:
            if sheet == sheet_name and c1 <= col <= c2 and r1 <= row <= r2:
                out.append(cell)
                break
    return out


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _looks_date_value(value: Any) -> bool:
    """Hard date only: Excel serials, ISO-like dates, or year/month cues — not SKUs."""
    if value is None:
        return False
    num = _as_number(value)
    if num is not None and _EXCEL_DATE_LO <= num <= _EXCEL_DATE_HI:
        return True
    text = str(value).strip()
    if not text or len(text) > 40:
        return False
    # Reject product/SKU tokens like 260-1（背色） that soft-match digit-dash.
    if re.search(r"[A-Za-z]|（|）|\(|\)", text) and not re.search(r"(20\d{2}|19\d{2}|月)", text):
        return False
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}([-/.]\d{1,2})?", text):
        return True
    return bool(_DATEISH.search(text))


def _looks_order_value(value: Any) -> bool:
    if value is None:
        return False
    num = _as_number(value)
    if num is not None:
        # Plain integers used as order ids (not excel dates).
        return not (_EXCEL_DATE_LO <= num <= _EXCEL_DATE_HI) and abs(num) < 1_000_000
    text = str(value).strip()
    if not text or len(text) > 24:
        return False
    if _TITLE_HINT.search(text) or _DATEISH.search(text):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9号\-_/]+", text))


def _is_title_row_text(text: str) -> bool:
    text = text.strip()
    if len(text) < 4 or len(text) > 120:
        return False
    # Footers, totals, and boilerplate contract lines are not document titles.
    if re.search(r"(合计|总计|小计|价税合计|金额合计|一式|协议|联为|签字|法律效力|人民法院)", text):
        return False
    if re.match(r"^\d+[\.、．]", text):
        return False
    if not _TITLE_HINT.search(text):
        return False
    # Period/start cue, or a short standalone document-type title (e.g. 送货单/退货单).
    if bool(_DATEISH.search(text)) or ("起" in text) or ("至" in text):
        return True
    return len(text) <= 40 and bool(
        re.search(
            r"(送货单|退货单|出货单|购货明细|回款明细|报价单|对账单|invoice|receipt)",
            text,
            re.I,
        )
    )


def _is_document_heading_text(text: str) -> bool:
    """Standalone document header — not agreement/meta lines inside one form."""
    primary = (text or "").split("|", 1)[0].strip()
    if len(primary) < 4 or len(primary) > 80:
        return False
    if re.search(r"(销售协议|一式|法律效力|联为|签字|人民法院|如有异议|按期付清)", primary):
        return False
    if re.match(r"^\d+[\.、．]", primary):
        return False
    if re.search(r"(购货单位|联系人：|联系人:|订单编号)", primary) and not re.search(
        r"(送货单|退货单|出货单|购货明细|回款明细)", primary[:24]
    ):
        return False
    return bool(
        re.search(
            r"(送货单|退货单|出货单|购货明细|回款明细|出货明细|报价单|对账单|"
            r"invoice|statement|receipt|delivery)",
            primary,
            re.I,
        )
    )


def _detect_title_blocks(cells: list[dict], sheet: str, c1: int, r1: int, c2: int, r2: int) -> list[dict]:
    """Rows whose leftmost nonempty text looks like a titled document block."""
    by_row: dict[int, list[dict]] = {}
    for cell in cells:
        if cell.get("sheet") != sheet or cell.get("kind") == "formula":
            continue
        col_letter, row = coordinate_from_string(cell["cell"])
        col = column_index_from_string(col_letter)
        if not (c1 <= col <= c2 and r1 <= row <= r2):
            continue
        by_row.setdefault(row, []).append(cell)
    titles: list[dict] = []
    for row in sorted(by_row):
        ordered = sorted(by_row[row], key=lambda c: column_index_from_string(coordinate_from_string(c["cell"])[0]))
        text = str(ordered[0].get("value") or "").strip()
        if _is_title_row_text(text):
            titles.append({"row": row, "text": text[:120], "cell": ordered[0]["cell"]})
    return titles


def _column_values(cells: list[dict], sheet: str, col: int, r1: int, r2: int) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for cell in cells:
        if cell.get("sheet") != sheet:
            continue
        col_letter, row = coordinate_from_string(cell["cell"])
        if column_index_from_string(col_letter) != col or not (r1 <= row <= r2):
            continue
        if cell.get("kind") == "formula":
            continue
        out[row] = cell.get("value")
    return out


def _run_boundaries(keys: list[tuple[int, Any]]) -> list[tuple[int, int, Any]]:
    """keys is sorted (row, key); return inclusive (start,end,key) runs skipping None keys."""
    runs: list[tuple[int, int, Any]] = []
    cur = None
    start = None
    for row, key in keys:
        if key is None:
            if cur is not None:
                runs.append((start, row - 1, cur))
                cur = None
                start = None
            continue
        if key != cur:
            if cur is not None:
                runs.append((start, row - 1, cur))
            cur = key
            start = row
    if cur is not None and start is not None:
        last_row = keys[-1][0]
        runs.append((start, last_row, cur))
    return runs


def _detect_order_ledger_runs(
    cells: list[dict], sheet: str, c1: int, r1: int, c2: int, r2: int
) -> dict | None:
    """Find best adjacent (date-like, order-like) column pair with many distinct runs."""
    best: dict | None = None
    # Also honor explicit 单号 / order headers: value column is header.col, date may be left.
    header_cols: list[int] = []
    for cell in cells:
        if cell.get("sheet") != sheet or cell.get("kind") == "formula":
            continue
        text = str(cell.get("value") or "").strip().rstrip(":：")
        if _ORDER_HEADER.fullmatch(text):
            col_letter, row = coordinate_from_string(cell["cell"])
            col = column_index_from_string(col_letter)
            if c1 <= col <= c2 and r1 <= row <= r2:
                header_cols.append(col)
    candidates = []
    for col in range(c1, c2):
        candidates.append((col, col + 1))
    for hcol in header_cols:
        if hcol - 1 >= c1:
            candidates.append((hcol - 1, hcol))
        if hcol + 1 <= c2:
            candidates.append((hcol, hcol + 1))
    # de-dupe
    seen = set()
    for left, right in candidates:
        if (left, right) in seen:
            continue
        seen.add((left, right))
        left_vals = _column_values(cells, sheet, left, r1, r2)
        right_vals = _column_values(cells, sheet, right, r1, r2)
        rows = sorted(set(left_vals) | set(right_vals))
        if len(rows) < 6:
            continue
        date_hits = sum(1 for r in rows if _looks_date_value(left_vals.get(r)))
        order_hits = sum(1 for r in rows if _looks_order_value(right_vals.get(r)))
        # Try swapped orientation too.
        orientations = [
            (left, right, date_hits, order_hits, left_vals, right_vals),
            (
                right,
                left,
                sum(1 for r in rows if _looks_date_value(right_vals.get(r))),
                sum(1 for r in rows if _looks_order_value(left_vals.get(r))),
                right_vals,
                left_vals,
            ),
        ]
        for dcol, ocol, d_hits, o_hits, dvals, ovals in orientations:
            nonempty = max(1, len(rows))
            # Require a clear date column and a clear order column (majority),
            # and reject pairs where the "date" column is mostly non-dates (e.g. SKUs).
            if d_hits < max(4, int(0.55 * nonempty)) or o_hits < max(4, int(0.55 * nonempty)):
                continue
            order_also_dates = sum(
                1 for r in rows if _looks_date_value(ovals.get(r)) and _looks_order_value(ovals.get(r))
            )
            if order_also_dates > o_hits * 0.5:
                continue
            keyed = []
            for row in rows:
                dv, ov = dvals.get(row), ovals.get(row)
                if (dv is None and ov is None) or not (
                    _looks_date_value(dv) and _looks_order_value(ov)
                ):
                    keyed.append((row, None))
                else:
                    keyed.append((row, (str(dv), str(ov))))
            runs = [run for run in _run_boundaries(keyed) if run[2] is not None]
            if len(runs) < _MIN_ORDER_RUNS_FOR_STICKY:
                continue
            # Prefer real Excel-serial / year-bearing date columns over SKU
            # false positives that inflate run_count via soft gaps.
            serial_hits = sum(
                1
                for r in rows
                if (_as_number(dvals.get(r)) is not None)
                and _EXCEL_DATE_LO <= float(_as_number(dvals.get(r))) <= _EXCEL_DATE_HI
            )
            year_hits = sum(
                1
                for r in rows
                if isinstance(dvals.get(r), str)
                and re.search(r"(20\d{2}|19\d{2})", str(dvals.get(r)))
            )
            date_quality = serial_hits * 5 + year_hits * 3 + d_hits
            # Hard separators = distinct (date, order) keys on a quality date col.
            # Do not reward soft over-splits from weak date columns.
            score = date_quality * 20 + min(len(runs), 30) + o_hits
            cand = {
                "sheet": sheet,
                "date_col": dcol,
                "order_col": ocol,
                "run_count": len(runs),
                "runs": [{"row_start": a, "row_end": b, "key": k} for a, b, k in runs],
                "score": score,
                "date_quality": date_quality,
            }
            if best is None or cand["score"] > best["score"]:
                best = cand
    return best


def _formula_outbound_and_circular(
    cells: list[dict], fragments: list[dict]
) -> dict:
    """Scan formula cells inside fragments for outbound same-sheet refs and obvious self-SUM cycles."""
    rects_by_sheet: dict[str, list[tuple[int, int, int, int]]] = {}
    for part in fragments:
        try:
            rects_by_sheet.setdefault(part["sheet"], []).append(bounded_range(part["range"]))
        except (TypeError, ValueError, KeyError):
            continue

    def selected(sheet: str, col: int, row: int) -> bool:
        return any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in rects_by_sheet.get(sheet, []))

    outbound: list[dict] = []
    circular: list[dict] = []
    cell_ref = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d+)(?::\$?([A-Za-z]{1,3})\$?(\d+))?")
    for cell in cells:
        if cell.get("kind") != "formula":
            continue
        sheet = cell["sheet"]
        formula = str(cell.get("value") or "")
        address = cell["cell"]
        # Self-inclusive SUM/AVERAGE style: =SUM(C70:C79) where address is C79
        m = re.match(
            r"^=\s*(SUM|AVERAGE|MIN|MAX|COUNT|COUNTA)\s*\(\s*(\$?[A-Za-z]{1,3}\$?\d+:\$?[A-Za-z]{1,3}\$?\d+)\s*\)\s*$",
            formula,
            re.IGNORECASE,
        )
        if m:
            try:
                c1, r1, c2, r2 = bounded_range(m.group(2).replace("$", ""))
                acol, arow = coordinate_from_string(address)
                acol_i = column_index_from_string(acol)
                if c1 <= acol_i <= c2 and r1 <= arow <= r2:
                    circular.append(
                        {
                            "sheet": sheet,
                            "cell": address,
                            "formula": formula[:200],
                            "reason": "合计区间含自身单元格",
                        }
                    )
            except (TypeError, ValueError):
                pass
        for match in cell_ref.finditer(formula):
            a, r, a2, r2 = match.groups()
            try:
                if a2 and r2:
                    bc1, br1, bc2, br2 = bounded_range(f"{a}{r}:{a2}{r2}")
                    points = [(bc1, br1), (bc2, br2)]
                    # sample corners + mid for outbound
                    points.append(((bc1 + bc2) // 2, (br1 + br2) // 2))
                else:
                    points = [(column_index_from_string(a), int(r))]
            except (TypeError, ValueError):
                continue
            for col, row in points:
                if not selected(sheet, col, row):
                    outbound.append(
                        {
                            "sheet": sheet,
                            "from_cell": address,
                            "formula": formula[:200],
                            "outside": f"{get_column_letter(col)}{row}",
                        }
                    )
                    break
    # Cap receipt size
    return {
        "outbound_formula_refs": outbound[:50],
        "circular_self_refs": circular[:50],
        "outbound_count": len(outbound),
        "circular_count": len(circular),
    }


def inspect_cut(review: dict, group: dict) -> dict:
    """Inspect one proposed document cut; never mutates the group."""
    fragments = group.get("fragments") or []
    if not fragments:
        return {
            "ok": False,
            "status": "empty",
            "reason": "切片无片段",
            "sticky": False,
            "needs_reidentify": True,
        }
    cells = _cells_in_fragments(review, fragments)
    formula = _formula_outbound_and_circular(cells, fragments)
    title_blocks: list[dict] = []
    ledger = None
    # Union rectangles per sheet so multi-fragment mega-cuts (split only for transport)
    # are scored as one continuous ledger / title band.
    by_sheet: dict[str, list[tuple[int, int, int, int]]] = {}
    for part in fragments:
        try:
            by_sheet.setdefault(part["sheet"], []).append(bounded_range(part["range"]))
        except (TypeError, ValueError, KeyError):
            continue
    for sheet, rects in by_sheet.items():
        c1 = min(r[0] for r in rects)
        r1 = min(r[1] for r in rects)
        c2 = max(r[2] for r in rects)
        r2 = max(r[3] for r in rects)
        host_range = _range_to_a1(c1, r1, c2, r2)
        titles = _detect_title_blocks(cells, sheet, c1, r1, c2, r2)
        # Structural block_title_rows may refine a cut, but only document-heading
        # rows count. Agreement / multi-copy / 购货单位 meta lines inside one
        # contiguous delivery note must not force sticky title resplit.
        index = review.get("workbook_structural_index") or {}
        for sheet_info in index.get("sheets") or []:
            if sheet_info.get("sheet") != sheet:
                continue
            for block in sheet_info.get("block_title_rows") or []:
                row = block.get("row")
                if not isinstance(row, int) or not (r1 <= row <= r2):
                    continue
                text = str(block.get("text") or "").strip()
                if not text:
                    continue
                if not (_is_document_heading_text(text) or _is_title_row_text(text)):
                    continue
                if any(t.get("row") == row for t in titles):
                    continue
                titles.append({"row": row, "text": text[:120], "cell": f"A{row}"})
        for t in titles:
            title_blocks.append({**t, "sheet": sheet, "host_range": host_range})
        found = _detect_order_ledger_runs(cells, sheet, c1, r1, c2, r2)
        if found and (ledger is None or found["run_count"] > ledger["run_count"]):
            ledger = {**found, "host_range": host_range, "host_bounds": (c1, r1, c2, r2)}

    # Period documents often have one title + many line-level date/order rows.
    # Only treat ledger runs as stickiness when the cut lacks a single covering title
    # (continuous untitled / weakly-titled shipment ledgers).
    sticky_titles = len(title_blocks) >= _MIN_TITLE_BLOCKS_FOR_STICKY
    single_title = len(title_blocks) == 1  # retained for receipts / future heuristics
    _ = single_title
    # Prefer atomic order/date runs for untitled shipment ledgers.
    # Titled period/documents (any title_blocks) stay period-scoped — do not
    # resplit them by inner date/order-looking columns.
    sticky_ledger = bool(
        ledger
        and ledger["run_count"] >= _MIN_ORDER_RUNS_FOR_STICKY
        and not sticky_titles
        and not title_blocks
    )
    sticky = sticky_titles or sticky_ledger
    status = "ok"
    reason = "切后交叉引用复核通过"
    if formula["circular_count"]:
        # Export path quarantines circular cells; verify only warns — do not
        # abandon the whole segment here.
        status = "circular_quarantine"
        reason = (
            f"检出 {formula['circular_count']} 处循环/自引用公式，"
            "导出时将隔离这些单元格，其余内容照常切出"
        )
    elif sticky_titles:
        status = "sticky_titles"
        reason = (
            f"切片内检出 {len(title_blocks)} 个独立标题块，疑似多段单据粘连，"
            "需按标题拆分或重新识别"
        )
    elif sticky_ledger:
        status = "sticky_ledger"
        reason = (
            f"切片疑似粘连多单台账（检出约 {ledger['run_count']} 个日期+单号连续块），"
            "需按单拆分或重新识别"
        )
    elif formula["outbound_count"]:
        # Outbound alone is not always fatal (support sheet may cover), but surface it.
        status = "outbound_refs"
        reason = f"切片内有 {formula['outbound_count']} 处公式引用落在切出范围外（交叉引用）"

    return {
        "ok": status in ("ok", "circular_quarantine", "outbound_refs"),
        "status": status,
        "reason": reason,
        "sticky": sticky,
        "needs_reidentify": sticky and not (sticky_titles or sticky_ledger),
        "title_blocks": title_blocks[:40],
        "ledger": (
            {
                "sheet": ledger["sheet"],
                "date_col": ledger["date_col"],
                "order_col": ledger["order_col"],
                "run_count": ledger["run_count"],
                "host_range": ledger.get("host_range"),
            }
            if ledger
            else None
        ),
        "ledger_runs": (ledger or {}).get("runs", [])[:200],
        "formula": formula,
        "fragment_count": len(fragments),
        "cell_count": len(cells),
    }


def _new_document_id(fragments: list[dict]) -> str:
    payload = [{"sheet": f["sheet"], "range": f["range"]} for f in fragments]
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return "source-" + digest[:24]


def _split_by_titles(group: dict, title_blocks: list[dict]) -> list[dict] | None:
    """Split a single-sheet cut into one group per titled block."""
    fragments = group.get("fragments") or []
    if len(fragments) != 1:
        # Multi-fragment groups: only split when all titles share one host sheet+range.
        hosts = {(t["sheet"], t["host_range"]) for t in title_blocks}
        if len(hosts) != 1:
            return None
        sheet, host_range = next(iter(hosts))
        c1, r1, c2, r2 = bounded_range(host_range)
    else:
        sheet = fragments[0]["sheet"]
        c1, r1, c2, r2 = bounded_range(fragments[0]["range"])
        title_blocks = [t for t in title_blocks if t.get("sheet") == sheet]
    if len(title_blocks) < _MIN_TITLE_BLOCKS_FOR_STICKY:
        return None
    rows = sorted({t["row"] for t in title_blocks if r1 <= t["row"] <= r2})
    if len(rows) < 2:
        return None
    splits: list[dict] = []
    for idx, start in enumerate(rows):
        end = rows[idx + 1] - 1 if idx + 1 < len(rows) else r2
        if end < start:
            continue
        frags = [{"sheet": sheet, "range": _range_to_a1(c1, start, c2, end)}]
        splits.append(
            {
                "document_id": _new_document_id(frags),
                "fragments": frags,
                "evidence": group.get("evidence") or [],
                "reason": f"切后复核按标题块拆分自 {group.get('document_id')}",
                "verify_resplit_from": group.get("document_id"),
                "verify_basis": "title_blocks",
            }
        )
    return splits if len(splits) >= 2 else None


def _split_by_ledger_runs(group: dict, inspection: dict) -> list[dict] | None:
    ledger = inspection.get("ledger") or {}
    runs = inspection.get("ledger_runs") or []
    if not ledger or len(runs) < _MIN_ORDER_RUNS_FOR_STICKY:
        return None
    sheet = ledger["sheet"]
    host = ledger.get("host_range")
    if not host:
        return None
    c1, r1, c2, r2 = bounded_range(host)
    # Prefer original fragment column span on this sheet; ignore other sheets' fragments.
    same_sheet = [f for f in (group.get("fragments") or []) if f.get("sheet") == sheet]
    if same_sheet:
        # Union column span across same-sheet fragments that overlap host rows.
        cols = []
        for f in same_sheet:
            fc1, fr1, fc2, fr2 = bounded_range(f["range"])
            cols.append((fc1, fc2))
        c1 = min(c for c, _ in cols)
        c2 = max(c for _, c in cols)
    splits: list[dict] = []
    # Include a short header band above first run when present (title row).
    header_end = runs[0]["row_start"] - 1
    header_start = r1 if r1 <= header_end else None
    for i, run in enumerate(runs):
        rs, re_ = run["row_start"], run["row_end"]
        if i == 0 and header_start is not None and header_start < rs:
            rs = header_start
        rs = max(rs, r1)
        re_ = min(re_, r2)
        if re_ < rs:
            continue
        frags = [{"sheet": sheet, "range": _range_to_a1(c1, rs, c2, re_)}]
        splits.append(
            {
                "document_id": _new_document_id(frags),
                "fragments": frags,
                "evidence": group.get("evidence") or [],
                "reason": f"切后复核按日期+单号块拆分自 {group.get('document_id')}",
                "verify_resplit_from": group.get("document_id"),
                "verify_basis": "order_ledger_runs",
            }
        )
    return splits if len(splits) >= 2 else None


def verify_after_cut(
    review: dict,
    groups: list[dict],
    *,
    resplit: bool = True,
    max_groups: int = 500,
) -> dict:
    """Verify each proposed cut; optionally resplit sticky multi-document ranges.

    Returns groups (possibly expanded), per-group receipts, and aggregate stats.
    Does not call the model. Never invents workbook-title-specific rules.
    """
    if not isinstance(groups, list):
        raise ReviewedExcelError("切后复核分组无效")
    if len(groups) > max_groups:
        raise ReviewedExcelError("切后复核分组数量超过安全预算")

    receipts: list[dict] = []
    out_groups: list[dict] = []
    sticky_caught = 0
    circular_caught = 0
    resplit_count = 0
    outbound_flagged = 0

    for group in groups:
        inspection = inspect_cut(review, group)
        receipt = {
            "document_id": group.get("document_id"),
            "fragments": deepcopy(group.get("fragments") or []),
            **{k: inspection[k] for k in (
                "ok", "status", "reason", "sticky", "needs_reidentify",
                "title_blocks", "ledger", "formula", "fragment_count", "cell_count",
            )},
            "action": "keep",
        }
        if inspection["status"] in ("circular", "circular_quarantine"):
            circular_caught += 1
        if inspection.get("formula", {}).get("outbound_count"):
            outbound_flagged += 1
        if inspection["sticky"]:
            sticky_caught += 1
            split = None
            if resplit:
                if inspection["status"] == "sticky_titles":
                    split = _split_by_titles(group, inspection.get("title_blocks") or [])
                elif inspection["status"] == "sticky_ledger":
                    split = _split_by_ledger_runs(group, inspection)
            if split:
                # Re-inspect children; keep those that are not empty.
                children = []
                child_notes = []
                for child in split:
                    if len(out_groups) + len(children) >= max_groups:
                        break
                    child_insp = inspect_cut(review, child)
                    note = {
                        "document_id": child["document_id"],
                        "fragments": child["fragments"],
                        "status": child_insp["status"],
                        "reason": child_insp["reason"],
                        "sticky": child_insp["sticky"],
                    }
                    child_notes.append(note)
                    # Avoid infinite cascade: accept child even if still mildly sticky
                    # when run_count collapsed (status ok or outbound only).
                    children.append(child)
                if len(children) >= 2:
                    receipt["action"] = "resplit"
                    receipt["resplit_into"] = child_notes
                    resplit_count += 1
                    out_groups.extend(children)
                    receipts.append(receipt)
                    continue
            receipt["action"] = "flag_reidentify"
            receipt["needs_reidentify"] = True
            # Keep original so export still attempts; caller may filter on needs_reidentify.
            tagged = deepcopy(group)
            tagged["verify_status"] = inspection["status"]
            tagged["verify_reason"] = inspection["reason"]
            tagged["needs_reidentify"] = True
            out_groups.append(tagged)
            receipts.append(receipt)
            continue

        tagged = deepcopy(group)
        tagged["verify_status"] = inspection["status"]
        tagged["verify_reason"] = inspection["reason"]
        if inspection["status"] in ("circular", "circular_quarantine"):
            tagged["circular_quarantine"] = True
            tagged["verify_fail_closed"] = False
        out_groups.append(tagged)
        receipts.append(receipt)

    stats = {
        "input_groups": len(groups),
        "output_groups": len(out_groups),
        "sticky_caught": sticky_caught,
        "circular_caught": circular_caught,
        "outbound_flagged": outbound_flagged,
        "resplit_groups": resplit_count,
        "flagged_reidentify": sum(1 for r in receipts if r.get("action") == "flag_reidentify"),
    }
    return {"groups": out_groups, "receipts": receipts, "stats": stats}


def verify_groups_or_raise(review: dict, groups: list[dict], *, resplit: bool = True) -> list[dict]:
    """Product-path helper: run verify_after_cut and return groups (resplit when possible)."""
    result = verify_after_cut(review, groups, resplit=resplit)
    return result["groups"]
