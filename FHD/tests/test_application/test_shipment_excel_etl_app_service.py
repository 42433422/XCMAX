from __future__ import annotations

from pathlib import Path

from app.application.shipment_excel_etl_app_service import (
    execute_shipment_excel_etl,
    parse_delivery_notes,
    preview_shipment_excel_etl,
)


SAMPLE_DIR = Path("/Users/a4243342/Desktop/新建文件夹 (4)/产品文件夹/发货单")


def test_parse_guosheng_delivery_note():
    path = SAMPLE_DIR / "国圣化工.xlsx"
    if not path.is_file():
        return
    result = parse_delivery_notes(path)
    assert result["success"] is True
    assert result["note_count"] >= 1
    note = result["notes"][0]
    assert "送货单" in str(note.get("title") or "") or note["score"] >= 60
    assert "国圣" in str(note.get("unit_name") or "")
    assert note["item_count"] >= 1
    assert note["items"][0]["product_name"]


def test_parse_houxuemei_and_yin():
    for name in ("侯雪梅.xlsx", "尹玉华1.xlsx", "现金.xlsx", "澜宇电视柜.xlsx"):
        path = SAMPLE_DIR / name
        if not path.is_file():
            continue
        result = parse_delivery_notes(path)
        assert result["success"] is True, name
        assert result["note_count"] >= 1, name
        assert all(n["item_count"] >= 1 for n in result["notes"]), name


def test_preview_marks_confirm_required():
    path = SAMPLE_DIR / "国圣化工.xlsx"
    if not path.is_file():
        return
    preview = preview_shipment_excel_etl(path)
    assert preview["success"] is True
    assert preview.get("confirm_required") is True
    assert preview.get("product_records")


def test_score_rejects_ledger_only_sheet(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "出货"
    ws.append(["厂名", "日期", "单号", "产品型号", "产品名称", "数量/件"])
    ws.append(["澜宇", 45821, 40, "632", "PE白底漆", 1])
    path = tmp_path / "ledger_only.xlsx"
    wb.save(path)
    result = parse_delivery_notes(path)
    assert result["success"] is True
    assert result["note_count"] == 0


def test_execute_creates_shipment(tmp_path, monkeypatch):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "送货"
    ws["A1"] = "成都国圣工业有限公司（五星花）送货单"
    ws["A2"] = "购货单位：测试客户甲     联系人：张总       2026年01月21日"
    ws.append([])  # row3 unused after we write header at row3
    # openpyxl append after A1/A2 writes at next empty - clearer to set cells
    ws["A3"] = "产品型号"
    ws["D3"] = "产品名称"
    ws["E3"] = "数量/件"
    ws["F3"] = "规格/KG"
    ws["G3"] = "数量/KG"
    ws["H3"] = "单价/元"
    ws["I3"] = "金额/元"
    ws["A4"] = "RX001"
    ws["D4"] = "PU哑光漆"
    ws["E4"] = 2
    ws["F4"] = 25
    ws["G4"] = 50
    ws["H4"] = 17
    ws["I4"] = 850
    path = tmp_path / "delivery.xlsx"
    wb.save(path)

    parsed = parse_delivery_notes(path)
    assert parsed["note_count"] == 1

    calls: list[dict] = []

    class _FakeShipmentSvc:
        def create_shipment(self, unit_name, items_data, contact_person=""):
            calls.append(
                {
                    "unit_name": unit_name,
                    "items_data": items_data,
                    "contact_person": contact_person,
                }
            )
            return {"success": True, "shipment": {"id": 101}}

    monkeypatch.setattr(
        "app.bootstrap.get_shipment_app_service",
        lambda: _FakeShipmentSvc(),
    )
    monkeypatch.setattr(
        "app.services.tools_workflow_registered._execute_excel_import_records",
        lambda records: {"success": True, "imported_count": len(records)},
    )

    result = execute_shipment_excel_etl(path)
    assert result["success"] is True
    assert result["closed_loop"] is True
    assert result["shipment_created"] == 1
    assert calls[0]["unit_name"] == "测试客户甲"
    assert calls[0]["items_data"][0]["model_number"] == "RX001"
