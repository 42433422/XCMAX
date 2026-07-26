"""通用表格与 OCR 输入解析。"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.application.etl.errors import EtlError

MAX_ROWS = 100_000
STRUCTURED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
OCR_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
KNOWLEDGE_ONLY_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx"}
SUPPORTED_SUFFIXES = STRUCTURED_SUFFIXES | OCR_SUFFIXES | KNOWLEDGE_ONLY_SUFFIXES


@dataclass(slots=True)
class ParsedRow:
    sheet: str
    row_number: int
    values: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDataset:
    headers: list[str]
    rows: list[ParsedRow]
    source_features: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _clean_header(value: Any, index: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:160] if text else f"未命名列{index}"


def _unique_headers(values: Iterable[Any]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, raw in enumerate(values, start=1):
        base = _clean_header(raw, index)
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def _header_score(values: list[Any]) -> float:
    cells = [str(value or "").strip() for value in values]
    non_empty = [value for value in cells if value]
    if len(non_empty) < 2:
        return -1
    unique_ratio = len(set(non_empty)) / len(non_empty)
    text_ratio = sum(not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value) for value in non_empty) / len(
        non_empty
    )
    return len(non_empty) + unique_ratio + text_ratio


def _parse_workbook(path: Path, max_rows: int) -> ParsedDataset:
    from openpyxl import load_workbook

    workbook = load_workbook(
        path,
        read_only=True,
        data_only=True,
        keep_links=False,
    )
    result: list[ParsedRow] = []
    all_headers: list[str] = []
    sheets: list[dict[str, Any]] = []
    try:
        for worksheet in workbook.worksheets:
            probe = list(worksheet.iter_rows(min_row=1, max_row=20, values_only=True))
            if not probe:
                continue
            header_offset, header_values = max(
                enumerate(probe), key=lambda item: _header_score(list(item[1]))
            )
            if _header_score(list(header_values)) < 0:
                continue
            headers = _unique_headers(header_values)
            all_headers.extend(header for header in headers if header not in all_headers)
            sheet_count = 0
            for row_number, values in enumerate(
                worksheet.iter_rows(min_row=header_offset + 2, values_only=True),
                start=header_offset + 2,
            ):
                if len(result) >= max_rows:
                    raise EtlError(
                        "ETL_ROW_LIMIT_EXCEEDED",
                        f"文件超过 {max_rows} 行限制",
                        status_code=413,
                    )
                data = {
                    headers[index]: value
                    for index, value in enumerate(values[: len(headers)])
                    if value not in (None, "")
                }
                if not data:
                    continue
                result.append(
                    ParsedRow(
                        sheet=worksheet.title,
                        row_number=row_number,
                        values=data,
                        provenance={
                            "sheet": worksheet.title,
                            "row": row_number,
                            "original_fragment": {
                                headers[index]: value
                                for index, value in enumerate(values[: len(headers)])
                            },
                        },
                    )
                )
                sheet_count += 1
            sheets.append(
                {
                    "name": worksheet.title,
                    "header_row": header_offset + 1,
                    "row_count": sheet_count,
                }
            )
    finally:
        workbook.close()
    return ParsedDataset(
        headers=all_headers,
        rows=result,
        source_features={"kind": "workbook", "sheets": sheets, "headers": all_headers},
    )


def _csv_reader(path: Path):
    for encoding in ("utf-8-sig", "gb18030"):
        handle = None
        try:
            handle = path.open("r", encoding=encoding, newline="")
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            return handle, csv.reader(handle, dialect)
        except UnicodeDecodeError:
            if handle is not None:
                handle.close()
            continue
    raise EtlError("ETL_CSV_ENCODING_UNSUPPORTED", "CSV 编码无法识别")


def _parse_csv(path: Path, max_rows: int) -> ParsedDataset:
    handle, reader = _csv_reader(path)
    try:
        try:
            headers = _unique_headers(next(reader))
        except StopIteration:
            return ParsedDataset(headers=[], rows=[], source_features={"kind": "csv"})
        rows: list[ParsedRow] = []
        for row_number, values in enumerate(reader, start=2):
            if len(rows) >= max_rows:
                raise EtlError(
                    "ETL_ROW_LIMIT_EXCEEDED", f"文件超过 {max_rows} 行限制", status_code=413
                )
            data = {
                headers[index]: value
                for index, value in enumerate(values[: len(headers)])
                if value != ""
            }
            if not data:
                continue
            rows.append(
                ParsedRow(
                    sheet="CSV",
                    row_number=row_number,
                    values=data,
                    provenance={
                        "sheet": "CSV",
                        "row": row_number,
                        "original_fragment": dict(zip(headers, values)),
                    },
                )
            )
        return ParsedDataset(
            headers=headers,
            rows=rows,
            source_features={"kind": "csv", "headers": headers, "row_count": len(rows)},
        )
    finally:
        handle.close()


def _parse_delivery_note_with_compat_profile(
    path: Path,
    *,
    target_type: str,
    max_rows: int,
) -> ParsedDataset | None:
    """Convert the proven shipment profiles into general-ETL source rows.

    This is a read-only compatibility preset: execution still goes through the
    general preview/confirmation engine and its target adapters.
    """

    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return None
    if target_type not in {"customers", "products", "shipment_records"}:
        return None
    try:
        from app.application.shipment_excel_etl_app_service import (
            preview_shipment_excel_etl,
        )

        result = preview_shipment_excel_etl(path, include_ledger=False)
    except Exception:  # noqa: BLE001 - profile detection is a non-blocking preset probe
        return None
    notes = result.get("notes") if isinstance(result, dict) else None
    if not result.get("success") or not isinstance(notes, list) or not notes:
        return None

    rows: list[ParsedRow] = []
    headers: list[str] = []
    skipped_sheets: list[str] = []
    inherited_unit_sheets: list[str] = []

    def note_uses_unreliable_filename_fallback(note: dict[str, Any]) -> bool:
        unit_name = str(note.get("unit_name") or "").strip()
        assist = note.get("assist") if isinstance(note.get("assist"), dict) else {}
        used_filename_fallback = bool(unit_name) and unit_name == path.stem
        lacks_business_identity = (
            not str(note.get("order_number") or "").strip()
            and not bool(assist.get("ok"))
        )
        return used_filename_fallback and lacks_business_identity

    def note_is_reliable(note: dict[str, Any]) -> bool:
        return bool(str(note.get("unit_name") or "").strip()) and not (
            note_uses_unreliable_filename_fallback(note)
        )

    primary_units = {
        str(note.get("unit_name") or "").strip()
        for note in notes
        if isinstance(note, dict) and note_is_reliable(note)
    }

    def resolved_unit_name(note: dict[str, Any], sheet: str) -> tuple[str, bool]:
        unit_name = str(note.get("unit_name") or "").strip()
        if note_is_reliable(note):
            return unit_name, False
        finance_sheet = bool(re.search(r"回款|付款|收款|对账|统计|汇总|余额|账龄", sheet))
        if (
            target_type == "products"
            and note_uses_unreliable_filename_fallback(note)
            and len(primary_units) == 1
            and not finance_sheet
        ):
            return next(iter(primary_units)), True
        return "", False

    def item_is_business_row(item: dict[str, Any]) -> bool:
        name = str(item.get("product_name") or "").strip()
        model = re.sub(r"\s+", "", str(item.get("model_number") or ""))
        if not name or "大写人民币" in model:
            return False
        return name not in {"合计", "总计", "金额合计", "人民币合计"}

    def resolved_contact_person(note: dict[str, Any]) -> str | None:
        value = str(note.get("contact_person") or "").strip()
        compact = re.sub(r"\s+", "", value)
        if not value or re.match(r"^(日期|制单日期)[:：]?\d{4}[年./-]", compact):
            return None
        return value

    def append(sheet: str, values: dict[str, Any], source: dict[str, Any]) -> None:
        if len(rows) >= max_rows:
            raise EtlError(
                "ETL_ROW_LIMIT_EXCEEDED",
                f"文件超过 {max_rows} 行限制",
                status_code=413,
            )
        row_number = len(rows) + 1
        for key in values:
            if key not in headers:
                headers.append(key)
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
                    "contact_person": resolved_contact_person(note),
                    "contact_phone": note.get("contact_phone") or note.get("phone"),
                    "contact_address": note.get("contact_address") or note.get("address"),
                },
                source_note,
            )
            continue
        for item_index, item in enumerate(note.get("items") or [], start=1):
            if not isinstance(item, dict):
                continue
            if not item_is_business_row(item):
                continue
            if target_type == "products":
                values = {
                    "unit": unit_name,
                    "model_number": item.get("model_number"),
                    "name": item.get("product_name"),
                    "specification": item.get("specification") or item.get("tin_spec"),
                    "price": item.get("unit_price"),
                    "description": item.get("description"),
                }
            else:
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
                values = {
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


def parse_file(path: str | Path, *, target_type: str, max_rows: int = MAX_ROWS) -> ParsedDataset:
    source = Path(path).expanduser().resolve()
    suffix = source.suffix.lower()
    if not source.is_file():
        raise EtlError("ETL_UPLOAD_MISSING", "上传文件不存在", status_code=404)
    if suffix not in SUPPORTED_SUFFIXES:
        raise EtlError("ETL_FILE_TYPE_UNSUPPORTED", f"不支持的文件类型: {suffix}")
    if suffix in KNOWLEDGE_ONLY_SUFFIXES:
        if target_type != "knowledge":
            raise EtlError(
                "ETL_KNOWLEDGE_ONLY_FILE",
                "Word/PPT 仅可导入知识库，不支持结构化业务写入",
            )
        return ParsedDataset(
            headers=["document_path"],
            rows=[
                ParsedRow(
                    sheet="文档",
                    row_number=1,
                    values={"document_path": str(source)},
                    provenance={"original_file": source.name},
                )
            ],
            source_features={"kind": "document", "knowledge_only": True},
        )
    if suffix == ".csv":
        return _parse_csv(source, max_rows)
    if suffix in STRUCTURED_SUFFIXES:
        compatibility = _parse_delivery_note_with_compat_profile(
            source,
            target_type=target_type,
            max_rows=max_rows,
        )
        if compatibility is not None:
            return compatibility
        return _parse_workbook(source, max_rows)

    from app.application.shipment_excel_etl_ocr import ocr_source_to_workbook

    result = ocr_source_to_workbook(source)
    if not result.get("success"):
        raise EtlError(
            str(result.get("error_code") or "ETL_OCR_FAILED").upper(),
            "OCR 无法可靠还原表格，请更换清晰文件后重试",
        )
    dataset = _parse_workbook(Path(str(result["file_path"])), max_rows)
    dataset.source_features.update(
        {
            "kind": "ocr",
            "source_suffix": suffix,
            "ocr_block_count": int(result.get("block_count") or 0),
            "ocr_meta_lines": list(result.get("meta_lines") or []),
            "ocr_page_count": len(result.get("pages") or []),
        }
    )
    page_by_sheet = {str(page.get("sheet_name") or ""): page for page in result.get("pages") or []}
    for item in dataset.rows:
        page = page_by_sheet.get(item.sheet, {})
        cell_evidence: dict[str, Any] = {}
        low_confidence_fields: list[str] = []
        confidences: list[float] = []
        for field_name, value in item.values.items():
            text = str(value or "").strip()
            if not text:
                continue
            evidence = next(
                (
                    block
                    for block in page.get("blocks") or []
                    if text == str(block.get("text") or "").strip()
                    or text in str(block.get("text") or "")
                ),
                None,
            )
            if not evidence:
                low_confidence_fields.append(field_name)
                cell_evidence[field_name] = {
                    "page": page.get("page_number") or 1,
                    "original_text": text,
                    "confidence": None,
                }
                continue
            raw_confidence = evidence.get("confidence", evidence.get("score"))
            confidence = float(raw_confidence) if isinstance(raw_confidence, (int, float)) else None
            if confidence is not None and confidence > 1:
                confidence /= 100
            if confidence is not None:
                confidences.append(confidence)
            if confidence is None or confidence < 0.8:
                low_confidence_fields.append(field_name)
            cell_evidence[field_name] = {
                "page": page.get("page_number") or 1,
                "original_text": str(evidence.get("text") or text),
                "confidence": confidence,
                "position": {
                    key: evidence.get(key)
                    for key in ("left", "top", "width", "height", "center")
                    if evidence.get(key) is not None
                },
            }
        item.provenance.update(
            {
                "page": page.get("page_number") or 1,
                "table_position": {
                    "sheet": item.sheet,
                    "row": item.row_number,
                    "data_start_row": page.get("data_start_row"),
                },
                "ocr": True,
                "confidence": min(confidences) if confidences else None,
                "low_confidence_fields": sorted(set(low_confidence_fields)),
                "cells": cell_evidence,
                "requires_confirmation": True,
            }
        )
    dataset.warnings.append(
        {
            "code": "ETL_OCR_REVIEW_REQUIRED",
            "message": "OCR 行必须人工复核；无法取得置信度的单元格不会静默写入。",
        }
    )
    return dataset
