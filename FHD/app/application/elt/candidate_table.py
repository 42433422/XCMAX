"""Read the workbook a person already selected, including a filled delivery note."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from app.application.elt.errors import EltError
from app.application.elt.parser_structure import business_note_text, is_footer_or_note_row
from app.application.elt.parser_types import ParsedDataset, ParsedRow
from app.application.elt.targets import get_adapter
from app.application.elt.targets.helpers import is_column_header_label

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


def read_candidate_table(path: str | Path | bytes | bytearray) -> ParsedDataset:
    """Keep each selected sheet's header row and the value rows under it."""
    source = path if isinstance(path, (str, Path)) else BytesIO(bytes(path))
    workbook = load_workbook(source, read_only=True, data_only=False, keep_links=False)
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
                if not values or _values_are_header_labels(values):
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


def _values_are_header_labels(values: dict) -> bool:
    texts = [_cell_text(value) for value in values.values() if _cell_text(value)]
    return len(texts) >= 2 and all(is_column_header_label(text) for text in texts)


def _is_quantity(value) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    text = _cell_text(value).replace(",", "")
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


_DELIVERY_TITLES = ("送货单", "发货单", "出货单")
_GENERIC_SHEET_TITLES = ("出货", "送货", "发货", "回款", "明细", "编号", "台账", "模板", "合计")
_CUSTOMER_LABELS = ("客户名称", "购货单位", "购买单位", "客户")
_OUTPUT_COLUMNS = {
    "产品名称": "产品名称",
    "商品名称": "产品名称",
    "货品名称": "产品名称",
    "品名": "产品名称",
    "产品型号": "型号",
    "数量": "数量",
    "桶数": "数量",
    "件数": "数量",
    "单价": "单价",
    "金额": "金额",
    "规格": "型号",
    "型号": "型号",
}


def _output_key(value) -> str | None:
    """Match a header after removing spaces and a unit suffix such as 数量/件."""
    compact = "".join(_cell_text(value).split()).replace("／", "/")
    if not compact:
        return None
    head = compact.split("/", 1)[0]
    return _OUTPUT_COLUMNS.get(head) or _OUTPUT_COLUMNS.get(compact)


def _sheet_customer(title: str) -> str:
    """A sheet named for one customer, when the note has no customer label."""
    text = title.strip()
    if not text or len(text) > 20:
        return ""
    if any(token in text for token in _GENERIC_SHEET_TITLES):
        return ""
    if any(token in text for token in _DELIVERY_TITLES):
        return ""
    return text


def _pair_after(raw, labels: tuple[str, ...]) -> str:
    cells = [_cell_text(cell) for cell in raw]
    for index, cell in enumerate(cells):
        if cell not in labels or index + 1 >= len(cells):
            continue
        value = cells[index + 1]
        if value and not is_column_header_label(value):
            return value
    return ""


def _delivery_sheet(title: str, occupied: list[tuple[int, tuple]]) -> bool:
    if any(token in title for token in _DELIVERY_TITLES):
        return True
    return any(
        any(token in _cell_text(cell) for token in _DELIVERY_TITLES for cell in raw)
        for _, raw in occupied
    )


def read_delivery_note_business(source: bytes | bytearray | str | Path) -> ParsedDataset | None:
    """Read item lines from a filled delivery note, including one later used as a template.

    Template cleanup blanks those lines. Business rows stay on the filled sheet:
    the banner customer, the column-header row, and the total are not records.
    """
    if isinstance(source, (bytes, bytearray)):
        workbook = load_workbook(BytesIO(source), read_only=True, data_only=False, keep_links=False)
        cached_book = load_workbook(BytesIO(source), read_only=True, data_only=True, keep_links=False)
    else:
        workbook = load_workbook(source, read_only=True, data_only=False, keep_links=False)
        cached_book = load_workbook(source, read_only=True, data_only=True, keep_links=False)
    cached_rows = {
        (worksheet.title, number): raw
        for worksheet in cached_book.worksheets
        for number, raw in enumerate(worksheet.iter_rows(values_only=True), start=1)
    }
    rows: list[ParsedRow] = []
    sheet_name = ""
    try:
        for worksheet in workbook.worksheets:
            occupied: list[tuple[int, tuple]] = []
            for number, raw in enumerate(worksheet.iter_rows(values_only=True), start=1):
                if any(_cell_text(cell) for cell in raw):
                    occupied.append((number, raw))
            if not _delivery_sheet(worksheet.title, occupied):
                continue
            header_at = next(
                (
                    index
                    for index, (_, raw) in enumerate(occupied)
                    if {"产品名称", "数量"} <= {_output_key(cell) for cell in raw}
                ),
                None,
            )
            if header_at is None:
                continue
            customer = ""
            for _, raw in occupied[:header_at]:
                customer = _pair_after(raw, _CUSTOMER_LABELS) or customer
            if not customer:
                customer = _sheet_customer(worksheet.title)
            if not customer:
                continue
            columns: list[tuple[int, str]] = []
            for pos, cell in enumerate(occupied[header_at][1]):
                key = _output_key(cell)
                if key and key not in {item[1] for item in columns}:
                    columns.append((pos, key))
            if not any(key == "产品名称" for _, key in columns):
                continue
            if not any(key == "数量" for _, key in columns):
                continue
            if not sheet_name:
                sheet_name = worksheet.title
            for number, raw in occupied[header_at + 1 :]:
                if is_footer_or_note_row(raw):
                    continue
                values = {"购买单位": customer}
                stored = cached_rows.get((worksheet.title, number)) or ()
                for pos, key in columns:
                    if pos >= len(raw) or is_column_header_label(raw[pos]):
                        continue
                    cell = raw[pos]
                    if isinstance(cell, str) and cell.startswith("="):
                        cell = stored[pos] if pos < len(stored) else None
                        if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                            continue
                    if _cell_text(cell):
                        values[key] = cell
                product = _cell_text(values.get("产品名称"))
                if not product or not _is_quantity(values.get("数量")):
                    continue
                rows.append(
                    ParsedRow(
                        sheet=worksheet.title,
                        row_number=number,
                        values=values,
                        provenance={"source": "reviewed_candidate", "parser": "delivery_note"},
                    )
                )
    finally:
        workbook.close()
        cached_book.close()
    if not rows:
        return None
    headers = [
        header
        for header in ("购买单位", "产品名称", "数量", "单价", "金额", "型号")
        if any(header in row.values for row in rows)
    ]
    return ParsedDataset(
        headers=headers,
        rows=rows,
        source_features={
            "kind": "reviewed_candidate",
            "parser": "delivery_note",
            "headers": headers,
            "sheet_name": sheet_name,
            "business_notes": [],
        },
    )


_UNLOCATED_ISSUE = {
    "code": "ELT_SOURCE_COORDINATE_MISSING",
    "field": "source_row",
    "severity": "error",
    "message": "模型未返回这一行的原表工作表和行号",
}


def dataset_from_business_rows(items: list[dict]) -> ParsedDataset | None:
    """Shipment rows from the database-line model. A column title is not a row.

    Original sheet and row come only from the model. A missing or repeated
    coordinate stays unlocated; this function does not look up a cell.
    """
    rows: list[ParsedRow] = []
    used: set[tuple[str, int]] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        unit = _cell_text(item.get("purchase_unit")) or _cell_text(item.get("customer_name"))
        product = _cell_text(item.get("product_name"))
        quantity = item.get("quantity")
        if (
            not unit
            or not product
            or is_column_header_label(unit)
            or is_column_header_label(product)
            or not _is_quantity(quantity)
        ):
            continue
        values = {"购买单位": unit, "产品名称": product, "数量": quantity}
        for source_key, target in (("unit_price", "单价"), ("amount", "金额"), ("model", "型号")):
            cell = _cell_text(item.get(source_key))
            if cell and not is_column_header_label(cell):
                values[target] = cell
        sheet = _cell_text(item.get("source_sheet"))
        raw_row = _cell_text(item.get("source_row"))
        located = bool(sheet) and raw_row.isdigit() and int(raw_row) >= 1
        number = int(raw_row) if located else -index
        if not located or (sheet, number) in used:
            sheet, number, located = "", -index, False
        used.add((sheet, number))
        provenance: dict = {
            "source": "reviewed_candidate",
            "parser": "database_llm",
            "location": "model" if located else "unlocated",
        }
        cited_range = _cell_text(item.get("source_range"))
        if located and cited_range:
            provenance["source_range"] = cited_range[:40]
        if not located:
            provenance["validation_issues"] = [dict(_UNLOCATED_ISSUE)]
        rows.append(ParsedRow(
            sheet=sheet, row_number=number, values=values, provenance=provenance,
        ))
    if not rows:
        return None
    headers = [name for name in ("购买单位", "产品名称", "数量", "单价", "金额", "型号") if any(name in row.values for row in rows)]
    return ParsedDataset(
        headers=headers, rows=rows,
        source_features={"kind": "reviewed_candidate", "parser": "database_llm", "headers": headers, "sheet_name": "", "business_notes": []},
    )


def confirmed_business_table(
    source: str | Path | bytes | bytearray,
) -> tuple[ParsedDataset, str] | None:
    """A table only when its headers name exactly one business target."""
    try:
        table = read_candidate_table(source)
    except EltError as exc:
        if exc.code != "ELT_CANDIDATE_EMPTY":
            raise
        return None
    try:
        return table, match_business_target(table.headers)
    except EltError as exc:
        if exc.code != "ELT_CANDIDATE_TARGET_UNCONFIRMED":
            raise
        return None


def dataset_from_document_text(text: str, source_key: str) -> ParsedDataset:
    """One knowledge row from the archived workbook when it is not a business table."""
    body = str(text or "").strip()
    if not body:
        raise EltError("ELT_KNOWLEDGE_EMPTY", "归档正文为空，不能进入知识库", status_code=409)
    headers = ["内容", "来源键"]
    return ParsedDataset(
        headers=headers,
        rows=[
            ParsedRow(
                sheet="",
                row_number=1,
                values={"内容": body, "来源键": str(source_key or "")[:160]},
                provenance={"source": "reviewed_candidate", "parser": "archived_document"},
            )
        ],
        source_features={
            "kind": "reviewed_candidate",
            "parser": "archived_document",
            "headers": headers,
            "sheet_name": "",
            "business_notes": [],
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
