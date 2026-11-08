"""Committed shipment rows fill the saved delivery-note layout."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.elt.service_support import dump_json
from app.application.elt.shipment_layout_fill import (
    fill_delivery_note_file,
    resolve_owned_shipment_layout,
    write_committed_shipment_workbook,
)
from app.db.db_base import Base
from app.db.models.elt import EltRun, EltRunRow, EltTemplate, EltTemplateVersion, EltUpload
from app.db.models.shipment import ShipmentRecord
from app.infrastructure.tenant_scope import reset_current_tenant_id, set_current_tenant_id


def _layout(path: Path, *, slots: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.title = "送货单"
    worksheet["A1"] = "成都国圣工业有限公司（五星花）送货单"
    worksheet.merge_cells("A1:J1")
    worksheet["A2"] = (
        "购货单位（乙方）：七彩乐园家私    日期：2026年10月24日   订单编号：26-01000054A"
    )
    worksheet.merge_cells("A2:J2")
    worksheet["A3"] = " 产 品 型 号"
    worksheet.merge_cells("A3:C3")
    worksheet["D3"] = " 产 品 名 称"
    worksheet["E3"] = "数量/件"
    worksheet["F3"] = "规格/KG"
    worksheet["G3"] = "数量/KG"
    worksheet["H3"] = "单价/元"
    worksheet["I3"] = "金额/元"
    worksheet["J3"] = "   备  注"
    first = 4
    total = first + slots
    for row in range(first, total):
        worksheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        worksheet.cell(row=row, column=4, value="示例")
    worksheet.cell(row=total, column=1, value="合   计")
    worksheet.merge_cells(start_row=total, start_column=1, end_row=total, end_column=3)
    worksheet.cell(row=total, column=5, value=f"=SUM(E{first}:E{total - 1})")
    clause = total + 1
    worksheet.cell(row=clause, column=1, value="大 写 人 民 币")
    worksheet.cell(row=clause, column=9, value=f"=SUM(I{first}:I{total})")
    contract = total + 2
    worksheet.cell(row=contract, column=1, value="销售协议")
    worksheet.cell(row=contract, column=2, value="合同条款：乙方每次核对型号和数量，不得计入明细。")
    workbook.save(path)
    workbook.close()


def _records() -> list[dict]:
    return [
        {
            "id": 1,
            "model_number": "9803",
            "product_name": "PE白底漆",
            "quantity_tins": 5,
            "tin_spec": 28,
            "unit_price": 9,
            "amount": 1260,
        },
        {
            "id": 2,
            "model_number": "",
            "product_name": "PE白底漆稀料",
            "quantity_tins": 1,
            "tin_spec": 180,
            "unit_price": 6.5,
            "amount": 1170,
            "raw_text": json.dumps({"备注": "加急"}, ensure_ascii=False),
        },
    ]


def _value(cell: str, worksheet) -> float:
    raw = worksheet[cell].value
    if isinstance(raw, str) and raw.startswith("="):
        return _product(raw, worksheet)
    return float(raw)


def _product(formula: str, worksheet) -> float:
    text = str(formula)
    assert text.startswith("=") and "*" in text
    left, right = text[1:].split("*", 1)
    return _value(left, worksheet) * _value(right, worksheet)


def test_fill_keeps_headers_date_formulas_and_contract(tmp_path):
    source = tmp_path / "layout.xlsx"
    _layout(source)
    first = tmp_path / "one.xlsx"
    second = tmp_path / "two.xlsx"
    digest_one = fill_delivery_note_file(source, _records(), first)
    digest_two = fill_delivery_note_file(source, _records(), second)
    assert digest_one == digest_two
    assert first.read_bytes() == second.read_bytes()

    workbook = load_workbook(first, data_only=False)
    worksheet = workbook["送货单"]
    headers = [worksheet.cell(row=3, column=column).value for column in (1, 4, 5, 6, 7, 8, 9, 10)]
    assert [str(value).replace(" ", "") for value in headers] == [
        "产品型号",
        "产品名称",
        "数量/件",
        "规格/KG",
        "数量/KG",
        "单价/元",
        "金额/元",
        "备注",
    ]
    assert "2026年10月24日" in worksheet["A2"].value
    assert worksheet["A4"].value == 9803 or worksheet["A4"].value == "9803"
    assert worksheet["D4"].value == "PE白底漆"
    assert worksheet["E4"].value == 5
    assert worksheet["F4"].value == 28
    assert worksheet["H4"].value == 9
    assert worksheet["G4"].value == "=E4*F4"
    assert worksheet["I4"].value == "=G4*H4"
    assert _product(worksheet["G4"].value, worksheet) == 140
    assert _product(worksheet["I4"].value, worksheet) == 1260
    assert worksheet["J5"].value == "加急"
    assert worksheet["E6"].value == "=SUM(E4:E5)"
    assert str(worksheet["I7"].value).startswith("=SUM(")
    assert "合同条款" in worksheet["B8"].value
    assert worksheet["A6"].value.replace(" ", "") == "合计"
    data_names = [worksheet["D4"].value, worksheet["D5"].value]
    assert "合计" not in data_names
    assert all("合同" not in str(name) for name in data_names)
    workbook.close()


def test_fill_inserts_lines_without_dropping_the_contract(tmp_path):
    source = tmp_path / "layout.xlsx"
    _layout(source, slots=2)
    records = _records() + [
        {
            "id": 3,
            "model_number": "HL-001",
            "product_name": "白面漆",
            "quantity_tins": 2,
            "tin_spec": 25,
            "unit_price": 22,
            "amount": 1100,
        },
        {
            "id": 4,
            "model_number": "535F",
            "product_name": "固化剂",
            "quantity_tins": 4,
            "tin_spec": 10,
            "unit_price": 22,
            "amount": 880,
        },
    ]
    destination = tmp_path / "out.xlsx"
    fill_delivery_note_file(source, records, destination)
    workbook = load_workbook(destination, data_only=False)
    worksheet = workbook["送货单"]
    assert worksheet["D7"].value == "固化剂"
    assert worksheet["G7"].value == "=E7*F7"
    assert worksheet["E8"].value == "=SUM(E4:E7)"
    assert "合同条款" in "".join(
        str(cell.value or "") for row in worksheet.iter_rows(min_row=8) for cell in row
    )
    workbook.close()


def test_layout_resolution_rejects_another_tenant_or_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    layout = tmp_path / "tenants" / "7" / "document_templates" / "11" / "七彩乐园-发货单版式.xlsx"
    _layout(layout)
    outside = tmp_path / "outside.xlsx"
    _layout(outside)
    engine = create_engine(f"sqlite:///{tmp_path / 'etl.sqlite'}")
    Base.metadata.create_all(engine, tables=[EltTemplate.__table__, EltTemplateVersion.__table__])
    session = sessionmaker(bind=engine)()
    token = set_current_tenant_id(7)
    try:
        template = EltTemplate(
            id="owned-layout",
            tenant_id=7,
            owner_user_id=11,
            name="七彩乐园送货单",
            target_type="shipment_records",
            current_version=1,
            description="ELT_SHIPMENT_DOCUMENT_TEMPLATE",
        )
        session.add(template)
        session.add(
            EltTemplateVersion(
                id="ver-1",
                template_id="owned-layout",
                tenant_id=7,
                owner_user_id=11,
                version=1,
                target_type="shipment_records",
                source_features_json=dump_json(
                    {"shipment_document_template": {"file_path": str(layout)}}
                ),
            )
        )
        session.commit()
        found = resolve_owned_shipment_layout(
            "etl:owned-layout", tenant_id=7, owner_user_id=11, db=session
        )
        assert found == layout.resolve()
        assert (
            resolve_owned_shipment_layout(
                "etl:owned-layout", tenant_id=8, owner_user_id=11, db=session
            )
            is None
        )
        assert (
            resolve_owned_shipment_layout(
                "etl:owned-layout", tenant_id=7, owner_user_id=12, db=session
            )
            is None
        )
        session.query(EltTemplateVersion).filter_by(id="ver-1").update(
            {
                "source_features_json": dump_json(
                    {"shipment_document_template": {"file_path": str(outside)}}
                )
            }
        )
        session.commit()
        assert (
            resolve_owned_shipment_layout(
                "etl:owned-layout", tenant_id=7, owner_user_id=11, db=session
            )
            is None
        )
    finally:
        reset_current_tenant_id(token)
        session.close()
        engine.dispose()


def test_completed_run_writes_a_downloadable_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    layout = tmp_path / "tenants" / "7" / "document_templates" / "11" / "note.xlsx"
    _layout(layout)
    engine = create_engine(f"sqlite:///{tmp_path / 'ship.sqlite'}")
    Base.metadata.create_all(engine, tables=[ShipmentRecord.__table__])
    session = sessionmaker(bind=engine)()
    token = set_current_tenant_id(7)
    try:
        session.add(
            ShipmentRecord(
                tenant_id=7,
                purchase_unit="七彩乐园家私",
                product_name="PE白底漆",
                model_number="9803",
                quantity_kg=140,
                quantity_tins=5,
                tin_spec=28,
                unit_price=9,
                amount=1260,
                status="pending",
                parsed_data=json.dumps({"etl_run_id": "run-1"}),
            )
        )
        session.commit()
        run = SimpleNamespace(
            id="run-1",
            tenant_id=7,
            owner_user_id=11,
            target_type="shipment_records",
            status="completed",
            summary_json=dump_json(
                {"shipment_document_template": {"file_path": str(layout), "template_id": "etl:x"}}
            ),
        )
        produced = write_committed_shipment_workbook(session, run)
        assert produced is not None
        saved = tmp_path / "etl" / "exports" / "etl-run-1.xlsx"
        assert saved.is_file()
        assert produced["file_name"] == "etl-run-1.xlsx"
        assert produced["sha256"]
        workbook = load_workbook(saved, data_only=False)
        assert workbook["送货单"]["D4"].value == "PE白底漆"
        assert workbook["送货单"]["G4"].value == "=E4*F4"
        assert "2026年10月24日" in workbook["送货单"]["A2"].value
        workbook.close()
        assert (
            write_committed_shipment_workbook(
                session, SimpleNamespace(id="run-1", target_type="orders", status="completed")
            )
            is None
        )
    finally:
        reset_current_tenant_id(token)
        session.close()
        engine.dispose()


def test_submission_without_layout_downloads_every_preview_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    engine = create_engine(f"sqlite:///{tmp_path / 'trace.sqlite'}")
    Base.metadata.create_all(
        engine,
        tables=[
            EltUpload.__table__,
            EltTemplate.__table__,
            EltTemplateVersion.__table__,
            EltRun.__table__,
            EltRunRow.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    token = set_current_tenant_id(7)
    try:
        session.add(
            EltUpload(
                id="up-trace",
                tenant_id=7,
                owner_user_id=11,
                file_name="trace.xlsx",
                suffix=".xlsx",
                size_bytes=1,
                sha256="a" * 64,
                storage_path="trace.xlsx",
            )
        )
        session.commit()
        session.add(
            EltRun(
                id="run-trace",
                tenant_id=7,
                owner_user_id=11,
                upload_id="up-trace",
                target_type="shipment_records",
                file_sha256="a" * 64,
                status="completed",
            )
        )
        session.commit()
        session.add(
            EltRunRow(
                tenant_id=7,
                run_id="run-trace",
                owner_user_id=11,
                source_sheet="送货",
                source_row=12,
                source_json=dump_json(
                    {"购买单位": "甲", "产品名称": "白漆", "数量": "5", "金额": "40"}
                ),
                normalized_json=dump_json(
                    {
                        "purchase_unit": "甲",
                        "product_name": "白漆",
                        "quantity_kg": "140",
                        "quantity_tins": "5",
                        "amount": "40",
                    }
                ),
                final_action="new",
                execution_status="success",
                after_json=dump_json({"id": 9}),
            )
        )
        session.add(
            EltRunRow(
                tenant_id=7,
                run_id="run-trace",
                owner_user_id=11,
                source_sheet="送货",
                source_row=13,
                source_json=dump_json({"产品名称": "合计"}),
                normalized_json=dump_json({}),
                final_action="skip",
                execution_status="success",
                after_json=dump_json({}),
            )
        )
        session.commit()
        produced = write_committed_shipment_workbook(
            session,
            SimpleNamespace(
                id="run-trace",
                target_type="shipment_records",
                status="completed",
                summary_json="{}",
            ),
        )
        assert produced["file_name"] == "etl-run-trace.xlsx"
        book = load_workbook(tmp_path / "etl" / "exports" / "etl-run-trace.xlsx")
        sheet = book.active
        assert sheet["A2"].value == "送货" and sheet["B2"].value == 12
        assert sheet["C2"].value == "new" and sheet["G2"].value == "5"
        assert sheet["H2"].value == "140" and sheet["M2"].value == 9
        assert sheet["C3"].value == "skip" and sheet["M3"].value in (None, "")
        book.close()
        assert (
            write_committed_shipment_workbook(
                session,
                SimpleNamespace(
                    id="empty",
                    target_type="shipment_records",
                    status="completed",
                    summary_json="{}",
                ),
            )
            is None
        )
    finally:
        reset_current_tenant_id(token)
        session.close()
        engine.dispose()
