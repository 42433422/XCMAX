"""LLM-assisted layout inference isolated from worksheet reading and business writes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.shipment_etl_profile import (
    ShipmentEtlProfile,
)

from .metadata import _merge_meta

if TYPE_CHECKING:
    from app.application.shipment_excel_etl_llm import SheetProbe


def _build_sheet_probe(
    ws, profile: ShipmentEtlProfile, *, rule_hint: dict[str, Any] | None = None
) -> SheetProbe:
    from app.application.shipment_excel_etl_llm import SheetProbe

    max_row = int(ws.max_row or 0)
    max_col = min(16, int(ws.max_column or 0) or 16)
    probe_n = min(10, max_row)
    probe_rows: list[dict[str, Any]] = []
    for row in range(1, probe_n + 1):
        cells = []
        for col in range(1, max_col + 1):
            raw = ws.cell(row, col).value
            if raw is None or str(raw).strip() == "":
                continue
            cells.append({"col": col, "text": str(raw).strip()[:80]})
        if cells:
            probe_rows.append({"row": row, "cells": cells})
    candidate_headers: list[dict[str, Any]] = []
    for row in range(1, min(16, max_row) + 1):
        cells = []
        for col in range(1, max_col + 1):
            raw = ws.cell(row, col).value
            text = str(raw).strip() if raw is not None else ""
            if not text:
                continue
            samples: list[str] = []
            for r in range(row + 1, min(row + 4, max_row + 1)):
                sv = ws.cell(r, col).value
                if sv is None or str(sv).strip() == "":
                    continue
                samples.append(str(sv).strip()[:40])
                if len(samples) >= 3:
                    break
            cells.append({"col": col, "header": text[:80], "samples": samples})
        if len(cells) >= 2:
            candidate_headers.append({"row": row, "cells": cells})
    return SheetProbe(
        profile_id=profile.id,
        sheet_title=str(ws.title or ""),
        probe_rows=probe_rows,
        candidate_headers=candidate_headers[:8],
        max_row=max_row,
        max_col=max_col,
        rule_hint=dict(rule_hint or {}),
    )


def _apply_llm_assist_to_layout(
    ws,
    profile: ShipmentEtlProfile,
    *,
    delivery_score: int,
    ledger_score: int,
    min_score: int,
    header_row: int | None,
    mapping: dict[str, int],
    meta: dict[str, str] | None,
    prefer_kind: str | None,
    fallback_unit: str = "",
) -> tuple[int | None, dict[str, int], dict[str, str], str | None, dict[str, Any]]:
    """低置信时请求 LLM；返回 (header_row, mapping, meta, source_kind, assist_public)."""
    from app.application.shipment_excel_etl_llm import assist_sheet_layout, needs_llm_assist

    need, reason = needs_llm_assist(
        delivery_score=delivery_score,
        ledger_score=ledger_score,
        min_score=min_score,
        header_row=header_row,
        mapping=mapping,
        meta=meta,
        prefer_kind=prefer_kind,
        fallback_unit=fallback_unit,
    )
    assist_public: dict[str, Any] = {
        "used_llm": False,
        "cache_hit": False,
        "ok": False,
        "confidence": 1.0 if not need else 0.0,
        "reason": reason,
    }
    if not need:
        assist_public["ok"] = True
        return (header_row, mapping, dict(meta or {}), prefer_kind, assist_public)
    probe = _build_sheet_probe(
        ws,
        profile,
        rule_hint={
            "delivery_score": delivery_score,
            "ledger_score": ledger_score,
            "min_score": min_score,
            "prefer_kind": prefer_kind,
            "rule_header_row": header_row,
            "rule_mapping": mapping,
            "rule_meta": meta or {},
            "assist_reason": reason,
        },
    )
    assist = assist_sheet_layout(probe)
    assist_public = assist.as_public_dict()
    if not assist.ok:
        return (header_row, mapping, dict(meta or {}), prefer_kind, assist_public)
    new_header = assist.header_row if assist.header_row is not None else header_row
    new_mapping = dict(mapping)
    for field_name, col in (assist.columns or {}).items():
        if field_name not in new_mapping and isinstance(col, int) and (col > 0):
            new_mapping[field_name] = col
    for field_name, col in (assist.columns or {}).items():
        if field_name in {
            "product_name",
            "model_number",
            "order_number",
            "quantity_tins",
            "quantity_kg",
        }:
            if field_name not in mapping and isinstance(col, int) and (col > 0):
                new_mapping[field_name] = col
    new_meta = _merge_meta(dict(meta or {}), assist.meta or {}, prefer_overlay=True)
    kind = (
        assist.source_kind
        if assist.source_kind in {"delivery_note", "shipment_ledger", "ignore"}
        else prefer_kind
    )
    return (new_header, new_mapping, new_meta, kind, assist_public)
