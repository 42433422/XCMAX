"""Fill a saved delivery-note layout from committed shipment rows.

The layout keeps its title, date, column order, total formulas, and contract
text. Only the blank lines between the header and the total row are written.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import zipfile
from copy import copy
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.application.elt.errors import EltError
from app.application.elt.parser_structure import clean_cell_text, semantic_key
from app.application.elt.service_support import (
    ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
    load_json,
)
from app.application.elt.transforms import neutralize_spreadsheet_formula
from app.utils.path_io.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)

_STABLE_TIMESTAMP = datetime(1980, 1, 1)
_FORMULA_REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")
_TOTAL_KEYS = {"合计", "总计", "小计", "汇总"}
_FIELD_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("model_number", ("产品型号", "型号")),
    ("product_name", ("产品名称", "品名", "名称")),
    ("quantity_tins", ("数量件", "数量桶", "件数", "桶数")),
    ("tin_spec", ("规格kg", "规格")),
    ("quantity_kg", ("数量kg", "公斤", "数量公斤")),
    ("unit_price", ("单价元", "单价")),
    ("amount", ("金额元", "金额")),
    ("remark", ("备注",)),
)
_TEXT_FIELDS = {"model_number", "product_name", "remark"}


def _match_field(header: str) -> str | None:
    key = semantic_key(header)
    if not key:
        return None
    best: str | None = None
    best_len = -1
    for field, aliases in _FIELD_ALIASES:
        for alias in aliases:
            if key == semantic_key(alias) and len(semantic_key(alias)) > best_len:
                best = field
                best_len = len(semantic_key(alias))
    return best


def _header_map(worksheet: Worksheet) -> tuple[int, dict[str, int]]:
    best_row = 0
    best_map: dict[str, int] = {}
    last_row = min(int(worksheet.max_row or 1), 40)
    last_col = min(int(worksheet.max_column or 1), 30)
    for row in range(1, last_row + 1):
        found: dict[str, int] = {}
        for column in range(1, last_col + 1):
            cell = worksheet.cell(row=row, column=column)
            if isinstance(cell, MergedCell):
                continue
            field = _match_field(clean_cell_text(cell.value))
            if field and field not in found:
                found[field] = column
        if len(found) > len(best_map):
            best_row = row
            best_map = found
    if best_row <= 0 or "product_name" not in best_map or len(best_map) < 3:
        raise EltError("ELT_SHIPMENT_LAYOUT_HEADER_MISSING", "送货单版式缺少表头")
    return best_row, best_map


def _total_row(worksheet: Worksheet, header_row: int) -> int:
    last_col = min(int(worksheet.max_column or 1), 8)
    for row in range(header_row + 1, int(worksheet.max_row or header_row) + 1):
        values = [
            semantic_key(worksheet.cell(row=row, column=column).value)
            for column in range(1, last_col + 1)
        ]
        if any(value in _TOTAL_KEYS for value in values):
            return row
    raise EltError("ELT_SHIPMENT_TEMPLATE_TOTAL_MISSING", "送货单版式缺少合计行")


def _excel_number(value: Any) -> int | float:
    if isinstance(value, bool) or value is None or value == "":
        return 0
    if isinstance(value, Decimal):
        number = value
    else:
        number = Decimal(str(value).replace(",", "").strip() or "0")
    if number == number.to_integral():
        return int(number)
    return float(number)


def _remark(record: dict[str, Any]) -> str:
    for key in ("remark", "note", "备注"):
        text = clean_cell_text(record.get(key))
        if text:
            return text
    raw = record.get("raw_text")
    if isinstance(raw, str) and raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except ValueError:
            return ""
        if isinstance(payload, dict):
            return clean_cell_text(payload.get("备注") or payload.get("remark") or "")
    return ""


def _cell_text(record: dict[str, Any], field: str) -> str:
    if field == "remark":
        return str(neutralize_spreadsheet_formula(_remark(record)) or "")
    return str(neutralize_spreadsheet_formula(clean_cell_text(record.get(field))) or "")


def _set_cell(worksheet: Worksheet, row: int, column: int, value: Any) -> None:
    cell = worksheet.cell(row=row, column=column)
    if isinstance(cell, MergedCell):
        return
    cell.value = value


def _copy_row_style(worksheet: Worksheet, source_row: int, target_row: int, last_col: int) -> None:
    for column in range(1, last_col + 1):
        source = worksheet.cell(row=source_row, column=column)
        target = worksheet.cell(row=target_row, column=column)
        if isinstance(source, MergedCell) or isinstance(target, MergedCell):
            continue
        if source.has_style:
            target.font = copy(source.font)
            target.fill = copy(source.fill)
            target.border = copy(source.border)
            target.alignment = copy(source.alignment)
            target.protection = copy(source.protection)
        target.number_format = source.number_format


def _expand_formulas(worksheet: Worksheet, *, old_total_row: int, extra: int) -> None:
    """Keep total and clause formulas pointed at the rows they named before the insert."""
    if extra <= 0:
        return
    last_slot = old_total_row - 1
    new_total = old_total_row + extra

    def _shift(formula: str) -> str:
        def replace(match: re.Match[str]) -> str:
            row_number = int(match.group(4))
            if row_number >= last_slot:
                row_number += extra
            return f"{match.group(1)}{match.group(2)}{match.group(3)}{row_number}"

        return _FORMULA_REF.sub(replace, formula)

    for row in worksheet.iter_rows(min_row=new_total, max_row=worksheet.max_row or new_total):
        for cell in row:
            if isinstance(cell, MergedCell):
                continue
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.value = _shift(cell.value)


def _write_line(
    worksheet: Worksheet,
    row: int,
    columns: dict[str, int],
    record: dict[str, Any],
) -> None:
    for field in ("model_number", "product_name", "quantity_tins", "tin_spec", "unit_price", "remark"):
        column = columns.get(field)
        if column is None:
            continue
        if field in _TEXT_FIELDS:
            _set_cell(worksheet, row, column, _cell_text(record, field))
        else:
            _set_cell(worksheet, row, column, _excel_number(record.get(field)))
    tins = columns.get("quantity_tins")
    spec = columns.get("tin_spec")
    kilograms = columns.get("quantity_kg")
    price = columns.get("unit_price")
    amount = columns.get("amount")
    if kilograms and tins and spec:
        _set_cell(
            worksheet,
            row,
            kilograms,
            f"={get_column_letter(tins)}{row}*{get_column_letter(spec)}{row}",
        )
    elif kilograms:
        _set_cell(worksheet, row, kilograms, _excel_number(record.get("quantity_kg")))
    if amount and kilograms and price:
        _set_cell(
            worksheet,
            row,
            amount,
            f"={get_column_letter(kilograms)}{row}*{get_column_letter(price)}{row}",
        )
    elif amount:
        _set_cell(worksheet, row, amount, _excel_number(record.get("amount")))


def fill_delivery_note_layout(worksheet: Worksheet, records: list[dict[str, Any]]) -> None:
    """Write committed lines into the blank band of one delivery-note sheet."""
    header_row, columns = _header_map(worksheet)
    total_row = _total_row(worksheet, header_row)
    last_col = max(columns.values())
    slots = total_row - header_row - 1
    if slots < 1:
        raise EltError("ELT_SHIPMENT_LAYOUT_LINES_MISSING", "送货单版式没有可填写的明细行")
    extra = max(0, len(records) - slots)
    if extra:
        style_row = header_row + 1
        worksheet.insert_rows(total_row, extra)
        for offset in range(extra):
            _copy_row_style(worksheet, style_row, total_row + offset, last_col)
        _expand_formulas(worksheet, old_total_row=total_row, extra=extra)
        total_row += extra
    for index, record in enumerate(records):
        _write_line(worksheet, header_row + 1 + index, columns, record)
    # Drop leftover example lines so they cannot become extra records or totals.
    for row in range(header_row + 1 + len(records), total_row):
        for column in columns.values():
            cell = worksheet.cell(row=row, column=column)
            if not isinstance(cell, MergedCell):
                cell.value = None


def save_stable_workbook(workbook: Workbook, destination: Path) -> str:
    """Write an xlsx whose bytes do not change between identical saves."""
    workbook.properties.creator = "xcmax"
    workbook.properties.lastModifiedBy = "xcmax"
    workbook.properties.created = _STABLE_TIMESTAMP
    workbook.properties.modified = _STABLE_TIMESTAMP
    buffer = BytesIO()
    workbook.save(buffer)
    fixed = BytesIO()
    with zipfile.ZipFile(BytesIO(buffer.getvalue()), "r") as source, zipfile.ZipFile(
        fixed, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "docProps/core.xml":
                text = payload.decode("utf-8")
                text = re.sub(r"\d{4}-\d{2}-\d{2}T[^<]+", "1980-01-01T00:00:00Z", text)
                payload = text.encode("utf-8")
            entry = zipfile.ZipInfo(filename=info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            target.writestr(entry, payload)
    body = fixed.getvalue()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def fill_delivery_note_file(
    template_path: str | Path,
    records: list[dict[str, Any]],
    destination: str | Path,
) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(template_path, data_only=False, keep_links=False)
    try:
        if "送货单" in workbook.sheetnames:
            worksheet = workbook["送货单"]
        else:
            worksheet = workbook.active
            if worksheet is None:
                raise EltError("ELT_SHIPMENT_TEMPLATE_SHEET_MISSING", "送货单版式所在工作表不存在")
            worksheet.title = "送货单"
        fill_delivery_note_layout(worksheet, records)
        return save_stable_workbook(workbook, Path(destination))
    finally:
        workbook.close()


def _layout_root(tenant_id: int, owner_user_id: int) -> Path:
    return (
        Path(get_app_data_dir()).resolve()
        / "tenants"
        / str(int(tenant_id))
        / "document_templates"
        / str(int(owner_user_id))
    ).resolve()


def safe_layout_path(raw: object, *, tenant_id: int, owner_user_id: int) -> Path | None:
    text = str(raw or "").strip()
    if not text or tenant_id is None or owner_user_id is None:
        return None
    root = _layout_root(tenant_id, owner_user_id)
    try:
        candidate = Path(text).resolve()
    except OSError:
        return None
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def resolve_owned_shipment_layout(
    template_id: str,
    *,
    tenant_id: int | None,
    owner_user_id: int | None,
    db: Any | None = None,
) -> Path | None:
    """Return the owner's delivery-note file, or None when the id is not theirs."""
    raw_id = str(template_id or "").strip()
    if not raw_id.startswith("etl:") or tenant_id is None or owner_user_id is None:
        return None
    template_key = raw_id[4:].strip()
    if not template_key:
        return None

    def _lookup(session: Any) -> Path | None:
        from app.db.models.elt import EltTemplate, EltTemplateVersion

        template = (
            session.query(EltTemplate)
            .filter(
                EltTemplate.id == template_key,
                EltTemplate.tenant_id == int(tenant_id),
                EltTemplate.owner_user_id == int(owner_user_id),
                EltTemplate.is_active.is_(True),
                EltTemplate.description == ETL_SHIPMENT_DOCUMENT_TEMPLATE_DESCRIPTION,
                EltTemplate.target_type == "shipment_records",
            )
            .first()
        )
        if template is None:
            return None
        version = (
            session.query(EltTemplateVersion)
            .filter(
                EltTemplateVersion.template_id == template.id,
                EltTemplateVersion.version == int(template.current_version or 1),
                EltTemplateVersion.tenant_id == int(tenant_id),
                EltTemplateVersion.owner_user_id == int(owner_user_id),
            )
            .first()
        )
        if version is None:
            return None
        features = load_json(version.source_features_json, {})
        info = features.get("shipment_document_template") if isinstance(features, dict) else None
        if not isinstance(info, dict):
            return None
        return safe_layout_path(
            info.get("file_path"),
            tenant_id=int(tenant_id),
            owner_user_id=int(owner_user_id),
        )

    if db is not None:
        return _lookup(db)
    from app.db.session import get_db

    with get_db() as session:
        return _lookup(session)


def _committed_rows(db: Any, run: Any) -> list[dict[str, Any]]:
    from app.db.models.shipment import ShipmentRecord

    run_id = str(getattr(run, "id", "") or "")
    if not run_id:
        return []
    rows = (
        db.query(ShipmentRecord)
        .filter(ShipmentRecord.parsed_data.contains(run_id))
        .order_by(ShipmentRecord.id.asc())
        .all()
    )
    selected: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row.parsed_data or "{}")
        except ValueError:
            continue
        if isinstance(payload, dict) and str(payload.get("etl_run_id") or "") == run_id:
            selected.append(row.to_dict())
    return selected


def _saved_layout_path(db: Any, run: Any) -> Path | None:
    details = load_json(getattr(run, "summary_json", None), {})
    if not isinstance(details, dict):
        return None
    saved = details.get("shipment_document_template")
    if not isinstance(saved, dict):
        saved = {}
    tenant_id = getattr(run, "tenant_id", None)
    owner_user_id = getattr(run, "owner_user_id", None)
    if type(tenant_id) is not int or type(owner_user_id) is not int:
        return None
    path = safe_layout_path(
        saved.get("file_path"),
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    if path is not None:
        return path
    template_id = str(saved.get("template_id") or "")
    if not template_id.startswith("etl:"):
        return None
    return resolve_owned_shipment_layout(
        template_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        db=db,
    )


_TRACE_HEADERS = (
    "来源工作表",
    "来源行",
    "去向",
    "购买单位",
    "产品名称",
    "型号",
    "原数量",
    "公斤数",
    "桶数",
    "单价",
    "金额",
    "日期",
    "数据库记录",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first(data: dict[str, Any], *names: str) -> str:
    for name in names:
        text = _text(data.get(name))
        if text:
            return text
    return ""


def _source_date(source: dict[str, Any]) -> str:
    for key, value in source.items():
        if "日期" in str(key):
            text = _text(value)
            if text:
                return text
    return ""


def _trace_rows(db: Any, run_id: str) -> list[Any]:
    from app.db.models.elt import EltRunRow

    return (
        db.query(EltRunRow)
        .filter(EltRunRow.run_id == run_id)
        .order_by(EltRunRow.source_sheet.asc(), EltRunRow.source_row.asc(), EltRunRow.id.asc())
        .all()
    )


def write_submission_trace(db: Any, run: Any, destination: Path) -> str:
    """One row per preview disposition, including rows that were not written."""
    from openpyxl import Workbook

    run_id = str(getattr(run, "id", "") or "")
    book = Workbook()
    sheet = book.active
    sheet.title = "本次提交"
    sheet.append(list(_TRACE_HEADERS))
    for row in _trace_rows(db, run_id):
        source = load_json(row.source_json, {})
        normal = load_json(row.normalized_json, {})
        after = load_json(row.after_json, {})
        source = source if isinstance(source, dict) else {}
        normal = normal if isinstance(normal, dict) else {}
        after = after if isinstance(after, dict) else {}
        disposition = str(row.final_action or "")
        if row.execution_status and row.execution_status != "success":
            disposition = f"{disposition}:{row.execution_status}"
        written = disposition.startswith(("new", "update"))
        sheet.append(
            [
                row.source_sheet,
                row.source_row,
                disposition,
                _first(normal, "purchase_unit") or _first(source, "购买单位"),
                _first(normal, "product_name") or _first(source, "产品名称", "品名"),
                _first(normal, "model_number") or _first(source, "型号"),
                _first(source, "数量"),
                _first(after, "quantity_kg") or _first(normal, "quantity_kg"),
                _first(after, "quantity_tins") or _first(normal, "quantity_tins"),
                _first(after, "unit_price") or _first(normal, "unit_price") or _first(source, "单价"),
                _first(after, "amount") or _first(normal, "amount") or _first(source, "金额"),
                _source_date(source),
                after.get("id") if written else "",
            ]
        )
    return save_stable_workbook(book, destination)


def write_committed_shipment_workbook(db: Any, run: Any) -> dict[str, str] | None:
    """Store this run's result: the saved layout, or the trace of every preview row."""
    if getattr(run, "target_type", "") != "shipment_records":
        return None
    if getattr(run, "status", "") not in {"completed", "partial"}:
        return None
    run_id = str(getattr(run, "id", "") or "")
    if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
        return None
    root = (Path(get_app_data_dir()).resolve() / "etl" / "exports").resolve()
    destination = (root / f"etl-{run_id}.xlsx").resolve()
    if root not in destination.parents:
        return None
    layout = _saved_layout_path(db, run)
    if layout is None:
        if not _trace_rows(db, run_id):
            return None
        digest = write_submission_trace(db, run, destination)
    else:
        digest = fill_delivery_note_file(layout, _committed_rows(db, run), destination)
    return {
        "file_name": destination.name,
        "sha256": digest,
        "download_url": f"/api/elt/runs/{run_id}/download",
    }


__all__ = [
    "fill_delivery_note_file",
    "fill_delivery_note_layout",
    "resolve_owned_shipment_layout",
    "save_stable_workbook",
    "write_committed_shipment_workbook",
]
