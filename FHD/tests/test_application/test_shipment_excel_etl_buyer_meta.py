"""相邻单元格买家抽取 + 弱客户名规则。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.application.shipment_etl_profile import clear_profile_cache
from app.application.shipment_excel_etl_app_service import parse_delivery_notes


def test_english_to_adjacent_buyer(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", str(tmp_path / "kb.json"))
    clear_profile_cache()
    from app.domain.app_pure.excel_etl_kb import reset_excel_etl_kb_for_tests

    reset_excel_etl_kb_for_tests(tmp_path / "kb.json")

    path = tmp_path / "do.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "DO"
    ws["A5"] = "To:"
    ws["C5"] = "Semiconductor Technologies Pte Ltd"
    ws["A8"] = "SKU"
    ws["B8"] = "Description"
    ws["C8"] = "Qty"
    ws["A9"] = "A1"
    ws["B9"] = "Cable"
    ws["C9"] = 2
    wb.save(path)

    out = parse_delivery_notes(path, include_ledger=False)
    assert out["success"] is True
    note = out["notes"][0]
    assert "Semiconductor" in str(note.get("unit_name") or "")


def test_header_row_buyer_column_stays_per_row_with_cell_lineage(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", str(tmp_path / "kb.json"))
    clear_profile_cache()
    from app.application.elt.shipment_compat_parser import parse_delivery_note_with_compat_profile
    from app.domain.app_pure.excel_etl_kb import reset_excel_etl_kb_for_tests

    reset_excel_etl_kb_for_tests(tmp_path / "kb.json")
    path = tmp_path / "ship.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "出货单"
    for row in (
        ["购货单位", "品名", "桶数", "公斤", "单价", "金额"],
        ["华东化工有限公司", "面漆", 2, 40, 12.5, 500],
        ["西南涂料有限公司", "底漆", 1, 18, 9, None],
    ):
        ws.append(row)
    wb.save(path)

    parsed = parse_delivery_note_with_compat_profile(
        path, target_type="shipment_records", max_rows=10
    )
    assert parsed is not None
    rows = {row.row_number: row for row in parsed.rows}
    assert {n: r.values["purchase_unit"] for n, r in rows.items()} == {
        2: "华东化工有限公司",
        3: "西南涂料有限公司",
    }
    assert rows[2].provenance["cells"]["purchase_unit"] == "A2"
    assert rows[2].provenance["cells"]["amount"] == "F2"
    assert rows[3].provenance["derived"]["amount"] == ["E3", "D3"]
    assert "amount" not in rows[3].provenance["cells"]


def test_pi_bill_to_not_buyer_po(tmp_path, monkeypatch):
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", str(tmp_path / "kb.json"))
    clear_profile_cache()
    from app.domain.app_pure.excel_etl_kb import reset_excel_etl_kb_for_tests

    reset_excel_etl_kb_for_tests(tmp_path / "kb.json")

    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures" / "network_forms" / "net_PI_sample.xlsx"
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(fixture.parent))
    if not fixture.is_file():
        return
    out = parse_delivery_notes(fixture, include_ledger=False)
    assert out["success"] is True
    unit = str(out["notes"][0].get("unit_name") or "")
    assert "Dukjil" in unit
    assert "PO:" not in unit


def test_purchase_unit_label(tmp_path, monkeypatch):
    monkeypatch.setenv("FHD_SHIPMENT_ETL_LLM", "0")
    monkeypatch.setenv("FHD_EXCEL_ETL_KB_PATH", str(tmp_path / "kb.json"))
    clear_profile_cache()
    from app.domain.app_pure.excel_etl_kb import reset_excel_etl_kb_for_tests

    reset_excel_etl_kb_for_tests(tmp_path / "kb.json")

    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "network_forms"
        / "form_采购订单_七彩乐园.xlsx"
    )
    monkeypatch.setenv("WORKSPACE_ROOT", str(fixture.parent))
    if not fixture.is_file():
        return
    out = parse_delivery_notes(fixture, include_ledger=False)
    assert out["success"] is True
    unit = str(out["notes"][0].get("unit_name") or "")
    assert "七彩乐园" in unit
