"""Delivery and ledger decoding with shared layout resolution and narrow inference ports."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.application.shipment_etl_profile import (
    ShipmentEtlProfile,
)

from .layout import (
    _find_header_row,
    _find_ledger_header_row,
    _infer_columns_from_samples,
    _joined_row,
    _map_headers,
    _score_delivery_sheet,
    _score_ledger_sheet,
)
from .notes import _build_item_from_row, _enrich_note, _excel_date_to_str, _parse_items


class RememberLayout(Protocol):
    def __call__(
        self,
        ws: Any,
        *,
        header_row: int,
        mapping: dict[str, int],
        profile: ShipmentEtlProfile,
        source: str = "learned",
    ) -> str: ...


class AssistLayout(Protocol):
    def __call__(
        self,
        ws: Any,
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
    ) -> tuple[int | None, dict[str, int], dict[str, str], str | None, dict[str, Any]]: ...


@dataclass(frozen=True)
class SheetParserPorts:
    resolve_memory: Callable[[Any], tuple[int | None, dict[str, int], str]]
    remember: RememberLayout
    buyer_metadata: Callable[[Any, int, ShipmentEtlProfile], dict[str, str]]
    assist: AssistLayout


class SheetParser:
    def __init__(self, ports: SheetParserPorts) -> None:
        self._ports = ports

    def _layout(
        self, ws: Any, profile: ShipmentEtlProfile, *, ledger: bool
    ) -> tuple[int, int, int | None, dict[str, int], str]:
        delivery_score = _score_delivery_sheet(ws, profile)
        ledger_score = _score_ledger_sheet(ws, profile)
        memory_header, memory_mapping, fingerprint = self._ports.resolve_memory(ws)
        find_header = _find_ledger_header_row if ledger else _find_header_row
        header = memory_header if memory_header is not None else find_header(ws, profile)
        mapping = (
            dict(memory_mapping)
            if memory_mapping
            else (_map_headers(ws, header, profile) if header is not None else {})
        )
        return delivery_score, ledger_score, header, mapping, fingerprint

    def delivery(
        self, ws, *, fallback_unit: str, profile: ShipmentEtlProfile, allow_llm: bool = True
    ) -> dict[str, Any] | None:
        d_score, l_score, header_row, mapping, kb_fp = self._layout(ws, profile, ledger=False)
        meta = (
            self._ports.buyer_metadata(ws, header_row, profile)
            if header_row is not None
            else {
                "unit_name": "",
                "contact_person": "",
                "order_date": "",
                "order_number": "",
                "title": "",
            }
        )
        assist_public: dict[str, Any] = {
            "used_llm": False,
            "cache_hit": bool(kb_fp),
            "ok": bool(kb_fp and mapping),
            "confidence": 1.0,
            "reason": "knowledge_base_hit" if kb_fp else "rules_only",
            "layout_fingerprint": kb_fp or "",
        }
        from app.application.shipment_excel_etl_llm import unit_name_is_weak

        unit_weak = unit_name_is_weak(
            str((meta or {}).get("unit_name") or ""), fallback=fallback_unit
        )
        if allow_llm and (not kb_fp or unit_weak):
            header_row, mapping, meta, kind, assist_public = self._ports.assist(
                ws,
                profile,
                delivery_score=d_score,
                ledger_score=l_score,
                min_score=profile.delivery_min_score,
                header_row=header_row,
                mapping=mapping,
                meta=meta,
                prefer_kind="delivery_note",
                fallback_unit=fallback_unit,
            )
            if kind == "ignore":
                return None
            if kind == "shipment_ledger":
                return None
            if kb_fp and (not assist_public.get("layout_fingerprint")):
                assist_public["layout_fingerprint"] = kb_fp
        heuristic_on = str(
            os.environ.get("FHD_EXCEL_ETL_HEURISTIC") or "1"
        ).strip().lower() not in {"0", "false", "no", "off"}
        if (
            heuristic_on
            and header_row is not None
            and ("product_name" not in mapping and "model_number" not in mapping)
        ):
            inferred = _infer_columns_from_samples(ws, header_row, mapping)
            if "product_name" in inferred or "model_number" in inferred:
                mapping = inferred
                if not assist_public.get("used_llm"):
                    assist_public = {
                        **assist_public,
                        "ok": True,
                        "confidence": 0.65,
                        "reason": "heuristic_samples",
                    }
        if header_row is None:
            return None
        if "product_name" not in mapping and "model_number" not in mapping:
            return None
        items = _parse_items(ws, header_row, mapping, profile)
        if not items:
            return None
        remembered_fp = self._ports.remember(
            ws,
            header_row=header_row,
            mapping=mapping,
            profile=profile,
            source="knowledge_base"
            if kb_fp
            else "llm"
            if assist_public.get("used_llm")
            else "rules",
        )
        if remembered_fp and (not assist_public.get("layout_fingerprint")):
            assist_public["layout_fingerprint"] = remembered_fp
        unit = meta.get("unit_name") or fallback_unit
        note = _enrich_note(
            {
                "sheet": ws.title,
                "source_kind": "delivery_note",
                "score": d_score,
                "unit_name": unit,
                "contact_person": meta.get("contact_person") or "",
                "order_date": meta.get("order_date") or "",
                "order_number": meta.get("order_number") or "",
                "title": meta.get("title") or "",
                "items": items,
                "assist": assist_public,
            }
        )
        return note

    def ledger(
        self, ws, *, fallback_unit: str, profile: ShipmentEtlProfile, allow_llm: bool = True
    ) -> list[dict[str, Any]]:
        d_score, l_score, header_row, mapping, kb_fp = self._layout(ws, profile, ledger=True)
        meta: dict[str, str] = {
            "unit_name": "",
            "contact_person": "",
            "order_date": "",
            "order_number": "",
            "title": "",
        }
        assist_public: dict[str, Any] = {
            "used_llm": False,
            "cache_hit": bool(kb_fp),
            "ok": bool(kb_fp and mapping),
            "confidence": 1.0,
            "reason": "knowledge_base_hit" if kb_fp else "rules_only",
            "layout_fingerprint": kb_fp or "",
        }
        if allow_llm and (not kb_fp):
            header_row, mapping, meta, kind, assist_public = self._ports.assist(
                ws,
                profile,
                delivery_score=d_score,
                ledger_score=l_score,
                min_score=profile.delivery_min_score,
                header_row=header_row,
                mapping=mapping,
                meta=meta,
                prefer_kind="shipment_ledger",
                fallback_unit=fallback_unit,
            )
            if kind == "ignore":
                return []
            if kind == "delivery_note":
                return []
        if header_row is None:
            return []
        if "order_number" not in mapping:
            return []
        if "product_name" not in mapping and "model_number" not in mapping:
            return []
        self._ports.remember(
            ws,
            header_row=header_row,
            mapping=mapping,
            profile=profile,
            source="knowledge_base"
            if kb_fp
            else "llm"
            if assist_public.get("used_llm")
            else "rules",
        )
        title_tpl = str((profile.ledger or {}).get("title_template") or "{unit}/{order_no}")
        unit_fallback = str(meta.get("unit_name") or fallback_unit).strip() or fallback_unit
        groups: dict[str, dict[str, Any]] = {}
        max_row = int(ws.max_row or 0)
        for row in range(header_row + 1, max_row + 1):
            joined = _joined_row(ws, row)
            if not joined:
                continue
            order_no = str(ws.cell(row, mapping["order_number"]).value or "").strip()
            if not order_no:
                continue
            item = _build_item_from_row(ws, row, mapping)
            if not item:
                continue
            order_date = ""
            if "order_date" in mapping:
                order_date = _excel_date_to_str(ws.cell(row, mapping["order_date"]).value, profile)
            bucket = groups.setdefault(
                order_no,
                {
                    "sheet": ws.title,
                    "source_kind": "shipment_ledger",
                    "score": l_score,
                    "unit_name": unit_fallback,
                    "contact_person": meta.get("contact_person") or "",
                    "order_date": order_date,
                    "order_number": order_no,
                    "title": title_tpl.format(unit=unit_fallback, order_no=order_no),
                    "items": [],
                    "assist": assist_public,
                },
            )
            if order_date and (not bucket.get("order_date")):
                bucket["order_date"] = order_date
            bucket["items"].append(item)
        return [_enrich_note(g) for g in groups.values() if g.get("items")]
