"""Multi-pack cell evidence with overlap anchors for global workbook inventory.

Transport packs (≤MAX_MODEL_CELLS / ≤MAX_MODEL_TEXT_BYTES) carry no business
meaning by themselves. This module adds overlapping row anchors and header
fingerprints so a model (or a follow-up merge call) can reassemble whole-workbook
document order across packs — without embedding answer counts or file-specific
labels in prompts.

Dense structure evidence for a single inventory-pass remains a separate path
(see prototype runners under batch1019); this module focuses on full-cell packs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string

from app.application.reviewed_excel_evidence import (
    MAX_MODEL_CELLS,
    MAX_MODEL_TEXT_BYTES,
    _model_cell_cost,
)

# Rows of overlap between consecutive packs on the same sheet (anchors).
DEFAULT_OVERLAP_ROWS = 8
ANCHOR_FINGERPRINT_ROWS = 3

MULTIPACK_STITCH_PROMPT = """你在做跨传输包的全局「单」清单拼接。每个 pack 是同一工作簿的局部单元格证据（含重叠锚点），运输边界本身没有业务含义。

规则（通用）：
1. 利用 pack 元数据中的 sheet、row_start/row_end、overlap_with_previous、header_fingerprint、anchor_rows 对齐同一工作表的连续区域；重叠行上的相同内容表示同一物理行，不要重复计数。
2. 隐表（sheet_state=hidden/veryHidden）非空则必须纳入。
3. 切单粒度：
   - 新的块标题（送货单/购货明细/回款/报价等）→ 新单；并列「购货明细」侧栏各自一单。
   - 同一报价时段内，主报价与同行右侧对照厂报价栏合并为同一报价段（不要把对照栏拆成另一单）。
   - 出货台账：以单号为主；空单号/换货/退货等标记变化视为新单。同一单号且行连续时，若日期相同或仅相差 1 个日历日则仍为一单；日期间隔更大则分为多单。
4. 禁止把整年台账粘成一单；禁止因 pack 边界而切断或重复同一单。
5. 输出严格 JSON：
{"documents":[{"sheet":"...","sheet_state":"...","kind":"...","range":"A1:L10","order_key":"...","note":"...","source_packs":[0,1]}],
 "by_sheet_counts":{},"total":0}
documents 一单一条；total=len(documents)；不要输出期望总数以外的目标数字（你应自行清点）。
"""


def _row_of(cell: dict) -> int:
    _, row = coordinate_from_string(cell["cell"])
    return row


def _col_of(cell: dict) -> int:
    col, _ = coordinate_from_string(cell["cell"])
    return column_index_from_string(col)


def _sheet_state_map(review: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in review.get("sheet_overview") or []:
        out[item["sheet"]] = item.get("sheet_state") or "visible"
    return out


def _header_fingerprint(cells: list[dict], rows: set[int]) -> str:
    bits = []
    for cell in sorted(cells, key=lambda c: (_row_of(c), _col_of(c))):
        if _row_of(cell) not in rows:
            continue
        val = (cell.get("value") or "")[:80]
        bits.append(f"{cell['cell']}={val}")
    digest = hashlib.sha256("|".join(bits).encode("utf-8")).hexdigest()[:16]
    return digest


def _anchor_snapshot(cells: list[dict], rows: set[int], limit: int = 24) -> list[dict]:
    chosen = [
        {
            "cell": c["cell"],
            "value": (c.get("value") or "")[:120],
            "kind": c.get("kind"),
        }
        for c in sorted(cells, key=lambda x: (_row_of(x), _col_of(x)))
        if _row_of(c) in rows
    ]
    return chosen[:limit]


def _pack_fits(cells: list[dict]) -> bool:
    if len(cells) > MAX_MODEL_CELLS:
        return False
    if sum(map(_model_cell_cost, cells)) > MAX_MODEL_TEXT_BYTES:
        return False
    return True


def build_overlapped_sheet_packs(
    review: dict,
    *,
    overlap_rows: int = DEFAULT_OVERLAP_ROWS,
) -> list[dict[str, Any]]:
    """Split full-cell evidence into per-sheet packs with overlapping row anchors.

    Returns pack descriptors: {pack_id, sheet, sheet_state, row_start, row_end,
    overlap_with_previous, header_fingerprint, anchor_rows, cells}.
    """
    if overlap_rows < 1:
        raise ValueError("overlap_rows must be >= 1")
    states = _sheet_state_map(review)
    by_sheet: dict[str, list[dict]] = defaultdict(list)
    for cell in review.get("cells") or []:
        by_sheet[cell["sheet"]].append(cell)

    packs: list[dict[str, Any]] = []
    pack_id = 0
    for sheet in review.get("sheets") or list(by_sheet):
        cells = sorted(by_sheet.get(sheet) or [], key=lambda c: (_row_of(c), _col_of(c)))
        if not cells:
            continue
        rows = sorted({_row_of(c) for c in cells})
        # Grow contiguous row windows until budget; overlap previous window's tail.
        i = 0
        prev_end = None
        while i < len(rows):
            # Start index: if continuing, back up overlap_rows into previous span.
            if prev_end is not None:
                # find index of first row >= prev_end - overlap + 1 conceptually
                start_row = max(rows[0], prev_end - overlap_rows + 1)
                while i > 0 and rows[i - 1] >= start_row:
                    i -= 1
                while i < len(rows) and rows[i] < start_row:
                    i += 1
            window_start_idx = i
            lo, hi, best = window_start_idx, len(rows) - 1, window_start_idx - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                row_set = set(rows[window_start_idx : mid + 1])
                chosen = [c for c in cells if _row_of(c) in row_set]
                if _pack_fits(chosen):
                    best = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best < window_start_idx:
                # Single-row still too large: take minimal prefix of that row's cells
                row = rows[window_start_idx]
                row_cells = [c for c in cells if _row_of(c) == row]
                chosen = []
                for c in row_cells:
                    trial = chosen + [c]
                    if not _pack_fits(trial) and chosen:
                        break
                    chosen = trial
                if not chosen:
                    chosen = row_cells[:1]
                row_start = row_end = row
                next_i = window_start_idx + 1
            else:
                row_set = set(rows[window_start_idx : best + 1])
                chosen = [c for c in cells if _row_of(c) in row_set]
                row_start = rows[window_start_idx]
                row_end = rows[best]
                next_i = best + 1

            overlap_meta = None
            if prev_end is not None:
                overlap_lo = max(row_start, prev_end - overlap_rows + 1)
                overlap_hi = min(row_end, prev_end)
                overlap_rows_set = {r for r in range(overlap_lo, overlap_hi + 1)}
                fp_rows = set(
                    sorted(overlap_rows_set)[:ANCHOR_FINGERPRINT_ROWS]
                    or [row_start]
                )
                overlap_meta = {
                    "overlap_row_start": overlap_lo,
                    "overlap_row_end": overlap_hi,
                    "continues_sheet": sheet,
                    "previous_pack_id": pack_id - 1,
                }
            else:
                fp_rows = set(rows[window_start_idx : window_start_idx + ANCHOR_FINGERPRINT_ROWS])
                overlap_meta = None

            # Header fingerprint: prefer early sheet rows present in this pack
            header_candidate = {r for r in rows[:5] if row_start <= r <= row_end} or fp_rows
            packs.append(
                {
                    "pack_id": pack_id,
                    "sheet": sheet,
                    "sheet_state": states.get(sheet, "visible"),
                    "row_start": row_start,
                    "row_end": row_end,
                    "cell_count": len(chosen),
                    "text_cost": sum(map(_model_cell_cost, chosen)),
                    "overlap_with_previous": overlap_meta,
                    "header_fingerprint": _header_fingerprint(chosen, header_candidate),
                    "anchor_rows": _anchor_snapshot(chosen, fp_rows),
                    "cells": chosen,
                }
            )
            pack_id += 1
            prev_end = row_end
            i = next_i
            # Ensure forward progress
            if i <= window_start_idx:
                i = window_start_idx + 1
    return packs


def packs_without_cells(packs: list[dict]) -> list[dict]:
    """Metadata-only view for logs / merge prompts (drop bulky cells)."""
    out = []
    for p in packs:
        out.append({k: v for k, v in p.items() if k != "cells"})
    return out


def stitch_inventory_messages(
    *,
    dense_structure_text: str,
    pack_summaries: list[dict],
    per_pack_inventories: list[dict],
) -> list[dict]:
    """Build messages for a model-led merge of per-pack inventories + dense overview."""
    user = {
        "dense_structure_evidence": dense_structure_text,
        "pack_summaries": pack_summaries,
        "per_pack_inventories": per_pack_inventories,
        "instruction": (
            "先用 dense_structure_evidence 建立全簿心智模型，再用各 pack 清单与 "
            "overlap/header_fingerprint/anchor_rows 去重合并为唯一全局 documents 列表。"
        ),
    }
    return [
        {"role": "system", "content": MULTIPACK_STITCH_PROMPT},
        {
            "role": "user",
            "content": json.dumps(user, ensure_ascii=False),
        },
    ]


def programmatic_merge_inventories(inventories: list[dict]) -> dict:
    """Dedupe documents by (sheet, normalized order_key or range) without GT.

    Used when a second model call is unnecessary; does not invent counts from answers.
    """
    seen: set[tuple] = set()
    docs: list[dict] = []
    for inv in inventories:
        for doc in inv.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            sheet = doc.get("sheet") or ""
            key = (
                sheet,
                (doc.get("order_key") or "").strip(),
                (doc.get("range") or "").strip(),
            )
            # Prefer order_key dedupe when present
            soft = (sheet, (doc.get("order_key") or "").strip())
            if key in seen or (soft[1] and soft in {(d.get("sheet"), (d.get("order_key") or "").strip()) for d in docs}):
                continue
            seen.add(key)
            docs.append(doc)
    by: dict[str, int] = defaultdict(int)
    for d in docs:
        by[str(d.get("sheet") or "")] += 1
    return {
        "documents": docs,
        "by_sheet_counts": dict(by),
        "total": len(docs),
        "merge": "programmatic_dedupe",
    }
