"""通用表格与 OCR 输入解析。"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable

from app.application.etl.errors import EtlError
from app.application.etl.parser_types import ParsedDataset, ParsedRow

MAX_ROWS = 100_000
STRUCTURED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
OCR_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
KNOWLEDGE_ONLY_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx"}
SUPPORTED_SUFFIXES = STRUCTURED_SUFFIXES | OCR_SUFFIXES | KNOWLEDGE_ONLY_SUFFIXES


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
        from app.application.etl.shipment_compat_parser import (
            parse_delivery_note_with_compat_profile,
        )

        compatibility = parse_delivery_note_with_compat_profile(
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
