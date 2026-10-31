"""General workbook structural index for ELT uploads (pre-slice global context).

Builds a schema that describes sheet visibility, headers, order-key-like columns,
block title rows, candidate row ranges, and cross-sheet formula edges — without
customer names, fixed order counts, or workbook-title hardcodes.

Product persistence: attach_structural_index_to_draft() stores a compact copy under
draft_json["workbook_structural_index"]. Prototype runners may also write the full
index beside the upload as a linked JSON artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.formula.tokenizer import Tokenizer, TokenizerError
from openpyxl.utils.cell import get_column_letter

from app.application.etl.errors import ReviewedExcelError
from app.application.reviewed_excel_evidence import bounded_range

SCHEMA_VERSION = "workbook-structural-index-v1"
# Reserved budget for the model-facing summary inside each classify/group request.
STRUCTURAL_INDEX_MODEL_BUDGET_BYTES = 40_000

_TITLE_HINT = re.compile(
    r"(购货明细|回款明细|出货明细|送货单|退货单|出货单|报价|对账|明细表|"
    r"invoice|statement|receipt|delivery)",
    re.IGNORECASE,
)
_DATEISH_TITLE = re.compile(r"(20\d{2}|19\d{2}).{0,8}\d{1,2}|起|至|截止")
_ORDER_HEADER = re.compile(
    r"(订单号|单号|单据号|报价单号|出货单号|order\s*no|order\s*number|po\s*#?)",
    re.IGNORECASE,
)
_DATE_HEADER = re.compile(r"(^日期$|购货.*日期|出货.*日期|日\s*期|date)", re.IGNORECASE)
_FACTORY_HEADER = re.compile(r"(厂名|购货单位|客户|customer|factory)", re.IGNORECASE)
_HEADER_ANY = re.compile(
    r"(厂名|日期|单号|型号|名称|金额|购货|付款|备注|规格|数量|单价)",
)
_EXCEL_DATE_LO, _EXCEL_DATE_HI = 30000, 60000


def _cell_text(value: Any, limit: int = 120) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).replace("\n", " ").strip()
    return text[: limit - 3] + "..." if len(text) > limit else text


def _is_excel_serial(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (_EXCEL_DATE_LO <= float(value) <= _EXCEL_DATE_HI)
    )


def _title_like(text: str) -> bool:
    if not text or len(text) < 4:
        return False
    if _TITLE_HINT.search(text):
        return True
    if _DATEISH_TITLE.search(text) and len(text) >= 8:
        return True
    return False


def _kind_hint(text: str) -> str:
    lower = text.casefold()
    if "退货" in text or "return" in lower:
        return "return_note"
    if "送货" in text or "delivery" in lower:
        return "delivery_note"
    if "回款" in text or "payment" in lower or "receipt" in lower:
        return "payment_block"
    if "报价" in text or "quote" in lower:
        return "quote_block"
    if "购货明细" in text or "出货明细" in text or ("明细" in text and _DATEISH_TITLE.search(text)):
        return "period_block"
    if "出货" in text:
        return "shipment_block"
    return "other"


_DOC_TYPE_PRIMARY = re.compile(
    r"(送货单|退货单|出货单|购货明细|回款明细|出货明细|报价单|对账单|"
    r"invoice|statement|receipt|delivery)",
    re.IGNORECASE,
)
_FORM_META = re.compile(r"(购货单位|联系人：|联系人:|订单编号)")
_TITLE_BOILERPLATE = re.compile(
    r"(销售协议|一式\s*四联|一式四联|法律效力|联为|签字|验收|如有异议|按期付清|人民法院)"
)


def _primary_title_segment(text: str) -> str:
    return (text or "").split("|", 1)[0].strip()


def _is_document_heading_text(text: str) -> bool:
    """True for a standalone document header row (送货单/退货单/期间明细...), not body lines.

    Agreement clauses, multi-copy legends, and 购货单位 meta bands are title-*like*
    for scanning but are not independent document heads.
    """
    primary = _primary_title_segment(text)
    if len(primary) < 4 or len(primary) > 80:
        return False
    if _TITLE_BOILERPLATE.search(primary):
        return False
    if re.match(r"^\d+[\.、．]", primary):
        return False
    if not _DOC_TYPE_PRIMARY.search(primary):
        return False
    # Form-meta rows that merely mention a doc type in a side clause stay non-heads.
    if _FORM_META.search(primary) and not _DOC_TYPE_PRIMARY.search(primary[:20]):
        return False
    return True


def _is_form_meta_text(text: str) -> bool:
    """购货单位 / 联系人 / 订单编号 band without being a document-type header."""
    primary = _primary_title_segment(text)
    if not primary or _is_document_heading_text(text):
        return False
    return bool(_FORM_META.search(primary))


def _detect_header_roles(ws, max_scan: int = 8) -> dict[str, dict]:
    roles: dict[str, dict] = {}
    patterns = [
        ("factory", _FACTORY_HEADER),
        ("date", _DATE_HEADER),
        ("order_no", _ORDER_HEADER),
    ]
    max_row = min(max_scan, ws.max_row or 1)
    max_col = min(ws.max_column or 1, 24)
    for row in range(1, max_row + 1):
        for col in range(1, max_col + 1):
            value = ws.cell(row, col).value
            if not isinstance(value, str):
                continue
            text = value.strip()
            for role, pattern in patterns:
                if role not in roles and pattern.search(text):
                    roles[role] = {
                        "role": role,
                        "col": get_column_letter(col),
                        "col_index": col,
                        "header_text": _cell_text(text, 40),
                        "header_row": row,
                    }
    return roles


def _infer_ledger_cols(ws) -> dict[str, int] | None:
    max_r = min(ws.max_row or 0, 40)
    max_c = min(ws.max_column or 0, 12)
    if max_r < 5:
        return None
    serial_hits: Counter[int] = Counter()
    short_token: Counter[int] = Counter()
    short_name: Counter[int] = Counter()
    for row in range(1, max_r + 1):
        for col in range(1, max_c + 1):
            value = ws.cell(row, col).value
            if _is_excel_serial(value) or isinstance(value, (datetime, date)):
                serial_hits[col] += 1
            elif (
                isinstance(value, str) and 1 <= len(value.strip()) <= 12 and not _title_like(value)
            ):
                short_name[col] += 1
            elif (
                isinstance(value, (int, float))
                and not _is_excel_serial(value)
                and abs(value) < 100000
            ) or (isinstance(value, str) and re.fullmatch(r"\d{1,5}|.?\d{1,4}号?", value.strip())):
                short_token[col] += 1
    if not serial_hits:
        return None
    date_c = serial_hits.most_common(1)[0][0]
    order_c = None
    for cand in (date_c + 1, date_c + 2, date_c - 1):
        if 1 <= cand <= max_c and (short_token[cand] >= 3 or short_name[cand] >= 3):
            order_c = cand
            break
    if order_c is None:
        for col, _ in short_token.most_common():
            if col != date_c:
                order_c = col
                break
    if order_c is None:
        return None
    factory_c = next((c for c, _ in short_name.most_common() if c not in (date_c, order_c)), None)
    out = {"date": date_c, "order_no": order_c}
    if factory_c:
        out["factory"] = factory_c
    return out


def _sample_column_values(ws, col: int, start_row: int, limit: int = 8) -> list[str]:
    samples: list[str] = []
    seen: set[str] = set()
    for row in range(start_row, (ws.max_row or 0) + 1):
        text = _cell_text(ws.cell(row, col).value, 40)
        if not text or text in seen:
            continue
        seen.add(text)
        samples.append(text)
        if len(samples) >= limit:
            break
    return samples


def _distinct_approx(ws, col: int, start_row: int, cap: int = 500) -> int:
    seen: set[str] = set()
    for row in range(start_row, (ws.max_row or 0) + 1):
        text = _cell_text(ws.cell(row, col).value, 40)
        if text:
            seen.add(text)
        if len(seen) >= cap:
            return cap
    return len(seen)


def _ledger_run_hint(ws, date_c: int, order_c: int, start_row: int) -> tuple[int, list[dict]]:
    """Return consecutive (date, order) runs with start/end rows for atomic candidates.

    Each run is one atomic order/date block. Caps stored runs for envelope size;
    run count itself is exact.
    """
    runs: list[dict] = []
    current: tuple[str, str] | None = None
    start: int | None = None
    last_data_row: int | None = None
    for row in range(start_row, (ws.max_row or 0) + 1):
        date_text = _cell_text(ws.cell(row, date_c).value, 32)
        order_text = _cell_text(ws.cell(row, order_c).value, 32)
        if not date_text and not order_text:
            continue
        key = (date_text, order_text)
        last_data_row = row
        if key != current:
            if current is not None and start is not None:
                runs.append(
                    {
                        "start_row": start,
                        "end_row": row - 1,
                        "date": current[0],
                        "order_key": current[1],
                    }
                )
            current = key
            start = row
    if current is not None and start is not None and last_data_row is not None:
        runs.append(
            {
                "start_row": start,
                "end_row": last_data_row,
                "date": current[0],
                "order_key": current[1],
            }
        )
    # Fix end_row of each run to the row before next run's start (gap-aware).
    for i in range(len(runs) - 1):
        runs[i]["end_row"] = max(runs[i]["start_row"], runs[i + 1]["start_row"] - 1)
    return len(runs), runs


def _cross_sheet_refs(ws, sheet_name: str, cap: int = 40) -> list[dict]:
    refs: list[dict] = []
    for row in ws.iter_rows():
        for cell in row:
            if cell.data_type != "f" or cell.value is None:
                continue
            formula = str(cell.value)
            if "!" not in formula:
                continue
            try:
                tokens = Tokenizer(formula).items
            except TokenizerError:
                continue
            targets = []
            for token in tokens:
                if token.type != "OPERAND" or token.subtype != "RANGE":
                    continue
                if "!" not in token.value:
                    continue
                targets.append(token.value.replace("$", "")[:80])
            if not targets:
                continue
            refs.append(
                {
                    "from_cell": cell.coordinate,
                    "formula_snippet": formula[:120],
                    "targets": targets[:8],
                }
            )
            if len(refs) >= cap:
                return refs
    return refs


def build_workbook_structural_index(body: bytes) -> dict[str, Any]:
    """Extract a general structural index from workbook bytes."""
    if not body:
        raise ValueError("empty workbook body")
    digest = hashlib.sha256(body).hexdigest()
    wb = load_workbook(BytesIO(body), data_only=False, keep_links=True)
    try:
        sheets_out: list[dict] = []
        edge_counter: Counter[tuple[str, str]] = Counter()
        for ws in wb.worksheets:
            state = ws.sheet_state or "visible"
            roles = _detect_header_roles(ws)
            inferred = None
            if "date" not in roles or "order_no" not in roles:
                inferred = _infer_ledger_cols(ws)
                if inferred and (ws.max_row or 0) >= 8:
                    for role, col in inferred.items():
                        roles.setdefault(
                            role,
                            {
                                "role": role,
                                "col": get_column_letter(col),
                                "col_index": col,
                                "header_text": "",
                                "header_row": 0,
                                "inferred_from_data_shape": True,
                            },
                        )

            block_titles: list[dict] = []
            header_rows: list[dict] = []
            for row in range(1, (ws.max_row or 0) + 1):
                bits = []
                is_title = False
                is_header = False
                for col in range(1, min((ws.max_column or 1), 16) + 1):
                    value = ws.cell(row, col).value
                    if value is None:
                        continue
                    text = _cell_text(value, 80)
                    if not text:
                        continue
                    bits.append({"col": get_column_letter(col), "text": text})
                    if isinstance(value, str) and _title_like(text):
                        is_title = True
                    if isinstance(value, str) and _HEADER_ANY.search(value):
                        is_header = True
                if not bits:
                    continue
                joined = " | ".join(item["text"] for item in bits)
                if is_title:
                    block_titles.append(
                        {
                            "row": row,
                            "text": joined[:160],
                            "kind_hint": _kind_hint(joined),
                        }
                    )
                elif is_header and row <= 12 and len(header_rows) < 12:
                    header_rows.append({"row": row, "cells": bits[:12]})

            order_key_columns: list[dict] = []
            candidate_ranges: list[dict] = []
            ledger_run_hint = 0
            use_ledger = (
                "date" in roles
                and "order_no" in roles
                and (ws.max_row or 0) >= 8
                and not any(t["kind_hint"] == "delivery_note" for t in block_titles[:5])
            )
            if use_ledger:
                date_meta = roles["date"]
                order_meta = roles["order_no"]
                date_c = date_meta["col_index"]
                order_c = order_meta["col_index"]
                start = max(date_meta.get("header_row", 0), order_meta.get("header_row", 0)) + 1
                if start <= 1:
                    start = 1
                    for row in range(1, min(8, (ws.max_row or 1) + 1)):
                        if _is_excel_serial(ws.cell(row, date_c).value) or isinstance(
                            ws.cell(row, date_c).value, (datetime, date)
                        ):
                            start = row
                            break
                for role_name in ("factory", "date", "order_no"):
                    meta = roles.get(role_name)
                    if not meta:
                        continue
                    order_key_columns.append(
                        {
                            "role": role_name,
                            "col": meta["col"],
                            "header_text": meta.get("header_text") or "",
                            "inferred_from_data_shape": bool(meta.get("inferred_from_data_shape")),
                            "sample_values": _sample_column_values(ws, meta["col_index"], start),
                            "distinct_approx": _distinct_approx(ws, meta["col_index"], start),
                        }
                    )
                ledger_run_hint, run_rows = _ledger_run_hint(ws, date_c, order_c, start)
                # Prefer atomic per-run candidates so identify/group can cut by
                # 单号 + date boundaries instead of one glued ledger rectangle.
                max_atomic = 120
                for run in run_rows[:max_atomic]:
                    candidate_ranges.append(
                        {
                            "start_row": run["start_row"],
                            "end_row": run["end_row"],
                            "basis": "ledger_key_run",
                            "date": run.get("date") or "",
                            "order_key": (run.get("order_key") or "")[:32],
                        }
                    )
                if ledger_run_hint > max_atomic and run_rows:
                    # Summary remainder hint when capped.
                    candidate_ranges.append(
                        {
                            "start_row": run_rows[max_atomic]["start_row"],
                            "end_row": run_rows[-1]["end_row"],
                            "basis": "ledger_key_runs_remainder",
                            "run_hint_count": ledger_run_hint - max_atomic,
                        }
                    )
                elif not run_rows and ledger_run_hint:
                    candidate_ranges.append(
                        {
                            "start_row": start,
                            "end_row": ws.max_row or start,
                            "basis": "ledger_key_runs",
                            "run_hint_count": ledger_run_hint,
                        }
                    )
            else:
                for role_name, meta in roles.items():
                    order_key_columns.append(
                        {
                            "role": role_name,
                            "col": meta["col"],
                            "header_text": meta.get("header_text") or "",
                            "inferred_from_data_shape": bool(meta.get("inferred_from_data_shape")),
                            "sample_values": _sample_column_values(
                                ws, meta["col_index"], max(meta.get("header_row", 0) + 1, 1), 6
                            ),
                            "distinct_approx": _distinct_approx(
                                ws, meta["col_index"], max(meta.get("header_row", 0) + 1, 1), 80
                            ),
                        }
                    )

            if block_titles:
                rows = [t["row"] for t in block_titles]
                # First document heading on a sheet keeps fine-grained title atoms
                # (agreement / meta lines remain separate structural cues).
                # A later document heading (e.g. mid-sheet 退货单 after a 送货单)
                # absorbs its immediate form-meta band so header+party lines are
                # one atom — not a phantom extra document.
                skip_indices: set[int] = set()
                document_headings_seen = 0
                for title_idx, title in enumerate(block_titles):
                    if title_idx in skip_indices:
                        continue
                    end = (
                        (rows[title_idx + 1] - 1)
                        if title_idx + 1 < len(rows)
                        else (ws.max_row or title["row"])
                    )
                    kind = title["kind_hint"]
                    if (
                        _is_document_heading_text(title["text"])
                        and document_headings_seen >= 1
                        and title_idx + 1 < len(block_titles)
                        and _is_form_meta_text(block_titles[title_idx + 1]["text"])
                    ):
                        skip_indices.add(title_idx + 1)
                        if title_idx + 2 < len(rows):
                            end = rows[title_idx + 2] - 1
                        else:
                            end = ws.max_row or title["row"]
                        kind = title["kind_hint"] or _kind_hint(title["text"])
                    if _is_document_heading_text(title["text"]):
                        document_headings_seen += 1
                    candidate_ranges.append(
                        {
                            "start_row": title["row"],
                            "end_row": max(end, title["row"]),
                            "basis": "block_title",
                            "kind_hint": kind,
                            "title_text": title["text"][:120],
                        }
                    )
            elif not candidate_ranges and (ws.max_row or 0) > 0:
                candidate_ranges.append(
                    {
                        "start_row": 1,
                        "end_row": ws.max_row or 1,
                        "basis": "whole_sheet",
                    }
                )

            xref = _cross_sheet_refs(ws, ws.title)
            for item in xref:
                for target in item["targets"]:
                    other = target.split("!", 1)[0].strip("'")
                    if other and other != ws.title:
                        edge_counter[(ws.title, other)] += 1

            sheets_out.append(
                {
                    "sheet": ws.title,
                    "sheet_state": state,
                    "rows": ws.max_row or 0,
                    "columns": ws.max_column or 0,
                    "headers": header_rows,
                    "order_key_columns": order_key_columns,
                    "block_title_rows": block_titles[:80],
                    "candidate_row_ranges": candidate_ranges[:80],
                    "ledger_run_hint_count": ledger_run_hint,
                    "cross_sheet_formula_refs": xref,
                }
            )

        index = {
            "schema_version": SCHEMA_VERSION,
            "source_sha256": digest,
            "sheets": sheets_out,
            "cross_sheet_edges": [
                {"from_sheet": a, "to_sheet": b, "count": n}
                for (a, b), n in sorted(edge_counter.items())
            ],
            "stats": {
                "sheet_count": len(sheets_out),
                "hidden_sheet_count": sum(
                    1 for s in sheets_out if s["sheet_state"] in {"hidden", "veryHidden"}
                ),
                "block_title_count": sum(len(s["block_title_rows"]) for s in sheets_out),
                "ledger_run_hint_total": sum(s["ledger_run_hint_count"] for s in sheets_out),
                "cross_sheet_edge_count": sum(edge_counter.values()),
            },
            "notes": [
                "Program-built structural facts only; not a business document inventory.",
                "ledger_run_hint_count is the count of consecutive (date, order_key) runs; candidate_row_ranges with basis ledger_key_run are atomic cut hints.",
                "Do not treat transport packet boundaries as document boundaries.",
                "Include hidden/veryHidden sheets as sheet_state facts for the operator/model.",
            ],
        }
        return index
    finally:
        wb.close()


def compress_structural_index_for_model(
    index: dict[str, Any], *, budget_bytes: int = STRUCTURAL_INDEX_MODEL_BUDGET_BYTES
) -> dict[str, Any]:
    """Return a size-bounded summary safe to inject into classify/group payloads."""
    if not isinstance(index, dict):
        return {}
    summary: dict[str, Any] = {
        "schema_version": index.get("schema_version") or SCHEMA_VERSION,
        "source_sha256": index.get("source_sha256"),
        "stats": index.get("stats") or {},
        "notes": (index.get("notes") or [])[:4],
        "cross_sheet_edges": (index.get("cross_sheet_edges") or [])[:40],
        "sheets": [],
    }
    for sheet in index.get("sheets") or []:
        entry = {
            "sheet": sheet.get("sheet"),
            "sheet_state": sheet.get("sheet_state", "visible"),
            "rows": sheet.get("rows"),
            "columns": sheet.get("columns"),
            "block_title_rows": [
                {
                    "row": t.get("row"),
                    "kind_hint": t.get("kind_hint"),
                    "text": (t.get("text") or "")[:100],
                }
                for t in (sheet.get("block_title_rows") or [])[:40]
            ],
            "order_key_columns": [
                {
                    "role": c.get("role"),
                    "col": c.get("col"),
                    "header_text": (c.get("header_text") or "")[:40],
                    "distinct_approx": c.get("distinct_approx"),
                    "sample_values": (c.get("sample_values") or [])[:5],
                    "inferred_from_data_shape": bool(c.get("inferred_from_data_shape")),
                }
                for c in (sheet.get("order_key_columns") or [])[:6]
            ],
            "candidate_row_ranges": [],
            "ledger_run_hint_count": sheet.get("ledger_run_hint_count") or 0,
            "cross_sheet_formula_refs": [
                {
                    "from_cell": r.get("from_cell"),
                    "targets": (r.get("targets") or [])[:4],
                }
                for r in (sheet.get("cross_sheet_formula_refs") or [])[:12]
            ],
        }
        for rng in sheet.get("candidate_row_ranges") or []:
            compact = {
                "start_row": rng.get("start_row"),
                "end_row": rng.get("end_row"),
                "basis": rng.get("basis"),
            }
            if "run_hint_count" in rng:
                compact["run_hint_count"] = rng["run_hint_count"]
                compact["run_boundary_samples"] = (rng.get("run_boundary_samples") or [])[:12]
            if rng.get("basis") == "ledger_key_run":
                if rng.get("order_key"):
                    compact["order_key"] = str(rng.get("order_key"))[:24]
                if rng.get("date"):
                    compact["date"] = str(rng.get("date"))[:24]
            if "kind_hint" in rng:
                compact["kind_hint"] = rng["kind_hint"]
            if "title_text" in rng:
                compact["title_text"] = (rng.get("title_text") or "")[:80]
            entry["candidate_row_ranges"].append(compact)
            if len(entry["candidate_row_ranges"]) >= 80:
                break
        summary["sheets"].append(entry)

    def encoded_size(payload: dict) -> int:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    # Progressive trim if over budget.
    while encoded_size(summary) > budget_bytes and summary["sheets"]:
        trimmed = False
        for sheet in summary["sheets"]:
            if sheet.get("cross_sheet_formula_refs"):
                sheet["cross_sheet_formula_refs"] = sheet["cross_sheet_formula_refs"][:-1]
                trimmed = True
                break
            ranges = sheet.get("candidate_row_ranges") or []
            if ranges and ranges[-1].get("run_boundary_samples"):
                ranges[-1]["run_boundary_samples"] = ranges[-1]["run_boundary_samples"][:-2]
                trimmed = True
                break
            if sheet.get("block_title_rows") and len(sheet["block_title_rows"]) > 3:
                sheet["block_title_rows"] = sheet["block_title_rows"][:-1]
                trimmed = True
                break
            if ranges and len(ranges) > 1:
                sheet["candidate_row_ranges"] = ranges[:-1]
                trimmed = True
                break
        if not trimmed:
            # Drop trailing sheets' verbose fields entirely.
            last = summary["sheets"][-1]
            if last.get("candidate_row_ranges"):
                last["candidate_row_ranges"] = []
            elif len(summary["sheets"]) > 1:
                summary["sheets"].pop()
            else:
                break
    summary["model_budget_bytes"] = budget_bytes
    summary["encoded_bytes"] = encoded_size(summary)
    return summary


def attach_structural_index_to_draft(
    draft: dict[str, Any], index: dict[str, Any]
) -> dict[str, Any]:
    """Product path: persist compact index on an EtlRun draft_json object (mutates+returns)."""
    if not isinstance(draft, dict):
        draft = {}
    draft["workbook_structural_index"] = compress_structural_index_for_model(index)
    draft["workbook_structural_index_full_sha256"] = index.get("source_sha256")
    draft["workbook_structural_index_schema"] = index.get("schema_version") or SCHEMA_VERSION
    return draft


def ensure_review_structural_index(
    review: dict[str, Any], body: bytes | None = None
) -> dict[str, Any]:
    """Attach full+compressed index onto a review dict when missing."""
    existing = review.get("workbook_structural_index")
    if isinstance(existing, dict) and existing.get("schema_version"):
        review.setdefault(
            "workbook_structural_index_for_model",
            compress_structural_index_for_model(existing),
        )
        return existing
    if body is None:
        return {}
    index = build_workbook_structural_index(body)
    review["workbook_structural_index"] = index
    review["workbook_structural_index_for_model"] = compress_structural_index_for_model(index)
    return index


def iter_visible_structural_candidates(index: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield visible-sheet layout/date-block atoms (skip hidden + whole_sheet fillers)."""
    out: list[dict[str, Any]] = []
    for sheet in index.get("sheets") or []:
        state = sheet.get("sheet_state") or "visible"
        if state in {"hidden", "veryHidden"}:
            continue
        name = sheet.get("sheet")
        if not isinstance(name, str) or not name:
            continue
        columns = max(1, int(sheet.get("columns") or 1))
        for cand in sheet.get("candidate_row_ranges") or []:
            basis = cand.get("basis") or ""
            if basis == "whole_sheet":
                continue
            try:
                start = int(cand["start_row"])
                end = int(cand["end_row"])
            except (KeyError, TypeError, ValueError):
                continue
            if end < start:
                continue
            out.append(
                {
                    "sheet": name,
                    "start_row": start,
                    "end_row": end,
                    "basis": basis,
                    "columns": columns,
                    "kind_hint": cand.get("kind_hint") or "",
                    "title_text": cand.get("title_text") or "",
                    "date": cand.get("date") or "",
                    "order_key": cand.get("order_key") or "",
                }
            )
    return out


def classification_from_structural_index(
    review: dict[str, Any],
    *,
    index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a classify-shaped result from layout + date-block structural candidates.

    Used when model/keyword classify misses: each visible candidate becomes one
    region and one suggested document (atomic). No workbook-title hardcodes.
    """
    from openpyxl.utils.cell import get_column_letter

    index = index or review.get("workbook_structural_index") or {}
    if not isinstance(index, dict) or not index.get("sheets"):
        raise ValueError("structural index missing")
    sheet_states = {
        overview["sheet"]: overview.get("sheet_state", "visible")
        for overview in review.get("sheet_overview", [])
    }
    candidates = iter_visible_structural_candidates(index)
    # Drop candidates on sheets the review already marked hidden.
    candidates = [
        c
        for c in candidates
        if sheet_states.get(c["sheet"], "visible") not in {"hidden", "veryHidden"}
    ]
    if not candidates:
        raise ValueError("no visible structural candidates")
    regions: list[dict] = []
    suggested: list[dict] = []
    for i, cand in enumerate(candidates, 1):
        c2 = cand["columns"]
        area = f"A{cand['start_row']}:{get_column_letter(c2)}{cand['end_row']}"
        reason = (
            f"结构索引{cand['basis']}原子"
            + (f"（{cand['title_text'][:40]}）" if cand.get("title_text") else "")
            + (
                f" date={cand['date']} order={cand['order_key']}"
                if cand.get("date") or cand.get("order_key")
                else ""
            )
        )
        region = {
            "sheet": cand["sheet"],
            "range": area,
            "labels": ["unknown"],
            "evidence": [],
            "dependencies": [],
            "reason": reason[:1000],
            "needs_confirmation": True,
            "label_source": "structural_index",
            "range_source": "structural_index",
            "structural_basis": cand["basis"],
        }
        regions.append(region)
        suggested.append(
            {
                "document_id": f"structural-{i:04d}",
                "fragments": [{"sheet": cand["sheet"], "range": area}],
                "status": "candidate",
                "reason": reason[:1000],
            }
        )
    coverage = []
    for overview in review.get("sheet_overview", []):
        name = overview["sheet"]
        state = overview.get("sheet_state", "visible")
        coverage.append(
            {
                "sheet": name,
                "unread": [],
                "unassigned": [],
                "merged_omitted": [],
                "drawing_unread": [],
                "drawing_unassigned": [],
                "merged_sent": len(overview.get("merged_regions") or []),
                "merged_ranges": list(overview.get("merged_regions") or []),
                "sheet_state": state,
            }
        )
    return {
        "source_sha256": review.get("sha256"),
        "model_status": "returned",
        "regions": regions,
        "suggested_documents": suggested,
        "logical_documents": suggested,
        "coverage": coverage,
        "layout_references": [],
        "contract": "structural_layout_dateblock_v1",
        "workbook_structural_index_source": "layout_dateblock_fallback",
        "input_summary": {
            "provider": "structural_index",
            "model": "layout_dateblock_fallback",
            "candidate_count": len(candidates),
        },
    }


def prefer_structural_classification_if_undersegmented(
    review: dict[str, Any],
    classification: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer layout/date-block atoms when keyword/model classify under-segments.

    Structural index is an independent atom inventory. Prefer it when classify is
    missing, model produced zero regions, or visible structural candidates strictly
    outnumber model regions (under-segmentation). Also prefer it when the model
    left multiple 1x1 orphan slices while structural has strictly more atoms.
    No workbook-specific count thresholds.
    """
    index = review.get("workbook_structural_index") or {}
    candidates = iter_visible_structural_candidates(index) if index else []
    sheet_states = {
        overview["sheet"]: overview.get("sheet_state", "visible")
        for overview in review.get("sheet_overview", [])
    }
    candidates = [
        c
        for c in candidates
        if sheet_states.get(c["sheet"], "visible") not in {"hidden", "veryHidden"}
    ]
    if not candidates:
        if classification is None:
            raise ReviewedExcelError("无结构索引候选且模型分类不可用")
        return classification

    if classification is None:
        return classification_from_structural_index(review, index=index)

    regions = classification.get("regions") or []
    model_n = len(regions)
    struct_n = len(candidates)
    orphan_singles = 0
    for region in regions:
        try:
            c1, r1, c2, r2 = bounded_range(region["range"])
        except (ReviewedExcelError, TypeError, ValueError):
            continue
        if c1 == c2 and r1 == r2:
            orphan_singles += 1

    undersegmented = struct_n > model_n
    orphan_promote = orphan_singles >= 2 and struct_n > model_n
    if undersegmented or orphan_promote or model_n == 0:
        return classification_from_structural_index(review, index=index)
    return classification
