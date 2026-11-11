"""Software keeps one template block together and reuses the same layout."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.application.reviewed_excel_auto_slice import derive_classified_documents
from app.application.reviewed_excel_template import inspect_workbook
from app.application.reviewed_excel_template_blocks import (
    collapse_listed_templates,
    workbook_template_fingerprint,
)
from app.infrastructure.tenant_scope import tenant_scope


def _save(book: Workbook) -> bytes:
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def _classify(body: bytes, documents: list[tuple[str, str]]) -> dict:
    return {
        "source_sha256": inspect_workbook(body)["sha256"],
        "model_status": "returned",
        "regions": [
            {"sheet": sheet, "range": area, "dependencies": []} for sheet, area in documents
        ],
        "suggested_documents": [
            {"fragments": [{"sheet": sheet, "range": area}]} for sheet, area in documents
        ],
    }


def test_title_and_table_of_one_form_stay_one_slice():
    book = Workbook()
    sheet = book.active
    sheet.title = "单据"
    sheet["A1"] = "成都某公司送货单"
    for column, label in enumerate(["品名", "数量", "单价", "金额"], start=1):
        sheet.cell(2, column, label)
    sheet["A3"] = "螺栓"
    sheet["B3"] = 2
    body = _save(book)
    slices = derive_classified_documents(
        body, _classify(body, [("单据", "A1:D1"), ("单据", "A2:D3")])
    )
    assert len(slices) == 1
    saved = load_workbook(BytesIO(slices[0]["workbook"]))
    assert saved["单据"]["A1"].value == "成都某公司送货单"
    assert saved["单据"]["A3"].value == "螺栓"


def test_next_document_heading_is_not_pulled_into_the_previous_form():
    book = Workbook()
    sheet = book.active
    sheet.title = "单据"
    sheet["A1"] = "成都某公司送货单"
    sheet["A2"] = "品名"
    sheet["B2"] = "数量"
    sheet["C2"] = "单价"
    sheet["A3"] = "螺栓"
    sheet["A5"] = "成都某公司退货单"
    sheet["A6"] = "品名"
    sheet["B6"] = "数量"
    sheet["C6"] = "单价"
    body = _save(book)
    slices = derive_classified_documents(
        body,
        _classify(body, [("单据", "A1:C3"), ("单据", "A5:C6")]),
    )
    assert len(slices) == 2
    assert slices[0]["fragments"][0]["range"] == "A1:C3"
    assert slices[1]["fragments"][0]["range"] == "A5:C6"


def test_same_header_layout_becomes_one_template_family(monkeypatch):
    from app.application import reviewed_excel_template_families as families

    book = Workbook()
    sheet = book.active
    sheet.title = "S"
    for column, label in enumerate(["品名", "数量", "单价"], start=1):
        sheet.cell(1, column, label)
        sheet.cell(10, column, label)
    body = _save(book)
    slices = [
        {"fragments": [{"sheet": "S", "range": "A1:C2"}]},
        {"fragments": [{"sheet": "S", "range": "A10:C11"}]},
    ]
    cells = []
    for row in (1, 10):
        for column, label in enumerate(["品名", "数量", "单价"], start=1):
            cells.append(
                {
                    "sheet": "S",
                    "cell": f"{'ABC'[column - 1]}{row}",
                    "value": label,
                    "kind": "text",
                }
            )
    monkeypatch.setattr(
        families,
        "_template_llm_complete",
        lambda *args, **kwargs: SimpleNamespace(
            data={
                "families": [
                    {"members": [0], "reason": "单独"},
                    {"members": [1], "reason": "单独"},
                ]
            }
        ),
    )
    result = families.suggest_template_families(slices, cells, owner_id=7, source_body=body)
    assert [item["members"] for item in result] == [[0, 1]]


def test_different_headers_stay_separate_families(monkeypatch):
    from app.application import reviewed_excel_template_families as families

    book = Workbook()
    sheet = book.active
    sheet.title = "S"
    for column, label in enumerate(["品名", "数量", "单价"], start=1):
        sheet.cell(1, column, label)
    for column, label in enumerate(["日期", "单号", "金额"], start=1):
        sheet.cell(10, column, label)
    body = _save(book)
    slices = [
        {"fragments": [{"sheet": "S", "range": "A1:C2"}]},
        {"fragments": [{"sheet": "S", "range": "A10:C11"}]},
    ]
    cells = [
        {"sheet": "S", "cell": "A1", "value": "品名", "kind": "text"},
        {"sheet": "S", "cell": "B1", "value": "数量", "kind": "text"},
        {"sheet": "S", "cell": "C1", "value": "单价", "kind": "text"},
        {"sheet": "S", "cell": "A10", "value": "日期", "kind": "text"},
        {"sheet": "S", "cell": "B10", "value": "单号", "kind": "text"},
        {"sheet": "S", "cell": "C10", "value": "金额", "kind": "text"},
    ]
    monkeypatch.setattr(
        families,
        "_template_llm_complete",
        lambda *args, **kwargs: SimpleNamespace(
            data={
                "families": [
                    {"members": [0], "reason": "单独"},
                    {"members": [1], "reason": "单独"},
                ]
            }
        ),
    )
    result = families.suggest_template_families(slices, cells, owner_id=7, source_body=body)
    assert [item["members"] for item in result] == [[0], [1]]


def test_cleaned_layout_fingerprint_ignores_zip_bytes():
    def grid() -> bytes:
        book = Workbook()
        sheet = book.active
        sheet.title = "单据"
        sheet["A1"] = "品名"
        sheet["B1"] = "数量"
        sheet["A2"] = None
        return _save(book)

    assert workbook_template_fingerprint(grid()) == workbook_template_fingerprint(grid())
    other = Workbook()
    other.active.title = "单据"
    other.active["A1"] = "单号"
    assert workbook_template_fingerprint(grid()) != workbook_template_fingerprint(_save(other))


def test_library_lists_one_card_for_one_reviewed_layout():
    shared = "a" * 64
    rows = [
        {
            "id": "db:2",
            "db_id": 2,
            "preview_data": {"reviewed_excel": True, "content_fingerprint": shared},
        },
        {
            "id": "db:9",
            "db_id": 9,
            "preview_data": {"reviewed_excel": True, "content_fingerprint": shared},
        },
        {"id": "seed:customer-ledger", "name": "客户资料"},
        {
            "id": "db:3",
            "db_id": 3,
            "preview_data": {"reviewed_excel": True, "content_fingerprint": "b" * 64},
        },
    ]
    listed = collapse_listed_templates(rows)
    assert [item["id"] for item in listed] == ["db:2", "seed:customer-ledger", "db:3"]


def test_saving_the_same_reviewed_layout_reuses_the_template(tmp_path, monkeypatch):
    from app.db import session as db_session
    from app.domain.shared_services.document_templates import crud
    from app.infrastructure.templates import tenant_scope as template_scope

    engine = create_engine(f"sqlite:///{tmp_path / 'templates.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE templates (id INTEGER PRIMARY KEY, template_key TEXT, "
                "template_name TEXT, template_type TEXT, original_file_path TEXT, "
                "analyzed_data TEXT, editable_config TEXT, zone_config TEXT, "
                "merged_cells_config TEXT, style_config TEXT, business_rules TEXT, "
                "is_active INTEGER, tenant_id INTEGER)"
            )
        )
        conn.execute(
            text("CREATE TABLE template_usage_log (template_id INTEGER, action TEXT, result TEXT)")
        )
    monkeypatch.setattr(db_session, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(crud, "_ensure_template_tables_ready", lambda: None)
    monkeypatch.setattr(template_scope, "ensure_templates_tenant_column", lambda: None)

    def payload(path: Path) -> dict:
        return {
            "name": "送货单",
            "template_type": "Excel",
            "category": "excel",
            "business_scope": "custom",
            "source": "reviewed_excel_cleanup",
            "file_path": str(path),
            "fields": [],
            "preview_data": {"reviewed_excel": True},
        }

    book = Workbook()
    book.active.title = "单据"
    book.active["A1"] = "品名"
    book.active["B1"] = "数量"
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    first.write_bytes(_save(book))
    book = Workbook()
    book.active.title = "单据"
    book.active["A1"] = "品名"
    book.active["B1"] = "数量"
    second.write_bytes(_save(book))
    with tenant_scope(1):
        created = crud.create_template_with_payload(payload(first))
        again = crud.create_template_with_payload(payload(second))
    assert created.status_code == 200
    body = created.get_json()
    reused = again.get_json()
    assert body["template"]["id"] == reused["template"]["id"]
    assert reused["reused"] is True
    revision = payload(second)
    revision["name"] = "送货单修订"
    revision["preview_data"] = {"reviewed_excel": True, "revision_parent": {"review_id": 9}}
    with tenant_scope(1):
        forked = crud.create_template_with_payload(revision)
    assert forked.get_json().get("reused") is not True
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM templates")).scalar_one() == 2


def test_print_area_keeps_the_outside_piece_as_its_own_slice():
    book = Workbook()
    sheet = book.active
    sheet.title = "表"
    sheet["A1"] = "考勤表"
    sheet["A2"] = "姓名"
    sheet["B2"] = "日期"
    sheet["A4"] = "末尾"
    sheet.print_area = "A1:B2"
    body = _save(book)
    slices = derive_classified_documents(body, _classify(body, [("表", "A1:B2"), ("表", "A3:B4")]))
    assert [item["fragments"][0]["range"] for item in slices] == ["A1:B2", "A3:B4"]
