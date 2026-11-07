"""Read the workbook a person already selected. No region or business parser."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from app.application.elt.errors import EltError
from app.application.elt.parser_structure import business_note_text, is_footer_or_note_row
from app.application.elt.parser_types import ParsedDataset, ParsedRow
from app.application.elt.targets import get_adapter

_BUSINESS_TARGETS = (
    "customers",
    "products",
    "customer_products",
    "shipment_records",
    "purchase_orders",
    "attendance",
)


def _cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def read_candidate_table(path: str | Path) -> ParsedDataset:
    """Keep each selected sheet's header row and the value rows under it."""
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    rows: list[ParsedRow] = []
    headers: list[str] = []
    notes: list[str] = []
    sheet_name = ""
    try:
        for worksheet in workbook.worksheets:
            occupied: list[tuple[int, tuple]] = []
            for number, raw in enumerate(worksheet.iter_rows(values_only=True), start=1):
                if any(_cell_text(cell) for cell in raw):
                    occupied.append((number, raw))
            header_at = next(
                (
                    index
                    for index, (_, raw) in enumerate(occupied)
                    if sum(bool(_cell_text(cell)) for cell in raw) >= 2
                    and all(
                        not _cell_text(cell).replace(".", "", 1).isdigit()
                        for cell in raw
                        if _cell_text(cell)
                    )
                ),
                None,
            )
            if header_at is None:
                continue
            header_row = occupied[header_at][1]
            named = [
                (pos, _cell_text(cell)) for pos, cell in enumerate(header_row) if _cell_text(cell)
            ]
            for name in (item[1] for item in named):
                if name not in headers:
                    headers.append(name)
            if not sheet_name:
                sheet_name = worksheet.title
            for number, raw in occupied[header_at + 1 :]:
                if is_footer_or_note_row(raw):
                    note = business_note_text(raw)
                    if note and note not in notes:
                        notes.append(note)
                    continue
                values = {
                    name: raw[pos] for pos, name in named if pos < len(raw) and _cell_text(raw[pos])
                }
                if not values:
                    continue
                rows.append(
                    ParsedRow(
                        sheet=worksheet.title,
                        row_number=number,
                        values=values,
                        provenance={"source": "reviewed_candidate"},
                    )
                )
    finally:
        workbook.close()
    if not rows or not headers:
        raise EltError(
            "ELT_CANDIDATE_EMPTY",
            "所选候选没有可写入的表头和记录",
            status_code=409,
        )
    return ParsedDataset(
        headers=headers,
        rows=rows,
        source_features={
            "kind": "reviewed_candidate",
            "parser": "none",
            "headers": headers,
            "sheet_name": sheet_name,
            "business_notes": notes,
        },
    )


def match_business_target(headers: list[str]) -> str:
    """Use a business target only when its required column names are all present."""
    present = {str(header).strip() for header in headers if str(header).strip()}
    matched: list[tuple[int, str]] = []
    for target_type in _BUSINESS_TARGETS:
        adapter = get_adapter(target_type)
        required = [field for field in adapter.fields if field.required]
        if not required:
            continue
        covered = 0
        for field in required:
            names = {field.label, *field.aliases}
            if present.isdisjoint(names):
                covered = 0
                break
            covered += 1
        else:
            matched.append((covered, target_type))
    if len(matched) != 1:
        raise EltError(
            "ELT_CANDIDATE_TARGET_UNCONFIRMED",
            "所选候选的表头不能对应唯一业务目标，未开始写入",
            status_code=409,
        )
    return matched[0][1]
