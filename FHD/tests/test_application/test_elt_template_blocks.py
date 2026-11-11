"""Software keeps one template block together and reuses the same layout."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Font, Side
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.application.reviewed_excel_auto_slice import derive_classified_documents
from app.application.reviewed_excel_template import inspect_workbook
from app.application.reviewed_excel_template_blocks import (
    collapse_listed_templates,
    join_split_template_blocks,
    merge_same_layout_families,
    template_file_fingerprint,
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


def test_library_lists_one_card_for_one_reviewed_layout(template_store):
    _crud, _engine, root = template_store
    book = Workbook()
    book.active["A1"] = "送货单"
    shared_path, other_path = root / "shared.xlsx", root / "other.xlsx"
    shared_path.write_bytes(_save(book))
    book = Workbook()
    book.active["A1"] = "退货单"
    other_path.write_bytes(_save(book))
    shared = workbook_template_fingerprint(shared_path.read_bytes())
    rows = [
        {
            "id": "db:2",
            "db_id": 2,
            "path": str(shared_path),
            "preview_data": {"reviewed_excel": True, "content_fingerprint": shared},
        },
        {
            "id": "db:9",
            "db_id": 9,
            "path": str(shared_path),
            "preview_data": {"reviewed_excel": True, "content_fingerprint": shared},
        },
        {"id": "seed:customer-ledger", "name": "客户资料"},
        {
            "id": "db:3",
            "db_id": 3,
            "path": str(other_path),
            "preview_data": {"reviewed_excel": True, "content_fingerprint": "b" * 64},
        },
    ]
    with tenant_scope(1):
        listed = collapse_listed_templates(rows)
    assert [item["id"] for item in listed] == ["db:2", "seed:customer-ledger", "db:3"]


@pytest.fixture
def template_store(tmp_path, monkeypatch):
    from app.application import reviewed_excel_template_blocks as blocks
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
                "is_active INTEGER, tenant_id INTEGER, updated_at TEXT)"
            )
        )
        conn.execute(
            text("CREATE TABLE template_usage_log (template_id INTEGER, action TEXT, result TEXT)")
        )
    monkeypatch.setattr(db_session, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(crud, "_ensure_template_tables_ready", lambda: None)
    monkeypatch.setattr(template_scope, "ensure_templates_tenant_column", lambda: None)
    monkeypatch.setattr(blocks, "get_app_data_dir", lambda: str(tmp_path))
    root = tmp_path / "templates" / "reviewed_excel" / "1"
    root.mkdir(parents=True)
    yield crud, engine, root
    engine.dispose()


def _template_payload(path: Path) -> dict:
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


def test_saving_the_same_reviewed_layout_reuses_the_template(template_store):
    crud, engine, root = template_store
    book = Workbook()
    book.active.title = "单据"
    book.active["A1"] = "品名"
    book.active["B1"] = "数量"
    first, second = root / "first.xlsx", root / "second.xlsx"
    body = _save(book)
    first.write_bytes(body)
    second.write_bytes(body)
    with tenant_scope(1):
        created = crud.create_template_with_payload(_template_payload(first))
        again = crud.create_template_with_payload(_template_payload(second))
    assert created.status_code == 200
    body = created.get_json()
    reused = again.get_json()
    assert body["template"]["id"] == reused["template"]["id"]
    assert reused["reused"] is True
    assert reused["template"]["file_path"] == str(first)
    revision = _template_payload(second)
    revision["name"] = "送货单修订"
    revision["preview_data"] = {"reviewed_excel": True, "revision_parent": {"review_id": 9}}
    with tenant_scope(1):
        forked = crud.create_template_with_payload(revision)
    assert forked.status_code == 200
    forked_body = forked.get_json()
    assert forked_body.get("reused") is not True
    assert forked_body["template"]["id"] != body["template"]["id"]
    assert forked_body["template"]["file_path"] == str(second)
    assert (
        forked_body["template"]["preview_data"]["content_fingerprint"]
        == body["template"]["preview_data"]["content_fingerprint"]
    )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM templates")).scalar_one() == 2
    with tenant_scope(1):
        cards = [body["template"], forked_body["template"]]
        assert collapse_listed_templates(cards) == cards


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


def test_distinct_print_areas_keep_adjacent_pieces_separate():
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "姓名"
    sheet["B1"] = "日期"
    sheet["A3"] = "内容"
    sheet["B3"] = "数量"
    sheet.print_area = ["A1:B2", "A3:B4"]
    groups = [
        ([{"sheet": "Sheet", "range": area}], "model", "separate") for area in ("A1:B2", "A3:B4")
    ]
    assert join_split_template_blocks(_save(book), groups) == groups


@pytest.mark.parametrize("title", ["送货单", "退货单", "发货单", "出库单"])
def test_short_document_heading_keeps_adjacent_forms_separate(title):
    book = Workbook()
    book.active["A1"] = "送货单"
    book.active["A2"] = "品名"
    book.active["A4"] = title
    book.active["A5"] = "品名"
    groups = [
        ([{"sheet": "Sheet", "range": area}], "model", "separate") for area in ("A1:C2", "A4:C5")
    ]
    assert join_split_template_blocks(_save(book), groups) == groups


@pytest.mark.parametrize("difference", ["title", "column", "style", "merged", "unavailable"])
def test_matching_header_alone_cannot_override_distinct_family_evidence(difference):
    evidence = {
        "layout_available": True,
        "fragments": [{"sheet": "Sheet", "range": "A1:C4"}],
        "cells": [
            {"row": 0, "column": 0, "value": "送货单", "kind": "text", "style": 1},
            *[
                {"row": 1, "column": column, "value": label, "kind": "text", "style": 0}
                for column, label in enumerate(["品名", "数量", "单价"])
            ],
        ],
        "merged": [[0, 0, 0, 2]],
    }
    other = deepcopy(evidence)
    if difference == "title":
        other["cells"][0]["value"] = "退货单"
    elif difference == "column":
        other["cells"][1]["column"] = 3
    elif difference == "style":
        other["cells"][0]["style"] = 2
    elif difference == "merged":
        other["merged"] = []
    else:
        other["layout_available"] = False
    groups = [{"members": [0], "reason": "one"}, {"members": [1], "reason": "two"}]
    assert merge_same_layout_families(groups, [evidence, other]) == groups


@pytest.mark.parametrize("change", ["column", "row", "format", "border", "font", "print", "merge"])
def test_layout_changes_have_distinct_fingerprints(change):
    book = Workbook()
    sheet = book.active
    sheet["A1"] = "金额"
    original = _save(book)
    book = load_workbook(BytesIO(original))
    sheet = book.active
    if change == "column":
        sheet.column_dimensions["A"].width = 32
    elif change == "row":
        sheet.row_dimensions[1].height = 34
    elif change == "format":
        sheet["A1"].number_format = "0.00"
    elif change == "border":
        sheet["A1"].border = Border(left=Side(style="thin"))
    elif change == "font":
        sheet["A1"].font = Font(bold=True)
    elif change == "print":
        sheet.page_setup.orientation = "landscape"
    else:
        sheet.merge_cells("A1:C1")
    assert workbook_template_fingerprint(original) != workbook_template_fingerprint(_save(book))


def test_package_identity_ignores_archive_order_and_save_timestamps():
    book = Workbook()
    book.active["A1"] = "品名"
    original = _save(book)
    output = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for name in reversed(source.namelist()):
            info = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            content = source.read(name)
            if name == "docProps/core.xml":
                core = ElementTree.fromstring(content)
                for child in core:
                    if child.tag in {
                        "{http://purl.org/dc/terms/}created",
                        "{http://purl.org/dc/terms/}modified",
                    }:
                        child.text = "2020-01-01T00:00:00Z"
                content = ElementTree.tostring(core)
            target.writestr(info, content)
    assert workbook_template_fingerprint(original) == workbook_template_fingerprint(
        output.getvalue()
    )


def test_sparse_extreme_coordinates_do_not_expand_the_entire_rectangle(monkeypatch):
    from app.application import reviewed_excel_template_blocks as blocks

    book = Workbook()
    book.active["A1"] = "标题"
    book.active["XFD1048576"] = "极远单元格"
    body = _save(book)
    monkeypatch.setattr(
        blocks, "load_workbook", lambda *_a, **_k: pytest.fail("must not expand cells")
    )
    assert workbook_template_fingerprint(body) == ""


def test_oversized_zip_is_rejected_before_reading_member_data(monkeypatch):
    from app.application import reviewed_excel_template as review

    body = _save(Workbook())
    monkeypatch.setattr(review, "MAX_UNPACKED", 10)
    monkeypatch.setattr(ZipFile, "read", lambda *_a, **_k: pytest.fail("must check budget first"))
    assert workbook_template_fingerprint(body) == ""


def test_template_file_reads_are_tenant_scoped_regular_and_bounded(template_store, monkeypatch):
    from app.application import reviewed_excel_template_blocks as blocks

    _crud, _engine, root = template_store
    book = Workbook()
    body = _save(book)
    owned = root / "owned.xlsx"
    owned.write_bytes(body)
    assert template_file_fingerprint(str(owned), tenant_id=1)
    assert template_file_fingerprint(str(owned), tenant_id=2) == ""
    assert template_file_fingerprint("/dev/zero", tenant_id=1) == ""
    foreign = root.parent / "2" / "foreign.xlsx"
    foreign.parent.mkdir()
    foreign.write_bytes(body)
    link = root / "foreign-link.xlsx"
    link.symlink_to(foreign)
    assert template_file_fingerprint(str(link), tenant_id=1) == ""
    oversized = root / "oversized.xlsx"
    oversized.write_bytes(b"x" * 101)
    monkeypatch.setattr(blocks, "_MAX_TEMPLATE_BYTES", 100)
    monkeypatch.setattr(
        blocks, "workbook_template_fingerprint", lambda _body: pytest.fail("must not read oversize")
    )
    assert template_file_fingerprint(str(oversized), tenant_id=1) == ""


@pytest.mark.parametrize("through_api", [True, False])
def test_replacement_invalidates_old_identity_and_new_save_keeps_correct_file(
    template_store, through_api
):
    crud, engine, root = template_store
    book = Workbook()
    book.active["A1"] = "送货单"
    first, second = root / "first.xlsx", root / "second.xlsx"
    first.write_bytes(_save(book))
    second.write_bytes(first.read_bytes())
    with tenant_scope(1):
        created = crud.create_template_with_payload(_template_payload(first)).get_json()
        old_fingerprint = created["template"]["preview_data"]["content_fingerprint"]
        book = Workbook()
        book.active["A1"] = "退货单"
        replacement = root / "replacement.xlsx"
        replacement.write_bytes(_save(book))
        if through_api:
            changed = crud.update_template_with_payload(
                {
                    **_template_payload(replacement),
                    "id": created["template"]["id"],
                    "preview_data": {
                        "reviewed_excel": True,
                        "content_fingerprint": old_fingerprint,
                    },
                }
            )
            assert changed.status_code == 200
        else:
            first.write_bytes(replacement.read_bytes())
        again = crud.create_template_with_payload(_template_payload(second)).get_json()
    assert again["template"]["id"] != created["template"]["id"]
    with engine.connect() as conn:
        previous = json.loads(
            conn.execute(text("SELECT analyzed_data FROM templates WHERE id=1")).scalar_one()
        )
        if through_api:
            assert "content_fingerprint" not in previous["preview_data"]
        else:
            assert previous["preview_data"]["content_fingerprint"] == old_fingerprint
    assert second.exists()


def test_library_prefers_usable_replacement_and_rechecks_stale_fingerprints(template_store):
    _crud, _engine, root = template_store
    book = Workbook()
    book.active["A1"] = "送货单"
    body = _save(book)
    good = root / "good.xlsx"
    good.write_bytes(body)
    fingerprint = workbook_template_fingerprint(body)
    rows = [
        {
            "id": "db:1",
            "path": str(root / "missing.xlsx"),
            "exists": False,
            "preview_data": {"reviewed_excel": True, "content_fingerprint": fingerprint},
        },
        {
            "id": "db:2",
            "path": str(good),
            "exists": True,
            "preview_data": {"reviewed_excel": True, "content_fingerprint": "obsolete"},
        },
    ]
    with tenant_scope(1):
        assert [row["id"] for row in collapse_listed_templates(rows)] == ["db:2"]


@pytest.mark.parametrize(
    "difference",
    [
        "width",
        "height",
        "print",
        "blank_border",
        "center",
        "area",
        "repeat_rows",
        "long_text",
        "header",
    ],
)
def test_family_collection_preserves_dimensions_and_print_settings(monkeypatch, difference):
    from app.application import reviewed_excel_template_families as families

    book = Workbook()
    book.active.title = "left"
    book.create_sheet("right")
    cells = []
    slices = []
    for sheet in book.worksheets:
        slices.append({"fragments": [{"sheet": sheet.title, "range": "A1:C2"}]})
        for column, label in enumerate(["品名", "数量", "单价"], start=1):
            cell = sheet.cell(1, column, label)
            cells.append(
                {"sheet": sheet.title, "cell": cell.coordinate, "value": label, "kind": "text"}
            )
    if difference == "width":
        book["right"].column_dimensions["A"].width = 37
    elif difference == "height":
        book["right"].row_dimensions[1].height = 37
    elif difference == "print":
        book["right"].page_setup.orientation = "landscape"
    elif difference == "blank_border":
        book["right"]["B2"].border = Border(bottom=Side(style="thin"))
    elif difference == "center":
        book["right"].print_options.horizontalCentered = True
    elif difference == "area":
        book["right"].print_area = "A1:B2"
    elif difference == "repeat_rows":
        book["right"].print_title_rows = "1:1"
    elif difference == "header":
        book["right"].oddHeader.center.text = "另一家公司"
    else:
        for sheet in book.worksheets:
            value = "相同条款" * 15 + sheet.title
            sheet["A2"] = value
            cells.append({"sheet": sheet.title, "cell": "A2", "value": value, "kind": "text"})
    monkeypatch.setattr(
        families,
        "_template_llm_complete",
        lambda *_a, **_k: SimpleNamespace(
            data={
                "families": [{"members": [0], "reason": "one"}, {"members": [1], "reason": "two"}]
            }
        ),
    )
    assert (
        len(families.suggest_template_families(slices, cells, owner_id=7, source_body=_save(book)))
        == 2
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-swap injection")
def test_parent_directory_replacement_cannot_redirect_the_read(template_store, monkeypatch):
    from app.application import shipment_excel_etl_security as secure

    _crud, _engine, root = template_store
    owned = root / "form.xlsx"
    owned.write_bytes(_save(Workbook()))
    foreign = root.parent / "2"
    foreign.mkdir()
    (foreign / owned.name).write_bytes(owned.read_bytes())
    previous = root.with_name("1-original")
    original_open = secure._open_directory_under_root

    def swap(runtime, parent, **kwargs):
        root.rename(previous)
        root.symlink_to(foreign, target_is_directory=True)
        return original_open(runtime, parent, **kwargs)

    monkeypatch.setattr(secure, "_open_directory_under_root", swap)
    try:
        assert template_file_fingerprint(str(owned), tenant_id=1) == ""
    finally:
        if root.is_symlink():
            root.unlink()
        if previous.exists():
            previous.rename(root)


def test_member_boundaries_and_custom_properties_are_part_of_the_fingerprint():
    base = _save(Workbook())

    def package(parts):
        output = BytesIO()
        with ZipFile(BytesIO(base)) as source, ZipFile(output, "w") as target:
            for name in source.namelist():
                target.writestr(name, source.read(name))
            for name, value in parts.items():
                target.writestr(name, value)
        return output.getvalue()

    joined = package({"xl/media/a.bin": b"first\0xl/media/b.bin\0second"})
    split = package({"xl/media/a.bin": b"first", "xl/media/b.bin": b"second"})
    assert workbook_template_fingerprint(joined) != workbook_template_fingerprint(split)
    assert workbook_template_fingerprint(
        package({"docProps/custom.xml": b"one"})
    ) != workbook_template_fingerprint(package({"docProps/custom.xml": b"two"}))


def test_unverifiable_existing_template_is_not_hidden_by_its_old_identity(template_store):
    _crud, _engine, root = template_store
    body = _save(Workbook())
    good, corrupt = root / "good.xlsx", root / "corrupt.xlsx"
    good.write_bytes(body)
    corrupt.write_bytes(b"different unreadable content")
    rows = [
        {
            "id": f"db:{index}",
            "path": str(path),
            "exists": True,
            "preview_data": {
                "reviewed_excel": True,
                "content_fingerprint": workbook_template_fingerprint(body),
            },
        }
        for index, path in enumerate((good, corrupt), start=1)
    ]
    with tenant_scope(1):
        assert collapse_listed_templates(rows) == rows
