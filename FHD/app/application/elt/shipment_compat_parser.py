"""Read-only shipment-profile compatibility parsing for the general ETL engine."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.application.elt.errors import EltError
from app.application.elt.parser_types import ParsedDataset, ParsedRow
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _is_unreliable_filename_fallback(note: dict[str, Any], path: Path) -> bool:
    unit_name = str(note.get("unit_name") or "").strip()
    assist = note.get("assist") if isinstance(note.get("assist"), dict) else {}
    if not isinstance(assist, dict):
        assist = {}
    lacks_business_identity = not str(note.get("order_number") or "").strip() and not bool(
        assist.get("ok")
    )
    return bool(unit_name) and unit_name == path.stem and lacks_business_identity


def _is_reliable_note(note: dict[str, Any], path: Path) -> bool:
    return bool(str(note.get("unit_name") or "").strip()) and not (
        _is_unreliable_filename_fallback(note, path)
    )


def _is_business_item(item: dict[str, Any]) -> bool:
    name = str(item.get("product_name") or "").strip()
    model = re.sub(r"\s+", "", str(item.get("model_number") or ""))
    if not name or "大写人民币" in model:
        return False
    return name not in {"合计", "总计", "金额合计", "人民币合计"}


def _contact_person(note: dict[str, Any]) -> str | None:
    value = str(note.get("contact_person") or "").strip()
    compact = re.sub(r"\s+", "", value)
    if not value or re.match(r"^(日期|制单日期)[:：]?\d{4}[年./-]", compact):
        return None
    return value


_SHIPMENT_FIELDS = {
    "purchase_unit": "unit_name",
    "external_order_no": "order_number",
    "product_name": "product_name",
    "model_number": "model_number",
    "quantity_kg": "quantity_kg",
    "quantity_tins": "quantity_tins",
    "tin_spec": "tin_spec",
    "unit_price": "unit_price",
    "amount": "amount",
}
_PRODUCT_FIELDS = {
    "model_number": "model_number",
    "name": "product_name",
    "specification": "tin_spec",
    "price": "unit_price",
    "unit": "unit_name",
    "customer_name": "unit_name",
}
_NOTE_FIELDS = {"customer_name": "unit_name", "contact_person": "contact_person"}


def _cell_lineage(
    note: dict[str, Any], item: dict[str, Any], fields: dict[str, str], values: dict[str, Any]
) -> dict[str, Any]:
    """Map each emitted field to the workbook cell it was read from or computed out of."""
    from openpyxl.utils import get_column_letter

    def mapping(source: dict[str, Any], key: str) -> dict[str, Any]:
        value = source.get(key)
        return value if isinstance(value, dict) else {}

    row = item.get("source_row")
    columns = mapping(item, "source_columns")
    note_cells = mapping(note, "source_cells")
    derived_fields = mapping(item, "derived_fields")

    def cell(source_field: str) -> str | None:
        col = columns.get(source_field)
        if isinstance(row, int) and isinstance(col, int):
            return f"{get_column_letter(col)}{row}"
        return note_cells.get(source_field)

    cells: dict[str, str] = {}
    derived: dict[str, list[str]] = {}
    value_sources: dict[str, str] = {}
    for target, source_field in fields.items():
        if values.get(target) in (None, ""):
            continue
        if source_field in derived_fields:
            derived[target] = [c for c in map(cell, derived_fields[source_field]) if c]
        elif located := cell(source_field):
            cells[target] = located
        elif source_field == "unit_name":
            value_sources[target] = (
                "inherited_note"
                if note.get("compatibility_unit_inherited")
                else str(note.get("unit_source") or "sheet")
            )
    return {"cells": cells, "derived": derived, "value_sources": value_sources}


def _shipment_item_values(
    note: dict[str, Any],
    item: dict[str, Any],
    *,
    unit_name: str,
    item_index: int,
) -> dict[str, Any]:
    note_fingerprint = str(note.get("fingerprint") or "")
    item_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "note": note_fingerprint,
                "index": item_index,
                "model": item.get("model_number"),
                "name": item.get("product_name"),
                "kg": item.get("quantity_kg"),
                "tins": item.get("quantity_tins") or item.get("quantity"),
                "price": item.get("unit_price"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "purchase_unit": unit_name,
        "external_order_no": note.get("order_number"),
        "source_fingerprint": item_fingerprint,
        "legacy_note_fingerprint": note_fingerprint,
        "product_name": item.get("product_name"),
        "model_number": item.get("model_number"),
        "quantity_kg": item.get("quantity_kg"),
        "quantity_tins": item.get("quantity_tins") or item.get("quantity"),
        "tin_spec": item.get("tin_spec") or item.get("spec_per_tin"),
        "unit_price": item.get("unit_price"),
        "amount": item.get("amount"),
    }


def parse_delivery_note_with_compat_profile(
    path: Path,
    *,
    target_type: str,
    max_rows: int,
    compatibility_preset_id: str | None = None,
) -> ParsedDataset | None:
    """Convert proven shipment profiles into general-ETL source rows."""

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return None
    if target_type not in {
        "customer_products",
        "customers",
        "products",
        "shipment_records",
    }:
        return None
    try:
        from app.application.shipment_excel_elt_app_service import (
            preview_shipment_excel_etl,
        )

        result = preview_shipment_excel_etl(
            path,
            include_ledger=False,
            profile_id=compatibility_preset_id,
        )
    except RECOVERABLE_ERRORS:
        return None
    notes = result.get("notes") if isinstance(result, dict) else None
    if not result.get("success") or not isinstance(notes, list) or not notes:
        return None

    rows: list[ParsedRow] = []
    headers: list[str] = []
    skipped_sheets: list[str] = []
    inherited_unit_sheets: list[str] = []
    primary_units = {
        str(note.get("unit_name") or "").strip()
        for note in notes
        if isinstance(note, dict) and _is_reliable_note(note, path)
    }

    def resolved_unit_name(note: dict[str, Any], sheet: str) -> tuple[str, bool]:
        unit_name = str(note.get("unit_name") or "").strip()
        if _is_reliable_note(note, path):
            return unit_name, False
        finance_sheet = bool(re.search(r"回款|付款|收款|对账|统计|汇总|余额|账龄", sheet))
        if (
            target_type in {"customer_products", "products"}
            and _is_unreliable_filename_fallback(note, path)
            and len(primary_units) == 1
            and not finance_sheet
        ):
            return next(iter(primary_units)), True
        return "", False

    used_rows: dict[str, set[int]] = {}

    def append(
        sheet: str,
        values: dict[str, Any],
        source: dict[str, Any],
        item: dict[str, Any],
        fields: dict[str, str],
    ) -> None:
        if len(rows) >= max_rows:
            raise EltError(
                "ELT_ROW_LIMIT_EXCEEDED",
                f"文件超过 {max_rows} 行限制",
                status_code=413,
            )
        sheet = sheet or "送货单"
        taken = used_rows.setdefault(sheet, set())
        source_row = item.get("source_row")
        # (run, sheet, row) is unique downstream; synthetic rows sit past the real ones.
        if not isinstance(source_row, int) or source_row in taken:
            source_row = max(taken, default=0) + 1
        taken.add(source_row)
        headers.extend(key for key in values if key not in headers)
        rows.append(
            ParsedRow(
                sheet=sheet,
                row_number=source_row,
                values={key: value for key, value in values.items() if value not in (None, "")},
                provenance={
                    "sheet": sheet,
                    "row": source_row,
                    "compatibility_profile": str(source.get("profile_id") or "universal"),
                    "source_kind": "shipment_delivery",
                    "source_fingerprint": source.get("fingerprint"),
                    "original_fragment": values,
                    **_cell_lineage(source, item, fields, values),
                },
            )
        )

    for note in notes:
        if not isinstance(note, dict):
            continue
        sheet = str(note.get("sheet") or note.get("sheet_name") or "送货单")
        unit_name, inherited_unit = resolved_unit_name(note, sheet)
        row_units = [
            str(item.get("unit_name") or "").strip()
            for item in note.get("items") or []
            if isinstance(item, dict)
        ]
        if not unit_name and not (row_units and all(row_units)):
            skipped_sheets.append(sheet)
            continue
        source_note = note
        if inherited_unit:
            inherited_unit_sheets.append(sheet)
            source_note = {
                **note,
                "compatibility_unit_inherited": True,
                "inherited_unit_name": unit_name,
            }
        if target_type == "customers":
            unit_cell = str((note.get("source_cells") or {}).get("unit_name") or "")
            row_match = re.search(r"\d+$", unit_cell)
            append(
                sheet,
                {
                    "customer_name": unit_name,
                    "contact_person": _contact_person(note),
                    "contact_phone": note.get("contact_phone") or note.get("phone"),
                    "contact_address": note.get("contact_address") or note.get("address"),
                },
                source_note,
                {"source_row": int(row_match.group())} if row_match else {},
                _NOTE_FIELDS,
            )
            continue
        note_unit = unit_name
        for item_index, item in enumerate(note.get("items") or [], start=1):
            if not isinstance(item, dict) or not _is_business_item(item):
                continue
            unit_name = str(item.get("unit_name") or "").strip() or note_unit
            if target_type in {"customer_products", "products"}:
                values = {
                    "model_number": item.get("model_number"),
                    "name": item.get("product_name"),
                    "specification": item.get("specification") or item.get("tin_spec"),
                    "price": item.get("unit_price"),
                    "description": item.get("description"),
                }
                if target_type == "customer_products":
                    values.update(
                        {
                            "customer_name": unit_name,
                            "contact_person": _contact_person(note),
                            "contact_phone": note.get("contact_phone") or note.get("phone"),
                            "contact_address": note.get("contact_address") or note.get("address"),
                        }
                    )
                else:
                    values["unit"] = unit_name
                fields = {**_PRODUCT_FIELDS, "contact_person": "contact_person"}
            else:
                values = _shipment_item_values(
                    note,
                    item,
                    unit_name=unit_name,
                    item_index=item_index,
                )
                fields = _SHIPMENT_FIELDS
            append(sheet, values, source_note, item, fields)

    if not rows:
        return None
    warnings: list[dict[str, Any]] = [
        {
            "code": "ELT_COMPATIBILITY_PROFILE_APPLIED",
            "message": "已使用原送货单兼容预设解析；执行仍需在通用 ETL 中预演确认。",
        }
    ]
    if skipped_sheets:
        warnings.append(
            {
                "code": "ELT_COMPATIBILITY_LOW_CONFIDENCE_SHEETS_SKIPPED",
                "message": f"已跳过 {len(skipped_sheets)} 个无法可靠识别业务主体的工作表。",
                "sheets": skipped_sheets[:20],
            }
        )
    if inherited_unit_sheets:
        warnings.append(
            {
                "code": "ELT_COMPATIBILITY_UNIT_INHERITED",
                "message": f"有 {len(inherited_unit_sheets)} 个产品明细表沿用同文件已确认的客户名称。",
                "sheets": inherited_unit_sheets[:20],
            }
        )
    source_features: dict[str, Any] = {
        "kind": "shipment_profile",
        "compatibility_preset": True,
        "profile_ids": sorted(
            {str(note.get("profile_id") or "universal") for note in notes if isinstance(note, dict)}
        ),
        "note_count": len(notes) - len(skipped_sheets),
        "skipped_note_count": len(skipped_sheets),
        "inherited_unit_note_count": len(inherited_unit_sheets),
        "headers": headers,
    }
    if compatibility_preset_id:
        source_features["compatibility_preset_id"] = compatibility_preset_id
    return ParsedDataset(
        headers=headers,
        rows=rows,
        source_features=source_features,
        warnings=warnings,
    )
