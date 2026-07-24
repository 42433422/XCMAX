"""发货单 / 出货流水 Excel ETL：识别 → 预览 → 幂等入库 → 模板回写。

识别依据（非文件名）：
- 送货单：标题含「送货单」+ 购货单位 + 型号/名称/数量表头
- 出货流水：表头含 日期/单号/型号/品名/数量，按单号分组

闭环能力：
- preview / execute（客户+产品+发货单，指纹幂等）
- batch 目录扫描
- 生成送货单/流水测试模板，并从 notes 反推再出单
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_DELIVERY_TITLE_RE = re.compile(r"送货单")
_BUYER_RE = re.compile(
    r"购货单位[（(]?[乙乙方]*[)）]?[：:\s]*([^\s联系人日期订单编号]+(?:\s*[家私厂公司化工柜]*)?)",
    re.UNICODE,
)
_CONTACT_RE = re.compile(r"联系人[：:\s]*([^\s日期订单编号购货]*)")
_DATE_RE = re.compile(r"((?:20)?\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|\d{4}[-/]\d{1,2}[-/]\d{1,2})")
_ORDER_NO_RE = re.compile(r"订单编号[：:\s]*([A-Za-z0-9\-]+)")
_STOP_ROW_RE = re.compile(r"大\s*写|销售协议|销售单位|销售负责人|一式四联")
_LEDGER_SHEET_RE = re.compile(r"出货|流水|明细")


def _norm_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ").strip()
    return re.sub(r"\s+", "", text)


def _norm_header(value: Any) -> str:
    return _norm_cell(value).lower()


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(_to_float(value, float(default))))
    except (TypeError, ValueError):
        return default


def _row_texts(ws, row: int, max_col: int = 16) -> list[str]:
    out: list[str] = []
    for col in range(1, max_col + 1):
        raw = ws.cell(row, col).value
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            out.append(text)
    return out


def _joined_row(ws, row: int, max_col: int = 16) -> str:
    return " ".join(_row_texts(ws, row, max_col))


def _score_delivery_sheet(ws) -> int:
    """内容指纹打分：越高越像国圣系送货单。"""
    score = 0
    probe_rows = min(8, int(ws.max_row or 0))
    blob = " ".join(_joined_row(ws, r) for r in range(1, probe_rows + 1))
    compact = _norm_cell(blob)
    if _DELIVERY_TITLE_RE.search(blob):
        score += 50
    if "购货单位" in compact:
        score += 25
    header_hits = 0
    for token in ("产品型号", "产品名称", "数量/件", "数量件", "规格/kg", "规格kg", "单价"):
        if token.replace("/", "") in compact.replace("/", "").lower() or token in compact:
            header_hits += 1
    score += min(header_hits, 5) * 6
    if "金额" in compact:
        score += 5
    return score


def _score_ledger_sheet(ws) -> int:
    """出货流水打分（无「送货单」抬头时使用）。"""
    if _score_delivery_sheet(ws) >= 60:
        return 0
    probe_rows = min(10, int(ws.max_row or 0))
    blob = " ".join(_joined_row(ws, r) for r in range(1, probe_rows + 1))
    compact = _norm_cell(blob)
    score = 0
    if _LEDGER_SHEET_RE.search(str(ws.title or "")) or "出货" in compact or "流水" in compact:
        score += 20
    hits = 0
    for token in ("日期", "单号", "型号", "品名", "名称", "数量", "单价"):
        if token in compact:
            hits += 1
    score += min(hits, 6) * 10
    if "购货单位" in compact and "送货单" not in compact:
        score += 5
    return score


def _find_header_row(ws) -> int | None:
    for row in range(1, min(12, int(ws.max_row or 0) + 1)):
        compact = _norm_header(_joined_row(ws, row))
        has_model = "型号" in compact or "编号" in compact
        has_name = "名称" in compact or "品名" in compact
        has_qty = "数量" in compact
        if has_model and has_name and has_qty:
            return row
    return None


def _find_ledger_header_row(ws) -> int | None:
    for row in range(1, min(16, int(ws.max_row or 0) + 1)):
        compact = _norm_header(_joined_row(ws, row))
        has_order = "单号" in compact
        has_name = "品名" in compact or "名称" in compact
        has_qty = "数量" in compact
        has_model = "型号" in compact or "编号" in compact
        if has_order and has_name and has_qty and (has_model or "规格" in compact):
            return row
    return None


def _map_headers(ws, header_row: int) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col in range(1, min(16, int(ws.max_column or 0) + 1)):
        key = _norm_header(ws.cell(header_row, col).value)
        if not key:
            continue
        if ("型号" in key or ("编号" in key and "订单" not in key and "单号" not in key)) and "model_number" not in mapping:
            mapping["model_number"] = col
        elif ("名称" in key or "品名" in key) and "product_name" not in mapping:
            mapping["product_name"] = col
        elif ("数量" in key and ("件" in key or "桶" in key)) and "quantity_tins" not in mapping:
            mapping["quantity_tins"] = col
        elif ("规格" in key) and "tin_spec" not in mapping:
            mapping["tin_spec"] = col
        elif ("数量" in key and ("kg" in key or "公斤" in key)) and "quantity_kg" not in mapping:
            mapping["quantity_kg"] = col
        elif key in {"数量", "数量/"} and "quantity_tins" not in mapping and "quantity_kg" not in mapping:
            mapping["quantity_tins"] = col
        elif ("单价" in key or "价格" in key) and "unit_price" not in mapping:
            mapping["unit_price"] = col
        elif ("金额" in key) and "amount" not in mapping:
            mapping["amount"] = col
        elif ("备注" in key) and "remark" not in mapping:
            mapping["remark"] = col
        elif "单号" in key and "order_number" not in mapping:
            mapping["order_number"] = col
        elif ("日期" in key or "打单" in key or "购货日" in key) and "order_date" not in mapping:
            mapping["order_date"] = col
    return mapping


def _parse_buyer_meta(ws, header_row: int) -> dict[str, str]:
    meta = {
        "unit_name": "",
        "contact_person": "",
        "order_date": "",
        "order_number": "",
        "title": "",
    }
    for row in range(1, header_row):
        text = _joined_row(ws, row)
        if not text:
            continue
        if not meta["title"] and _DELIVERY_TITLE_RE.search(text):
            meta["title"] = text.strip()
        buyer = _BUYER_RE.search(text.replace("　", " "))
        if buyer and not meta["unit_name"]:
            meta["unit_name"] = buyer.group(1).strip(" ：:　")
        contact = _CONTACT_RE.search(text)
        if contact and not meta["contact_person"]:
            meta["contact_person"] = contact.group(1).strip(" ：:　")
        date_m = _DATE_RE.search(text)
        if date_m and not meta["order_date"]:
            meta["order_date"] = date_m.group(1).replace(" ", "")
        order_m = _ORDER_NO_RE.search(text)
        if order_m and not meta["order_number"]:
            meta["order_number"] = order_m.group(1).strip()
    if not meta["unit_name"]:
        for row in range(1, header_row):
            text = _joined_row(ws, row)
            if "购货单位" not in text:
                continue
            after = re.split(r"购货单位[（(]?[乙乙方]*[)）]?[：:]", text, maxsplit=1)
            if len(after) > 1:
                chunk = re.split(r"联系人|日期|订单编号", after[1], maxsplit=1)[0]
                meta["unit_name"] = chunk.strip(" ：:　")
                break
    return meta


def _build_item_from_row(ws, row: int, mapping: dict[str, int]) -> dict[str, Any] | None:
    model = ""
    name = ""
    if "model_number" in mapping:
        model = str(ws.cell(row, mapping["model_number"]).value or "").strip()
    if "product_name" in mapping:
        name = str(ws.cell(row, mapping["product_name"]).value or "").strip()
    if not name and model and not re.search(r"[A-Za-z0-9]", model):
        name, model = model, ""
    if not name and not model:
        return None
    tins = _to_int(ws.cell(row, mapping["quantity_tins"]).value) if "quantity_tins" in mapping else 0
    tin_spec = (
        _to_float(ws.cell(row, mapping["tin_spec"]).value) if "tin_spec" in mapping else 0.0
    )
    qty_kg = (
        _to_float(ws.cell(row, mapping["quantity_kg"]).value)
        if "quantity_kg" in mapping
        else 0.0
    )
    unit_price = (
        _to_float(ws.cell(row, mapping["unit_price"]).value)
        if "unit_price" in mapping
        else 0.0
    )
    amount = _to_float(ws.cell(row, mapping["amount"]).value) if "amount" in mapping else 0.0
    if tins <= 0 and qty_kg <= 0 and unit_price <= 0 and amount <= 0:
        return None
    if tin_spec <= 0 and tins > 0 and qty_kg > 0:
        tin_spec = qty_kg / tins
    if qty_kg <= 0 and tins > 0 and tin_spec > 0:
        qty_kg = tins * tin_spec
    if amount <= 0 and unit_price > 0 and qty_kg > 0:
        amount = unit_price * qty_kg
    if tins <= 0 and qty_kg > 0:
        tins = 1
        if tin_spec <= 0:
            tin_spec = qty_kg
    return {
        "product_name": name or model,
        "model_number": model,
        "quantity_tins": max(0, tins),
        "tin_spec": tin_spec or 0.0,
        "spec_per_tin": tin_spec or 0.0,
        "quantity_kg": qty_kg,
        "unit_price": unit_price,
        "amount": amount,
        "quantity": max(1, tins) if tins else 1,
    }


def _parse_items(ws, header_row: int, mapping: dict[str, int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    max_row = int(ws.max_row or 0)
    for row in range(header_row + 1, max_row + 1):
        joined = _joined_row(ws, row)
        if not joined:
            continue
        if _STOP_ROW_RE.search(joined):
            break
        item = _build_item_from_row(ws, row, mapping)
        if item:
            items.append(item)
    return items


def note_fingerprint(note: dict[str, Any]) -> str:
    """内容指纹：同客户+单号+明细再导入可幂等跳过。"""
    payload = {
        "unit": str(note.get("unit_name") or "").strip(),
        "order": str(note.get("order_number") or "").strip(),
        "date": str(note.get("order_date") or "").strip(),
        "items": sorted(
            [
                {
                    "m": str(i.get("model_number") or "").strip().upper(),
                    "n": str(i.get("product_name") or "").strip(),
                    "q": float(i.get("quantity_tins") or i.get("quantity") or 0),
                    "k": float(i.get("quantity_kg") or 0),
                    "p": float(i.get("unit_price") or 0),
                }
                for i in (note.get("items") or [])
            ],
            key=lambda x: (x["m"], x["n"], x["q"], x["k"], x["p"]),
        ),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:28]


def _fingerprint_store_path() -> Path:
    """兼容旧测试 monkeypatch；真实幂等改走 SQLite。"""
    try:
        from app.utils.path_utils import get_data_dir

        root = Path(get_data_dir())
    except RECOVERABLE_ERRORS:
        root = Path.cwd() / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "shipment_etl_fingerprints.json"


def _legacy_json_has_fingerprint(fingerprint: str) -> bool:
    path = _fingerprint_store_path()
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries") if isinstance(data, dict) else None
        return bool(isinstance(entries, dict) and fingerprint in entries)
    except RECOVERABLE_ERRORS:
        return False


def _is_fingerprint_imported(tenant_key: str, fingerprint: str) -> bool:
    from app.application.shipment_excel_etl_fingerprint_store import has_fingerprint

    if has_fingerprint(tenant_key, fingerprint):
        return True
    # 兼容历史 JSON 指纹（无租户）
    return _legacy_json_has_fingerprint(fingerprint)


def _record_fingerprint_now(
    tenant_key: str,
    fingerprint: str,
    *,
    shipment_id: Any = None,
    unit_name: str = "",
    order_number: str = "",
    file_name: str = "",
) -> None:
    from app.application.shipment_excel_etl_fingerprint_store import record_fingerprint

    record_fingerprint(
        tenant_key,
        fingerprint,
        shipment_id=shipment_id,
        unit_name=unit_name,
        order_number=order_number,
        file_name=file_name,
    )


def _load_fingerprints() -> dict[str, Any]:
    path = _fingerprint_store_path()
    if not path.is_file():
        return {"entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            return data
    except RECOVERABLE_ERRORS:
        logger.warning("failed to load shipment etl fingerprints", exc_info=True)
    return {"entries": {}}


def _save_fingerprints(data: dict[str, Any]) -> None:
    path = _fingerprint_store_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _enrich_note(note: dict[str, Any]) -> dict[str, Any]:
    out = dict(note)
    out["sheet_name"] = str(out.get("sheet_name") or out.get("sheet") or "")
    out["sheet"] = out["sheet_name"] or str(out.get("sheet") or "")
    out["fingerprint"] = note_fingerprint(out)
    out["item_count"] = len(out.get("items") or [])
    out["total_amount"] = round(
        sum(float(i.get("amount") or 0) for i in (out.get("items") or [])), 2
    )
    return out


def _parse_delivery_sheet(ws, *, fallback_unit: str) -> dict[str, Any] | None:
    header_row = _find_header_row(ws)
    if header_row is None:
        return None
    mapping = _map_headers(ws, header_row)
    if "product_name" not in mapping and "model_number" not in mapping:
        return None
    meta = _parse_buyer_meta(ws, header_row)
    items = _parse_items(ws, header_row, mapping)
    if not items:
        return None
    unit = meta["unit_name"] or fallback_unit
    return _enrich_note(
        {
            "sheet": ws.title,
            "source_kind": "delivery_note",
            "score": _score_delivery_sheet(ws),
            "unit_name": unit,
            "contact_person": meta["contact_person"],
            "order_date": meta["order_date"],
            "order_number": meta["order_number"],
            "title": meta["title"],
            "items": items,
        }
    )


def _excel_date_to_str(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float)):
        try:
            from openpyxl.utils.datetime import from_excel

            return from_excel(value).strftime("%Y-%m-%d")
        except RECOVERABLE_ERRORS:
            return str(value)
    text = str(value).strip()
    date_m = _DATE_RE.search(text)
    return (date_m.group(1).replace(" ", "") if date_m else text)


def _parse_ledger_sheet(ws, *, fallback_unit: str) -> list[dict[str, Any]]:
    header_row = _find_ledger_header_row(ws)
    if header_row is None:
        return []
    mapping = _map_headers(ws, header_row)
    if "order_number" not in mapping:
        return []
    if "product_name" not in mapping and "model_number" not in mapping:
        return []

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
            order_date = _excel_date_to_str(ws.cell(row, mapping["order_date"]).value)
        bucket = groups.setdefault(
            order_no,
            {
                "sheet": ws.title,
                "source_kind": "shipment_ledger",
                "score": _score_ledger_sheet(ws),
                "unit_name": fallback_unit,
                "contact_person": "",
                "order_date": order_date,
                "order_number": order_no,
                "title": f"{fallback_unit}出货流水/{order_no}",
                "items": [],
            },
        )
        if order_date and not bucket.get("order_date"):
            bucket["order_date"] = order_date
        bucket["items"].append(item)

    return [_enrich_note(g) for g in groups.values() if g.get("items")]


def parse_delivery_notes(
    file_path: str | Path,
    *,
    min_score: int = 60,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
) -> dict[str, Any]:
    """解析工作簿中的送货单表；可选同时解析出货流水并按单号分组。

    include_ledger:
    - True: 送货单 + 流水都收
    - False: 只收送货单
    - \"auto\": 有送货单时忽略同簿流水（避免历史出货记录误入库）；无送货单时再解析流水
    """
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        return {"success": False, "message": f"文件不存在: {path}", "notes": []}

    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        return {"success": False, "message": f"缺少 openpyxl: {exc}", "notes": []}

    try:
        wb = load_workbook(str(path), data_only=True)
    except RECOVERABLE_ERRORS as exc:
        return {"success": False, "message": f"无法读取 Excel: {exc}", "notes": []}

    fallback_unit = (unit_name_hint or path.stem).strip() or path.stem
    delivery_notes: list[dict[str, Any]] = []
    ledger_notes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        for ws in wb.worksheets:
            d_score = _score_delivery_sheet(ws)
            if d_score >= min_score:
                note = _parse_delivery_sheet(ws, fallback_unit=fallback_unit)
                if note:
                    delivery_notes.append(note)
                else:
                    skipped.append({"sheet": ws.title, "score": d_score, "reason": "delivery_parse_failed"})
                continue

            l_score = _score_ledger_sheet(ws)
            if l_score >= 50:
                parsed_ledger = _parse_ledger_sheet(ws, fallback_unit=fallback_unit)
                if parsed_ledger:
                    ledger_notes.extend(parsed_ledger)
                else:
                    skipped.append({"sheet": ws.title, "score": l_score, "reason": "ledger_empty"})
            else:
                skipped.append({"sheet": ws.title, "score": max(d_score, l_score), "reason": "not_delivery_or_ledger"})
    finally:
        wb.close()

    mode = include_ledger
    if isinstance(mode, str):
        mode_l = mode.strip().lower()
        if mode_l in {"1", "true", "yes", "on"}:
            mode = True
        elif mode_l in {"0", "false", "no", "off"}:
            mode = False
        else:
            mode = "auto"

    if mode is True:
        notes = delivery_notes + ledger_notes
    elif mode is False:
        notes = delivery_notes
        for n in ledger_notes:
            skipped.append({"sheet": n.get("sheet"), "score": n.get("score"), "reason": "ledger_disabled"})
    else:
        # auto
        if delivery_notes:
            notes = delivery_notes
            for n in ledger_notes:
                skipped.append(
                    {
                        "sheet": n.get("sheet"),
                        "score": n.get("score"),
                        "reason": "ledger_skipped_auto_has_delivery",
                        "ledger_groups": 1,
                    }
                )
        else:
            notes = ledger_notes

    delivery_count = sum(1 for n in notes if n.get("source_kind") == "delivery_note")
    ledger_count = sum(1 for n in notes if n.get("source_kind") == "shipment_ledger")
    return {
        "success": True,
        "file_path": str(path),
        "file_name": path.name,
        "note_count": len(notes),
        "delivery_note_count": delivery_count,
        "ledger_note_count": ledger_count,
        "ledger_available_count": len(ledger_notes),
        "include_ledger_mode": mode if mode in (True, False) else "auto",
        "notes": notes,
        "skipped_sheets": skipped,
        "message": (
            f"识别到 {len(notes)} 张单据（送货单 {delivery_count} / 流水分组 {ledger_count}）"
            if notes
            else "未识别到送货单或出货流水"
        ),
    }


def preview_shipment_excel_etl(
    file_path: str | Path,
    *,
    include_ledger: bool | str = "auto",
    unit_name_hint: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        resolve_etl_path,
        tenant_key_for_etl,
    )

    try:
        path = resolve_etl_path(file_path, workspace_root=workspace_root, must_exist=True)
    except ShipmentEtlPathError as exc:
        return {"success": False, "message": f"非法文件路径: {exc}", "error_code": "unsafe_path", "notes": []}

    parsed = parse_delivery_notes(
        path,
        include_ledger=include_ledger,
        unit_name_hint=unit_name_hint,
    )
    if not parsed.get("success"):
        return parsed
    notes = parsed.get("notes") or []
    tenant_key = tenant_key_for_etl()
    for note in notes:
        fp = str(note.get("fingerprint") or "")
        note["already_imported"] = bool(fp and _is_fingerprint_imported(tenant_key, fp))
    ledger_available = int(parsed.get("ledger_available_count") or 0)
    return {
        **parsed,
        "preview": True,
        "product_records": _notes_to_product_records(notes),
        "confirm_required": True,
        "duplicate_note_count": sum(1 for n in notes if n.get("already_imported")),
        "ledger_risk": ledger_available > 0 and int(parsed.get("ledger_note_count") or 0) == 0,
        "ledger_available_count": ledger_available,
        "message": parsed.get("message")
        + ("。确认后将写入客户、产品与发货单。" if notes else ""),
    }


def _notes_to_product_records(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for note in notes:
        unit = str(note.get("unit_name") or "").strip()
        for item in note.get("items") or []:
            model = str(item.get("model_number") or "").strip().upper()
            name = str(item.get("product_name") or "").strip()
            key = (unit, model, name)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "unit_name": unit,
                    "product_name": name,
                    "model_number": model,
                    "unit_price": float(item.get("unit_price") or 0),
                }
            )
    return records


def execute_shipment_excel_etl(
    file_path: str | Path,
    *,
    import_products: bool = True,
    import_shipments: bool = True,
    notes: list[dict[str, Any]] | None = None,
    idempotent: bool = True,
    include_ledger: bool | str = False,
    confirm_ledger: bool = False,
    dry_run: bool = False,
    compensate_on_failure: bool = True,
    unit_name_hint: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """执行闭环：客户+产品+发货单（可幂等 / dry-run / 失败补偿）。

    生产默认 include_ledger=False；若要导入流水须 confirm_ledger=True。
    任一建单失败且 compensate_on_failure=True 时，取消本批已新建发货单并删除指纹。
    """
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        resolve_etl_path,
        tenant_key_for_etl,
    )

    path: Path | None = None
    file_name = "shipment.xlsx"
    if file_path:
        try:
            path = resolve_etl_path(file_path, workspace_root=workspace_root, must_exist=notes is None)
            file_name = path.name
        except ShipmentEtlPathError as exc:
            return {
                "success": False,
                "message": f"非法文件路径: {exc}",
                "error_code": "unsafe_path",
            }

    if notes is None:
        if path is None:
            return {"success": False, "message": "缺少 file_path", "error_code": "missing_path"}
        parsed = parse_delivery_notes(
            path,
            include_ledger=include_ledger,
            unit_name_hint=unit_name_hint,
        )
        if not parsed.get("success"):
            return parsed
        notes = [_enrich_note(n) for n in (parsed.get("notes") or [])]
        file_name = str(parsed.get("file_name") or file_name)
        ledger_available = int(parsed.get("ledger_available_count") or 0)
    else:
        notes = [_enrich_note(n) for n in notes]
        ledger_available = sum(1 for n in notes if n.get("source_kind") == "shipment_ledger")

    ledger_notes = [n for n in notes if n.get("source_kind") == "shipment_ledger"]
    if ledger_notes and not confirm_ledger:
        return {
            "success": False,
            "message": (
                f"检测到 {len(ledger_notes)} 张出货流水分组，生产默认禁止直接入库。"
                "请传 confirm_ledger=1 并确认客户归属后再执行。"
            ),
            "error_code": "ledger_confirm_required",
            "ledger_note_count": len(ledger_notes),
            "note_count": len(notes),
        }

    if not notes:
        return {
            "success": False,
            "message": "没有可导入的送货单",
            "error_code": "no_delivery_notes",
        }

    tenant_key = tenant_key_for_etl()
    to_import: list[dict[str, Any]] = []
    skipped_duplicates: list[dict[str, Any]] = []
    for note in notes:
        fp = str(note.get("fingerprint") or note_fingerprint(note))
        note["fingerprint"] = fp
        if idempotent and _is_fingerprint_imported(tenant_key, fp):
            skipped_duplicates.append(
                {
                    "fingerprint": fp,
                    "unit_name": note.get("unit_name"),
                    "order_number": note.get("order_number"),
                }
            )
            continue
        to_import.append(note)

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "message": (
                f"预演：将新建 {len(to_import)} 张，跳过重复 {len(skipped_duplicates)} 张；不会写库"
            ),
            "file_name": file_name,
            "note_count": len(notes),
            "would_create": len(to_import),
            "would_skip": len(skipped_duplicates),
            "notes": to_import,
            "skipped_duplicates": skipped_duplicates,
            "ledger_available_count": ledger_available,
            "closed_loop": False,
            "kind": "shipment_delivery_etl",
        }

    product_result: dict[str, Any] = {"success": True, "skipped": True}
    if import_products and to_import:
        from app.services.tools_workflow_registered import _execute_excel_import_records

        product_result = _execute_excel_import_records(_notes_to_product_records(to_import))
        if not bool(product_result.get("success", True)):
            return {
                "success": False,
                "message": f"客户/产品导入失败，已中止发货单写入：{product_result.get('message') or product_result}",
                "error_code": "product_import_failed",
                "product_result": product_result,
                "note_count": len(notes),
                "closed_loop": False,
            }

    shipment_created = 0
    shipment_failed = 0
    shipment_skipped = len(skipped_duplicates)
    shipment_ids: list[Any] = []
    created_pairs: list[tuple[Any, str]] = []  # (shipment_id, fingerprint)
    errors: list[str] = []
    compensated: list[Any] = []
    compensate_errors: list[str] = []

    if import_shipments and to_import:
        try:
            from app.bootstrap import get_shipment_app_service

            svc = get_shipment_app_service()
        except RECOVERABLE_ERRORS as exc:
            return {
                "success": False,
                "message": f"发货单服务不可用: {exc}",
                "product_result": product_result,
            }

        for note in to_import:
            unit = str(note.get("unit_name") or "").strip()
            items = list(note.get("items") or [])
            if not unit or not items:
                shipment_failed += 1
                errors.append(f"缺少客户或明细: {note.get('order_number') or note.get('sheet')}")
                break
            result = svc.create_shipment(
                unit_name=unit,
                items_data=items,
                contact_person=str(note.get("contact_person") or ""),
                external_order_number=str(note.get("order_number") or ""),
                order_date=str(note.get("order_date") or ""),
                source_fingerprint=str(note.get("fingerprint") or ""),
                source_kind=str(note.get("source_kind") or ""),
            )
            if result.get("success"):
                shipment_created += 1
                shipment = result.get("shipment") or {}
                sid = shipment.get("id") if isinstance(shipment, dict) else None
                fp = str(note.get("fingerprint") or "")
                if sid is not None:
                    shipment_ids.append(sid)
                    created_pairs.append((sid, fp))
                if idempotent and fp:
                    try:
                        _record_fingerprint_now(
                            tenant_key,
                            fp,
                            shipment_id=sid,
                            unit_name=unit,
                            order_number=str(note.get("order_number") or ""),
                            file_name=file_name,
                        )
                    except RECOVERABLE_ERRORS:
                        logger.warning("failed to persist etl fingerprint immediately", exc_info=True)
            else:
                shipment_failed += 1
                errors.append(str(result.get("message") or "create_shipment failed"))
                break

        # 未处理完的剩余 notes 计为未执行失败（避免静默漏导）
        processed = shipment_created + shipment_failed
        if processed < len(to_import) and shipment_failed:
            remaining = len(to_import) - processed
            errors.append(f"因失败中止，另有 {remaining} 张未执行")
            shipment_failed += remaining

        if shipment_failed and created_pairs and compensate_on_failure:
            from app.application.shipment_excel_etl_fingerprint_store import delete_fingerprint

            for sid, fp in created_pairs:
                try:
                    cancel = svc.cancel_shipment(int(sid))
                    if cancel.get("success"):
                        compensated.append(sid)
                    else:
                        # 取消失败则尝试删除
                        deleted = svc.delete_shipment(int(sid))
                        if deleted.get("success"):
                            compensated.append(sid)
                        else:
                            compensate_errors.append(
                                f"补偿失败 shipment_id={sid}: {cancel.get('message') or deleted.get('message')}"
                            )
                except RECOVERABLE_ERRORS as exc:
                    compensate_errors.append(f"补偿异常 shipment_id={sid}: {exc}")
                if fp:
                    try:
                        delete_fingerprint(tenant_key, fp)
                    except RECOVERABLE_ERRORS:
                        logger.warning("failed to delete etl fingerprint on compensate", exc_info=True)
            shipment_created = max(0, shipment_created - len(compensated))
            shipment_ids = [sid for sid in shipment_ids if sid not in set(compensated)]

    ok = shipment_failed == 0 and bool(product_result.get("success", True))
    if not to_import and skipped_duplicates:
        ok = True
    compensated_ok = bool(shipment_failed and compensate_on_failure and created_pairs and not compensate_errors)
    if shipment_failed and compensate_on_failure:
        # 补偿成功后视为「未留下脏发货单」，success=False 但仍可安全重试
        ok = False
    return {
        "success": ok,
        "partial_success": bool(shipment_failed and shipment_ids and not compensate_on_failure),
        "compensated": compensated,
        "compensate_on_failure": compensate_on_failure,
        "compensate_errors": compensate_errors[:8],
        "safe_to_retry": (not shipment_ids) or compensated_ok or ok,
        "message": (
            f"送货单闭环完成：新建 {shipment_created}，跳过重复 {shipment_skipped}"
            + (f"，失败 {shipment_failed}" if shipment_failed else "")
            + (f"，已补偿撤销 {len(compensated)}" if compensated else "")
            + ("；客户/产品已同步" if import_products and to_import else "")
            + ("（部分成功，未启用补偿）" if (shipment_ids and shipment_failed and not compensate_on_failure) else "")
        ),
        "file_name": file_name,
        "note_count": len(notes),
        "shipment_created": shipment_created,
        "shipment_failed": shipment_failed,
        "shipment_skipped": shipment_skipped,
        "shipment_ids": shipment_ids,
        "skipped_duplicates": skipped_duplicates,
        "product_result": product_result,
        "errors": errors[:20],
        "closed_loop": True,
        "idempotent": idempotent,
        "dry_run": False,
        "kind": "shipment_delivery_etl",
        "audit": {
            "tenant_key": tenant_key,
            "file_name": file_name,
            "created": shipment_created,
            "failed": shipment_failed,
            "skipped": shipment_skipped,
            "compensated": len(compensated),
        },
    }


def write_delivery_note_workbook(
    notes: list[dict[str, Any]],
    output_path: str | Path,
    *,
    seller_title: str = "成都修茈测试工厂送货单",
) -> dict[str, Any]:
    """按国圣系版式写出送货单模板（可用于回环验证 / 测试数据）。"""
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        return {"success": False, "message": f"缺少 openpyxl: {exc}"}

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    # remove default later if we create sheets
    default = wb.active
    created = 0
    for idx, note in enumerate(notes or [], start=1):
        unit = str(note.get("unit_name") or f"客户{idx}").strip()
        sheet_name = str(note.get("sheet_name") or note.get("sheet") or unit)[:28] or f"送货{idx}"
        # openpyxl sheet name constraints
        sheet_name = re.sub(r"[\\/*?:\[\]]", "_", sheet_name)[:31]
        if idx == 1:
            ws = default
            ws.title = sheet_name
        else:
            # unique sheet names
            base = sheet_name
            n = 1
            while sheet_name in wb.sheetnames:
                sheet_name = f"{base[:28]}_{n}"
                n += 1
            ws = wb.create_sheet(sheet_name)

        contact = str(note.get("contact_person") or "").strip()
        order_date = str(note.get("order_date") or datetime.now().strftime("%Y年%m月%d日")).strip()
        order_no = str(note.get("order_number") or f"TEST-{idx:04d}").strip()
        ws["A1"] = seller_title
        ws["A2"] = (
            f"购货单位（乙方）：{unit}     联系人：{contact}        "
            f"日期：{order_date}         订单编号：{order_no}"
        )
        headers = ["产品型号", "", "", "产品名称", "数量/件", "规格/KG", "数量/KG", "单价/元", "金额/元"]
        for col, h in enumerate(headers, start=1):
            ws.cell(3, col, h)
        last_row = 3
        for r, item in enumerate(note.get("items") or [], start=4):
            ws.cell(r, 1, item.get("model_number") or "")
            ws.cell(r, 4, item.get("product_name") or "")
            ws.cell(r, 5, item.get("quantity_tins") or item.get("quantity") or 0)
            ws.cell(r, 6, item.get("tin_spec") or item.get("spec_per_tin") or 0)
            ws.cell(r, 7, item.get("quantity_kg") or 0)
            ws.cell(r, 8, item.get("unit_price") or 0)
            ws.cell(r, 9, item.get("amount") or 0)
            last_row = r
        ws.cell(last_row + 2, 1, "大 写：测试联")
        created += 1

    if created == 0:
        ws = default
        ws.title = "送货单"
        ws["A1"] = seller_title
        ws["A2"] = "购货单位（乙方）：示例客户     联系人：测试        日期：2026年07月24日         订单编号：DEMO-0001"
        for col, h in enumerate(
            ["产品型号", "", "", "产品名称", "数量/件", "规格/KG", "数量/KG", "单价/元", "金额/元"],
            start=1,
        ):
            ws.cell(3, col, h)
        ws["A4"] = "RX-DEMO"
        ws["D4"] = "PU哑光清漆"
        ws["E4"] = 2
        ws["F4"] = 25
        ws["G4"] = 50
        ws["H4"] = 18
        ws["I4"] = 900
        created = 1

    wb.save(path)
    wb.close()
    return {
        "success": True,
        "file_path": str(path),
        "sheet_count": created,
        "message": f"已生成送货单模板 {path.name}（{created} 张表）",
    }


def write_ledger_workbook(
    rows: list[dict[str, Any]],
    output_path: str | Path,
    *,
    sheet_name: str = "25出货",
    unit_name: str = "流水测试客户",
) -> dict[str, Any]:
    """写出出货流水模板（日期/单号/型号/品名/数量…）。"""
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        return {"success": False, "message": f"缺少 openpyxl: {exc}"}

    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31] or "25出货"
    headers = ["日期", "单号", "产品型号", "", "", "产品名称", "数量/件", "规格/KG", "数量/KG", "单价/元", "金额/元"]
    for col, h in enumerate(headers, start=1):
        ws.cell(1, col, h)
    sample_rows = rows or [
        {
            "order_date": "2026-07-01",
            "order_number": "L-001",
            "model_number": "GS621",
            "product_name": "PE白底漆",
            "quantity_tins": 2,
            "tin_spec": 25,
            "quantity_kg": 50,
            "unit_price": 8.5,
            "amount": 425,
        },
        {
            "order_date": "2026-07-02",
            "order_number": "L-002",
            "model_number": "RX001",
            "product_name": "PU哑光漆",
            "quantity_tins": 1,
            "tin_spec": 20,
            "quantity_kg": 20,
            "unit_price": 17,
            "amount": 340,
        },
    ]
    for r, row in enumerate(sample_rows, start=2):
        ws.cell(r, 1, row.get("order_date") or "")
        ws.cell(r, 2, row.get("order_number") or "")
        ws.cell(r, 3, row.get("model_number") or "")
        ws.cell(r, 6, row.get("product_name") or "")
        ws.cell(r, 7, row.get("quantity_tins") or 0)
        ws.cell(r, 8, row.get("tin_spec") or 0)
        ws.cell(r, 9, row.get("quantity_kg") or 0)
        ws.cell(r, 10, row.get("unit_price") or 0)
        ws.cell(r, 11, row.get("amount") or 0)
    # embed unit hint in unused title cell for parse fallback via filename usually
    wb.create_sheet("已调价")
    wb.save(path)
    wb.close()
    return {
        "success": True,
        "file_path": str(path),
        "unit_name": unit_name,
        "row_count": len(sample_rows),
        "message": f"已生成出货流水模板 {path.name}",
    }


def regenerate_delivery_notes_from_file(
    file_path: str | Path,
    output_path: str | Path,
    *,
    include_ledger: bool | str = "auto",
) -> dict[str, Any]:
    """解析 → 按标准送货单版式再出单（模板反推闭环）。"""
    parsed = parse_delivery_notes(file_path, include_ledger=include_ledger)
    if not parsed.get("success"):
        return parsed
    notes = parsed.get("notes") or []
    if not notes:
        return {"success": False, "message": "无可反推的单据", "error_code": "no_delivery_notes"}
    written = write_delivery_note_workbook(notes, output_path)
    if not written.get("success"):
        return written
    reparsed = parse_delivery_notes(output_path, include_ledger=False)
    return {
        "success": True,
        "source": parsed,
        "generated": written,
        "reparsed": reparsed,
        "fingerprint_match": (
            {n.get("fingerprint") for n in notes}
            == {n.get("fingerprint") for n in (reparsed.get("notes") or [])}
            if reparsed.get("success")
            else False
        ),
        "message": "模板反推完成",
    }


def batch_preview_shipment_excel_etl(
    directory: str | Path,
    *,
    include_ledger: bool | str = "auto",
    pattern: str = "*.xlsx",
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        resolve_etl_path,
    )

    try:
        root = resolve_etl_path(directory, workspace_root=workspace_root, must_exist=True)
    except ShipmentEtlPathError as exc:
        return {"success": False, "message": f"非法目录: {exc}", "error_code": "unsafe_path", "files": []}
    if not root.is_dir():
        return {"success": False, "message": f"目录不存在: {root}", "files": []}
    files = sorted(root.glob(pattern))
    results = []
    total_notes = 0
    for path in files:
        if path.name.startswith("~$"):
            continue
        preview = preview_shipment_excel_etl(
            path,
            include_ledger=include_ledger,
            unit_name_hint=path.stem,
            workspace_root=workspace_root or root,
        )
        note_count = int(preview.get("note_count") or 0)
        total_notes += note_count
        results.append(
            {
                "file_path": str(path),
                "file_name": path.name,
                "success": bool(preview.get("success")),
                "note_count": note_count,
                "duplicate_note_count": preview.get("duplicate_note_count", 0),
                "message": preview.get("message"),
                "notes": preview.get("notes") or [],
            }
        )
    return {
        "success": True,
        "directory": str(root),
        "file_count": len(results),
        "note_count": total_notes,
        "files": results,
        "message": f"批量预览完成：{len(results)} 个文件，共 {total_notes} 张单据",
    }


def batch_execute_shipment_excel_etl(
    directory: str | Path,
    *,
    include_ledger: bool | str = False,
    pattern: str = "*.xlsx",
    idempotent: bool = True,
    import_products: bool = True,
    import_shipments: bool = True,
    confirm_ledger: bool = False,
    dry_run: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    from app.application.shipment_excel_etl_security import (
        ShipmentEtlPathError,
        batch_execute_allowed,
        resolve_etl_path,
    )

    if not dry_run and not batch_execute_allowed():
        return {
            "success": False,
            "message": "批量入库默认关闭。需设置环境变量 FHD_SHIPMENT_ETL_ALLOW_BATCH=1",
            "error_code": "batch_disabled",
            "files": [],
        }
    try:
        root = resolve_etl_path(directory, workspace_root=workspace_root, must_exist=True)
    except ShipmentEtlPathError as exc:
        return {"success": False, "message": f"非法目录: {exc}", "error_code": "unsafe_path", "files": []}
    if not root.is_dir():
        return {"success": False, "message": f"目录不存在: {root}", "files": []}
    files = sorted(root.glob(pattern))
    if len(files) > 50:
        return {
            "success": False,
            "message": f"批量文件过多（{len(files)}），上限 50，请缩小范围",
            "error_code": "batch_too_large",
            "files": [],
        }
    results = []
    created = skipped = failed = 0
    for path in files:
        if path.name.startswith("~$"):
            continue
        result = execute_shipment_excel_etl(
            path,
            include_ledger=include_ledger,
            unit_name_hint=path.stem,
            idempotent=idempotent,
            import_products=import_products,
            import_shipments=import_shipments,
            confirm_ledger=confirm_ledger,
            dry_run=dry_run,
            workspace_root=workspace_root or root,
        )
        created += int(result.get("shipment_created") or result.get("would_create") or 0)
        skipped += int(result.get("shipment_skipped") or result.get("would_skip") or 0)
        failed += int(result.get("shipment_failed") or 0)
        results.append(
            {
                "file_path": str(path),
                "file_name": path.name,
                "success": bool(result.get("success")),
                "shipment_created": result.get("shipment_created", result.get("would_create", 0)),
                "shipment_skipped": result.get("shipment_skipped", result.get("would_skip", 0)),
                "shipment_failed": result.get("shipment_failed", 0),
                "message": result.get("message"),
                "error_code": result.get("error_code"),
            }
        )
    return {
        "success": failed == 0,
        "directory": str(root),
        "file_count": len(results),
        "shipment_created": created,
        "shipment_skipped": skipped,
        "shipment_failed": failed,
        "files": results,
        "closed_loop": not dry_run,
        "dry_run": dry_run,
        "message": f"{'批量预演' if dry_run else '批量入库'}完成：新建/将建 {created}，跳过 {skipped}，失败 {failed}",
    }


class ShipmentExcelEtlApplicationService:
    def preview(self, file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return preview_shipment_excel_etl(file_path, **kwargs)

    def execute(self, file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return execute_shipment_excel_etl(file_path, **kwargs)

    def batch_preview(self, directory: str | Path, **kwargs: Any) -> dict[str, Any]:
        return batch_preview_shipment_excel_etl(directory, **kwargs)

    def batch_execute(self, directory: str | Path, **kwargs: Any) -> dict[str, Any]:
        return batch_execute_shipment_excel_etl(directory, **kwargs)

    def write_delivery_template(self, notes: list[dict[str, Any]], output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return write_delivery_note_workbook(notes, output_path, **kwargs)

    def write_ledger_template(self, rows: list[dict[str, Any]], output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return write_ledger_workbook(rows, output_path, **kwargs)

    def regenerate(self, file_path: str | Path, output_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        return regenerate_delivery_notes_from_file(file_path, output_path, **kwargs)


_svc: ShipmentExcelEtlApplicationService | None = None


def get_shipment_excel_etl_app_service() -> ShipmentExcelEtlApplicationService:
    global _svc
    if _svc is None:
        _svc = ShipmentExcelEtlApplicationService()
    return _svc
