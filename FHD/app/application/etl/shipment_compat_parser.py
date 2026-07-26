"""Read-only shipment-profile compatibility parsing for the general ETL engine."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.application.etl.errors import EtlError
from app.application.etl.parser_types import ParsedDataset, ParsedRow


def _is_unreliable_filename_fallback(note: dict[str, Any], path: Path) -> bool:
    unit_name = str(note.get("unit_name") or "").strip()
    assist = note.get("assist") if isinstance(note.get("assist"), dict) else {}
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
        from app.application.shipment_excel_etl_app_service import (
            preview_shipment_excel_etl,
        )

        result = preview_shipment_excel_etl(path, include_ledger=False)
    except Exception:  # noqa: BLE001 - compatibility detection is a non-blocking probe
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

    def append(sheet: str, values: dict[str, Any], source: dict[str, Any]) -> None:
        if len(rows) >= max_rows:
            raise EtlError(
                "ETL_ROW_LIMIT_EXCEEDED",
                f"文件超过 {max_rows} 行限制",
                status_code=413,
            )
        row_number = len(rows) + 1
        headers.extend(key for key in values if key not in headers)
        rows.append(
            ParsedRow(
                sheet=sheet or "送货单",
                row_number=row_number,
                values={key: value for key, value in values.items() if value not in (None, "")},
                provenance={
                    "sheet": sheet or "送货单",
                    "row": row_number,
                    "compatibility_profile": str(source.get("profile_id") or "universal"),
                    "source_kind": "shipment_delivery",
                    "source_fingerprint": source.get("fingerprint"),
                    "original_fragment": values,
                },
            )
        )

    for note in notes:
        if not isinstance(note, dict):
            continue
        sheet = str(note.get("sheet") or note.get("sheet_name") or "送货单")
        unit_name, inherited_unit = resolved_unit_name(note, sheet)
        if not unit_name:
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
            append(
                sheet,
                {
                    "customer_name": unit_name,
                    "contact_person": _contact_person(note),
                    "contact_phone": note.get("contact_phone") or note.get("phone"),
                    "contact_address": note.get("contact_address") or note.get("address"),
                },
                source_note,
            )
            continue
        for item_index, item in enumerate(note.get("items") or [], start=1):
            if not isinstance(item, dict) or not _is_business_item(item):
                continue
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
            else:
                values = _shipment_item_values(
                    note,
                    item,
                    unit_name=unit_name,
                    item_index=item_index,
                )
            append(sheet, values, source_note)

    if not rows:
        return None
    warnings = [
        {
            "code": "ETL_COMPATIBILITY_PROFILE_APPLIED",
            "message": "已使用原送货单兼容预设解析；执行仍需在通用 ETL 中预演确认。",
        }
    ]
    if skipped_sheets:
        warnings.append(
            {
                "code": "ETL_COMPATIBILITY_LOW_CONFIDENCE_SHEETS_SKIPPED",
                "message": f"已跳过 {len(skipped_sheets)} 个无法可靠识别业务主体的工作表。",
                "sheets": skipped_sheets[:20],
            }
        )
    if inherited_unit_sheets:
        warnings.append(
            {
                "code": "ETL_COMPATIBILITY_UNIT_INHERITED",
                "message": f"有 {len(inherited_unit_sheets)} 个产品明细表沿用同文件已确认的客户名称。",
                "sheets": inherited_unit_sheets[:20],
            }
        )
    return ParsedDataset(
        headers=headers,
        rows=rows,
        source_features={
            "kind": "shipment_profile",
            "compatibility_preset": True,
            "profile_ids": sorted(
                {
                    str(note.get("profile_id") or "universal")
                    for note in notes
                    if isinstance(note, dict)
                }
            ),
            "note_count": len(notes) - len(skipped_sheets),
            "skipped_note_count": len(skipped_sheets),
            "inherited_unit_note_count": len(inherited_unit_sheets),
            "headers": headers,
        },
        warnings=warnings,
    )
