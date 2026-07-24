"""发货单 Excel ETL：按内容指纹识别「送货单」表 → 预览 → 写入客户/产品/发货单。

识别依据（非文件名）：
- 标题行含「送货单」
- 抬头含「购货单位」
- 表头含 产品型号 / 产品名称 / 数量·件 / 规格·KG / 单价 等
"""

from __future__ import annotations

import logging
import re
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


def _find_header_row(ws) -> int | None:
    for row in range(1, min(12, int(ws.max_row or 0) + 1)):
        compact = _norm_header(_joined_row(ws, row))
        has_model = "型号" in compact or "编号" in compact
        has_name = "名称" in compact or "品名" in compact
        has_qty = "数量" in compact
        if has_model and has_name and has_qty:
            return row
    return None


def _map_headers(ws, header_row: int) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for col in range(1, min(16, int(ws.max_column or 0) + 1)):
        key = _norm_header(ws.cell(header_row, col).value)
        if not key:
            continue
        if ("型号" in key or ("编号" in key and "订单" not in key)) and "model_number" not in mapping:
            mapping["model_number"] = col
        elif ("名称" in key or "品名" in key) and "product_name" not in mapping:
            mapping["product_name"] = col
        elif ("数量" in key and ("件" in key or "桶" in key)) and "quantity_tins" not in mapping:
            mapping["quantity_tins"] = col
        elif ("规格" in key) and "tin_spec" not in mapping:
            mapping["tin_spec"] = col
        elif ("数量" in key and ("kg" in key or "公斤" in key)) and "quantity_kg" not in mapping:
            mapping["quantity_kg"] = col
        elif ("单价" in key or "价格" in key) and "unit_price" not in mapping:
            mapping["unit_price"] = col
        elif ("金额" in key) and "amount" not in mapping:
            mapping["amount"] = col
        elif ("备注" in key) and "remark" not in mapping:
            mapping["remark"] = col
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
        # 兜底：购货单位行整段里取冒号后第一段
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


def _parse_items(ws, header_row: int, mapping: dict[str, int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    max_row = int(ws.max_row or 0)
    for row in range(header_row + 1, max_row + 1):
        joined = _joined_row(ws, row)
        if not joined:
            if items:
                # 允许中间空行后继续；连续空行则停
                continue
            continue
        if _STOP_ROW_RE.search(joined):
            break
        model = ""
        name = ""
        if "model_number" in mapping:
            model = str(ws.cell(row, mapping["model_number"]).value or "").strip()
        if "product_name" in mapping:
            name = str(ws.cell(row, mapping["product_name"]).value or "").strip()
        # 有些行型号为空、名称在型号列
        if not name and model and not re.search(r"[A-Za-z0-9]", model):
            name, model = model, ""
        if not name and not model:
            continue
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
            # 可能是合并标题行
            continue
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
        items.append(
            {
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
        )
    return items


def parse_delivery_notes(file_path: str | Path, *, min_score: int = 60) -> dict[str, Any]:
    """解析工作簿中所有送货单表。"""
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

    notes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        for ws in wb.worksheets:
            score = _score_delivery_sheet(ws)
            if score < min_score:
                skipped.append({"sheet": ws.title, "score": score, "reason": "not_delivery_note"})
                continue
            header_row = _find_header_row(ws)
            if header_row is None:
                skipped.append({"sheet": ws.title, "score": score, "reason": "header_not_found"})
                continue
            mapping = _map_headers(ws, header_row)
            if "product_name" not in mapping and "model_number" not in mapping:
                skipped.append({"sheet": ws.title, "score": score, "reason": "columns_incomplete"})
                continue
            meta = _parse_buyer_meta(ws, header_row)
            items = _parse_items(ws, header_row, mapping)
            if not items:
                skipped.append({"sheet": ws.title, "score": score, "reason": "no_items"})
                continue
            if not meta["unit_name"]:
                meta["unit_name"] = path.stem
            notes.append(
                {
                    "sheet": ws.title,
                    "score": score,
                    "unit_name": meta["unit_name"],
                    "contact_person": meta["contact_person"],
                    "order_date": meta["order_date"],
                    "order_number": meta["order_number"],
                    "title": meta["title"],
                    "item_count": len(items),
                    "items": items,
                    "total_amount": round(sum(float(i.get("amount") or 0) for i in items), 2),
                }
            )
    finally:
        wb.close()

    return {
        "success": True,
        "file_path": str(path),
        "file_name": path.name,
        "note_count": len(notes),
        "notes": notes,
        "skipped_sheets": skipped,
        "message": (
            f"识别到 {len(notes)} 张送货单"
            if notes
            else "未识别到送货单（需标题含送货单+购货单位+产品明细表头）"
        ),
    }


def preview_shipment_excel_etl(file_path: str | Path) -> dict[str, Any]:
    parsed = parse_delivery_notes(file_path)
    if not parsed.get("success"):
        return parsed
    notes = parsed.get("notes") or []
    return {
        **parsed,
        "preview": True,
        "product_records": _notes_to_product_records(notes),
        "confirm_required": True,
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
) -> dict[str, Any]:
    """执行闭环：客户+产品+发货单。"""
    if notes is None:
        parsed = parse_delivery_notes(file_path)
        if not parsed.get("success"):
            return parsed
        notes = list(parsed.get("notes") or [])
        file_name = str(parsed.get("file_name") or Path(file_path).name)
    else:
        file_name = Path(file_path).name if file_path else "shipment.xlsx"
        parsed = {"success": True, "file_name": file_name, "notes": notes}

    if not notes:
        return {
            "success": False,
            "message": "没有可导入的送货单",
            "error_code": "no_delivery_notes",
        }

    product_result: dict[str, Any] = {"success": True, "skipped": True}
    if import_products:
        from app.services.tools_workflow_registered import _execute_excel_import_records

        product_result = _execute_excel_import_records(_notes_to_product_records(notes))

    shipment_created = 0
    shipment_failed = 0
    shipment_ids: list[Any] = []
    errors: list[str] = []

    if import_shipments:
        try:
            from app.bootstrap import get_shipment_app_service

            svc = get_shipment_app_service()
        except RECOVERABLE_ERRORS as exc:
            return {
                "success": False,
                "message": f"发货单服务不可用: {exc}",
                "product_result": product_result,
            }

        for note in notes:
            unit = str(note.get("unit_name") or "").strip()
            items = list(note.get("items") or [])
            if not unit or not items:
                shipment_failed += 1
                continue
            result = svc.create_shipment(
                unit_name=unit,
                items_data=items,
                contact_person=str(note.get("contact_person") or ""),
            )
            if result.get("success"):
                shipment_created += 1
                shipment = result.get("shipment") or {}
                if isinstance(shipment, dict) and shipment.get("id") is not None:
                    shipment_ids.append(shipment.get("id"))
            else:
                shipment_failed += 1
                errors.append(str(result.get("message") or "create_shipment failed"))

    ok = shipment_failed == 0 and bool(product_result.get("success", True))
    return {
        "success": ok,
        "message": (
            f"送货单闭环完成：发货单 {shipment_created} 张"
            + (f"，失败 {shipment_failed}" if shipment_failed else "")
            + "；客户/产品已同步"
            if import_products
            else f"送货单闭环完成：发货单 {shipment_created} 张"
        ),
        "file_name": file_name,
        "note_count": len(notes),
        "shipment_created": shipment_created,
        "shipment_failed": shipment_failed,
        "shipment_ids": shipment_ids,
        "product_result": product_result,
        "errors": errors[:8],
        "closed_loop": True,
        "kind": "shipment_delivery_etl",
    }


class ShipmentExcelEtlApplicationService:
    def preview(self, file_path: str | Path) -> dict[str, Any]:
        return preview_shipment_excel_etl(file_path)

    def execute(
        self,
        file_path: str | Path,
        *,
        import_products: bool = True,
        import_shipments: bool = True,
        notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return execute_shipment_excel_etl(
            file_path,
            import_products=import_products,
            import_shipments=import_shipments,
            notes=notes,
        )


_svc: ShipmentExcelEtlApplicationService | None = None


def get_shipment_excel_etl_app_service() -> ShipmentExcelEtlApplicationService:
    global _svc
    if _svc is None:
        _svc = ShipmentExcelEtlApplicationService()
    return _svc
